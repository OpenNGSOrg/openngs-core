"""End-to-end tests for the REST API's `datapoint` routes (Phase 3 backlog item 4,
docs/api-design.md). Mirrors the relevant scenarios in tests/test_cli_datapoints.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openngs.api import app

client = TestClient(app)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENNGS_ORG", "acme-genomics")
    monkeypatch.setenv("OPENNGS_NAMESPACE", "core-lab")
    monkeypatch.setenv("OPENNGS_DB_URL", f"sqlite:///{db_path}")


def _create(plural: str, **fields: object) -> str:
    r = client.post(f"/{plural}", json=fields)
    assert r.status_code == 200, r.text
    return str(r.json()["internal_id"])


def _setup_data_file() -> str:
    _create("sequencing-runs", local_id="RUN-001")
    return _create("data-files", local_id="R1.fastq.gz", produced_by="RUN-001")


def test_create_list_show_round_trip(env: None) -> None:
    data_file_id = _setup_data_file()
    r = client.post(
        "/datapoints",
        json={
            "local_id": "pct-dup",
            "for": "R1.fastq.gz",
            "type": "openngs-dp:percent_duplication",
            "kind": "number",
            "value": "12.3",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "DataPoint"
    dp_id = body["internal_id"]

    r = client.get("/datapoints", params={"for": "R1.fastq.gz"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["internal_id"] == dp_id
    assert rows[0]["value_number"] == 12.3

    r = client.get(f"/datapoints/{dp_id}")
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["value"] == 12.3
    assert shown["datapoint_type"] == "openngs-dp:percent_duplication"
    assert shown["outgoing"] == [
        {
            "predicate": "characterizes",
            "other_type": "DataFile",
            "other_id": data_file_id,
            "other_name": "openngs://acme-genomics/core-lab/data-file/R1.fastq.gz",
        }
    ]
    assert "events" not in shown

    r = client.get(f"/datapoints/{dp_id}", params={"events": "true"})
    events = r.json()["events"]
    assert {e["type"] for e in events} == {"entity_created", "edge_created"}

    # full name form - a {ref} path parameter's default Starlette converter refuses to
    # match literal "/"s, which the full openngs://... name always has; see the matching
    # test in test_api_entities.py for how this was found.
    r = client.get(f"/datapoints/{body['name']}")
    assert r.status_code == 200, r.text
    assert r.json()["internal_id"] == dp_id


def test_create_text_and_boolean_kinds(env: None) -> None:
    _setup_data_file()
    r = client.post(
        "/datapoints",
        json={
            "local_id": "status",
            "for": "R1.fastq.gz",
            "type": "acme:status",
            "kind": "text",
            "value": "PASS",
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        "/datapoints",
        json={
            "local_id": "flagged",
            "for": "R1.fastq.gz",
            "type": "acme:flagged",
            "kind": "boolean",
            "value": "true",
        },
    )
    assert r.status_code == 200, r.text

    rows = client.get("/datapoints", params={"for": "R1.fastq.gz"}).json()
    by_type = {r["datapoint_type"]: r for r in rows}
    assert by_type["acme:status"]["value_text"] == "PASS"
    assert by_type["acme:flagged"]["value_boolean"] is True


def test_create_rejects_bad_kind(env: None) -> None:
    _setup_data_file()
    r = client.post(
        "/datapoints",
        json={
            "local_id": "bad",
            "for": "R1.fastq.gz",
            "type": "x:y",
            "kind": "weird",
            "value": "1",
        },
    )
    assert r.status_code == 400
    assert "must be one of" in r.text


def test_create_rejects_unknown_for_ref(env: None) -> None:
    r = client.post(
        "/datapoints",
        json={"local_id": "orphan", "for": "NOPE", "type": "x:y", "kind": "number", "value": "1"},
    )
    assert r.status_code == 400


def test_create_missing_required_field_is_422(env: None) -> None:
    _setup_data_file()
    r = client.post(
        "/datapoints", json={"local_id": "no-for", "type": "x:y", "kind": "number", "value": "1"}
    )
    assert r.status_code == 422


def test_duplicate_name_without_force_returns_409(env: None) -> None:
    _setup_data_file()
    body = {"local_id": "dup", "for": "R1.fastq.gz", "type": "x:y", "kind": "number", "value": "1"}
    r1 = client.post("/datapoints", json=body)
    assert r1.status_code == 200, r1.text
    r2 = client.post("/datapoints", json=body)
    assert r2.status_code == 409


def test_a_datapoint_name_cannot_be_taken_twice(env: None) -> None:
    _setup_data_file()
    body = {"local_id": "dup", "for": "R1.fastq.gz", "type": "x:y", "kind": "number", "value": "1"}
    assert client.post("/datapoints", json=body).status_code == 200
    assert client.post("/datapoints", json=body).status_code == 409


def test_show_not_found(env: None) -> None:
    r = client.get("/datapoints/nope")
    assert r.status_code == 404


def test_generic_link_characterizes_escape_hatch(env: None) -> None:
    _setup_data_file()
    run2_id = _create("sequencing-runs", local_id="RUN-002")
    dp_id = client.post(
        "/datapoints",
        json={
            "local_id": "shared-dp",
            "for": "R1.fastq.gz",
            "type": "x:y",
            "kind": "number",
            "value": "1",
        },
    ).json()["internal_id"]

    r = client.post("/links/characterizes", json={"from": dp_id, "to": "RUN-002"})
    assert r.status_code == 200, r.text

    shown = client.get(f"/datapoints/{dp_id}").json()
    other_ids = {e["other_id"] for e in shown["outgoing"]}
    assert run2_id in other_ids
    assert len(shown["outgoing"]) == 2
