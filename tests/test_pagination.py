"""Cursor pagination across the store, CLI, REST and GraphQL (#3)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openngs.api import app
from openngs.cli import app as cli_app

client = TestClient(app)
runner = CliRunner()
FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    settings = {
        "OPENNGS_ORG": "acme-genomics",
        "OPENNGS_NAMESPACE": "core-lab",
        "OPENNGS_DB_URL": f"sqlite:///{db_path}",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    return settings


def _seed(count: int = 5) -> None:
    """Five subject rows, two of which share a name.

    A believed name is unique now, but the index is *partial*: a retracted row
    keeps its name and a new row may take it again. So two rows can still share a name, and
    a listing that includes retracted ones sees both - which is exactly why the cursor
    still has to break the tie on internal_id. Without it a page boundary between them
    would drop or repeat one.
    """
    for i in range(1, count):
        assert client.post("/subjects", json={"local_id": f"S{i}"}).status_code == 200
    assert client.post("/subjects/S2/retract", json={"reason": "mislabelled"}).status_code == 200
    assert client.post("/subjects", json={"local_id": "S2"}).status_code == 200


def _page_through(page_size: int, include_retracted: bool = True) -> tuple[list[str], int]:
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, Any] = {"limit": page_size, "include_retracted": include_retracted}
        if cursor is not None:
            params["after"] = cursor
        r = client.get("/subjects", params=params)
        assert r.status_code == 200, r.text
        seen += [row["internal_id"] for row in r.json()]
        cursor = r.headers.get("X-Next-Cursor")
        pages += 1
        if cursor is None:
            return seen, pages
        assert pages < 20, "pagination did not terminate"


def test_paging_visits_every_row_exactly_once(env: dict[str, str]) -> None:
    _seed()
    unpaged = [
        row["internal_id"]
        for row in client.get("/subjects", params={"limit": 50, "include_retracted": True}).json()
    ]
    assert len(unpaged) == 5  # four believed, one retracted, two sharing a name

    for page_size in (1, 2, 3, 5):
        seen, _pages = _page_through(page_size)
        assert seen == unpaged, f"page size {page_size}"
        assert len(seen) == len(set(seen))


def test_next_cursor_header_marks_the_last_page(env: dict[str, str]) -> None:
    _seed()
    r = client.get("/subjects", params={"limit": 2})
    assert r.headers["X-Next-Cursor"] == r.json()[-1]["internal_id"]
    # a page that is not full cannot have more after it
    r = client.get("/subjects", params={"limit": 50})
    assert "X-Next-Cursor" not in r.headers


def test_bad_cursor_is_an_error_not_an_empty_page(env: dict[str, str]) -> None:
    """Silently returning [] would end a caller's paging loop early and look like success."""
    _seed()
    r = client.get("/subjects", params={"after": "not-an-id"})
    assert r.status_code == 400
    assert "does not name a Subject row" in r.json()["detail"]


def test_cursor_composes_with_the_other_list_filters(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "SITE-01"})
    for i in range(4):
        client.post(
            "/specimens",
            json={
                "local_id": f"SP{i}",
                "subject": "SITE-01",
                "valid_time": f"2025-0{i + 1}-01T09:00:00",
            },
        )
    params = {"subject": "SITE-01", "valid_from": "2025-02-01", "limit": 2}
    r = client.get("/specimens", params=params)
    first = [row["name"].rsplit("/", 1)[1] for row in r.json()]
    assert first == ["SP1", "SP2"]
    r = client.get("/specimens", params={**params, "after": r.headers["X-Next-Cursor"]})
    assert [row["name"].rsplit("/", 1)[1] for row in r.json()] == ["SP3"]


def test_graphql_after(env: dict[str, str]) -> None:
    _seed()

    def page(args: str) -> list[dict[str, str]]:
        body = client.post("/graphql", json={"query": f"{{ subjects{args} {{ internalId }} }}"})
        data = body.json()
        assert "errors" not in data, data
        rows: list[dict[str, str]] = data["data"]["subjects"]
        return rows

    first = page("(limit: 2, includeRetracted: true)")
    second = page(f'(limit: 2, includeRetracted: true, after: "{first[-1]["internalId"]}")')
    assert [r["internalId"] for r in first] != [r["internalId"] for r in second]
    allrows = page("(limit: 50, includeRetracted: true)")
    assert [r["internalId"] for r in first + second] == [r["internalId"] for r in allrows[:4]]

    bad = client.post(
        "/graphql", json={"query": '{ subjects(after: "not-an-id") { name } }'}
    ).json()
    assert "errors" in bad


def test_cli_after(env: dict[str, str]) -> None:
    _seed()
    r = runner.invoke(cli_app, ["subject", "list", "--limit", "2", "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    first = json.loads(r.output)
    r = runner.invoke(
        cli_app,
        [
            "subject",
            "list",
            "--limit",
            "2",
            "--after",
            first[-1]["internal_id"],
            "--output",
            "json",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    second = json.loads(r.output)
    assert {x["internal_id"] for x in first} & {x["internal_id"] for x in second} == set()

    r = runner.invoke(cli_app, ["subject", "list", "--after", "not-an-id"], env=env)
    assert r.exit_code == 1
    assert "does not name a Subject row" in r.output


def test_facet_and_datapoint_and_schema_lists_paginate(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-001"})
    for i in range(3):
        client.post(
            "/datapoints",
            json={
                "local_id": f"DP-{i}",
                "for": "SUBJ-001",
                "type": "x:m",
                "kind": "number",
                "value": str(i),
            },
        )
        client.post(
            "/facets",
            json={
                "to": "SUBJ-001",
                "schema_url": FIXTURE_SCHEMA,
                "type": "QcMetricsFacet",
                "producer": "p",
                "data": {"metric_name": "m", "metric_value": float(i)},
            },
        )
        client.post(
            "/facet-schemas",
            json={"local_id": "qc", "json_schema": {"$defs": {"X": {"type": "object"}}}},
        )

    for path, key in (
        ("/datapoints", "internal_id"),
        ("/facets", "facet_id"),
        ("/facet-schemas", "schema_id"),
    ):
        r = client.get(path, params={"limit": 2})
        assert len(r.json()) == 2, path
        cursor = r.headers["X-Next-Cursor"]
        assert cursor == r.json()[-1][key]
        rest = client.get(path, params={"limit": 2, "after": cursor}).json()
        assert len(rest) == 1, path
        # every registered schema version is reachable, newest first, without repeats
        seen = [row[key] for row in r.json() + rest]
        assert len(seen) == len(set(seen)) == 3, path


# --- following the event log (#2) ------------------------------------------------------------


def _drain(page_size: int = 3, cursor: str | None = None, **filters: Any) -> list[dict[str, Any]]:
    """A consumer polling the log the way a real one would: page until no cursor comes
    back, then remember the last id."""
    got: list[dict[str, Any]] = []
    for _ in range(20):
        params: dict[str, Any] = {"limit": page_size, **filters}
        if cursor is not None:
            params["after"] = cursor
        r = client.get("/events", params=params)
        assert r.status_code == 200, r.text
        got += r.json()
        nxt = r.headers.get("X-Next-Cursor")
        if nxt is None:
            return got
        cursor = nxt
    raise AssertionError("polling did not terminate")


def test_a_consumer_can_resume_without_gaps_or_repeats(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1"})
    client.post("/specimens", json={"local_id": "SP1", "subject": "S1"})

    first = _drain()
    assert first
    cursor = first[-1]["event_id"]

    # restart with nothing new in between
    assert _drain(cursor=cursor) == []

    client.post("/subjects", json={"local_id": "S2"})
    client.post("/links/part-of", json={"from": "SP1", "to": "S1"})
    resumed = _drain(cursor=cursor)
    assert [e["type"] for e in resumed] == ["entity_created", "edge_created"]

    whole = client.get("/events", params={"limit": 500}).json()
    assert [e["event_id"] for e in first + resumed] == [e["event_id"] for e in whole]


def test_event_type_and_source_filters(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1"})
    client.post("/specimens", json={"local_id": "SP1", "subject": "S1"})

    only_edges = client.get("/events", params={"type": ["edge_created"], "limit": 100}).json()
    assert {e["type"] for e in only_edges} == {"edge_created"}
    both = client.get(
        "/events", params={"type": ["entity_created", "edge_created"], "limit": 100}
    ).json()
    assert {e["type"] for e in both} == {"entity_created", "edge_created"}

    # every write here came through the API
    assert client.get("/events", params={"source": "openngs-api", "limit": 100}).json()
    assert client.get("/events", params={"source": "openngs-cli", "limit": 100}).json() == []

    # filters compose with the cursor
    cursor = only_edges[0]["event_id"]
    rest = client.get(
        "/events", params={"type": ["edge_created"], "after": cursor, "limit": 100}
    ).json()
    assert all(e["event_id"] > cursor for e in rest)
    assert {e["type"] for e in rest} <= {"edge_created"}


def test_unknown_event_type_and_cursor_are_errors(env: dict[str, str]) -> None:
    """A consumer that silently receives nothing cannot tell "quiet" from "asked wrongly"."""
    client.post("/subjects", json={"local_id": "S1"})
    r = client.get("/events", params={"type": ["not_a_type"]})
    assert r.status_code == 400
    assert "unknown event type" in r.json()["detail"]
    assert client.get("/events", params={"after": "not-an-id"}).status_code == 400


def test_event_cursor_on_cli_and_graphql(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1"})
    client.post("/specimens", json={"local_id": "SP1", "subject": "S1"})
    whole = client.get("/events", params={"limit": 500}).json()

    r = runner.invoke(cli_app, ["event", "list", "--limit", "2", "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    first = json.loads(r.output)
    r = runner.invoke(
        cli_app,
        ["event", "list", "--after", first[-1]["event_id"], "--output", "json"],
        env=env,
    )
    rest = json.loads(r.output)
    assert [e["event_id"] for e in first + rest] == [e["event_id"] for e in whole]

    r = runner.invoke(cli_app, ["event", "list", "--type", "nope"], env=env)
    assert r.exit_code == 1
    assert "unknown event type" in r.output

    body = client.post(
        "/graphql",
        json={"query": f'{{ events(after: "{first[-1]["event_id"]}") {{ eventId }} }}'},
    ).json()
    assert [e["eventId"] for e in body["data"]["events"]] == [e["event_id"] for e in rest]
