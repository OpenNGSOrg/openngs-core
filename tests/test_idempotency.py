"""Get-or-create, and the structured conflict body (#4)."""

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
RETURN = {"if_exists": "return"}


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


def _events() -> list[dict[str, Any]]:
    return client.get("/events", params={"limit": 500}).json()


def test_a_repeated_create_reuses_and_emits_no_event(env: dict[str, str]) -> None:
    """The EHR poller re-sees the same patient every few minutes."""
    first = client.post("/subjects", json={"local_id": "SUBJ-1"}, params=RETURN)
    assert first.status_code == 200, first.text
    assert first.json()["created"] is True

    second = client.post("/subjects", json={"local_id": "SUBJ-1"}, params=RETURN)
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["internal_id"] == first.json()["internal_id"]

    # the second call left no trace in the log: nothing happened, so nothing is recorded
    assert len(_events()) == 1


def test_the_conflict_body_is_structured(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    r = client.post("/subjects", json={"local_id": "SUBJ-1"})
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["type"] == "Subject"
    assert detail["name"].endswith("/SUBJ-1")
    assert detail["internal_id"]  # actionable without parsing the prose
    assert "if_exists=return" in detail["detail"]


def test_a_collision_with_a_different_parent_is_not_a_repeat(env: dict[str, str]) -> None:
    """Two subjects' specimens sharing a local ID is a data problem, and returning either
    one silently would bury it."""
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    client.post("/subjects", json={"local_id": "SUBJ-2"})
    client.post("/specimens", json={"local_id": "SPEC-1", "subject": "SUBJ-1"}, params=RETURN)

    ok = client.post("/specimens", json={"local_id": "SPEC-1", "subject": "SUBJ-1"}, params=RETURN)
    assert ok.status_code == 200 and ok.json()["created"] is False

    clash = client.post(
        "/specimens", json={"local_id": "SPEC-1", "subject": "SUBJ-2"}, params=RETURN
    )
    assert clash.status_code == 409
    assert "not derived_from" in clash.json()["detail"]["detail"]


def test_if_exists_must_be_a_known_value(env: dict[str, str]) -> None:
    assert (
        client.post("/subjects", json={"local_id": "S2"}, params={"if_exists": "maybe"}).status_code
        == 422
    )


def test_links_are_idempotent_on_request(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    client.post("/contexts", json={"local_id": "COHORT-1"})
    body = {"from": "SUBJ-1", "to": "COHORT-1"}
    first = client.post("/links/part-of", json=body, params=RETURN)
    second = client.post("/links/part-of", json=body, params=RETURN)
    assert first.json()["created"] is True
    assert second.json()["created"] is False
    assert first.json()["edge_id"] == second.json()["edge_id"]
    # without the flag it is still an error, so an accidental repeat is still caught
    assert client.post("/links/part-of", json=body).status_code == 400


def test_a_whole_batch_is_rerunnable(env: dict[str, str]) -> None:
    """The pipeline completion hook runs twice."""
    ops = {
        "operations": [
            {
                "op": "create",
                "entity_type": "sequencing-run",
                "local_id": "RUN-1",
                "if_exists": "return",
            },
            {"op": "create", "entity_type": "actor", "local_id": "NOVASEQ", "if_exists": "return"},
            {
                "op": "link",
                "predicate": "used",
                "from": "RUN-1",
                "to": "NOVASEQ",
                "if_exists": "return",
            },
        ]
    }
    first = client.post("/batch", json=ops)
    second = client.post("/batch", json=ops)
    assert first.status_code == second.status_code == 200, second.text
    assert [x["created"] for x in first.json()["results"]] == [True, True, True]
    assert [x["created"] for x in second.json()["results"]] == [False, False, False]
    assert len(client.get("/sequencing-runs").json()) == 1
    assert len(client.get("/sequencing-runs/RUN-1").json()["outgoing"]) == 1


def test_datapoint_repeat_versus_correction(env: dict[str, str]) -> None:
    """A DataPoint is its value, so the same value is a repeat and a different one is a
    correction rather than a create."""
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    body = {
        "local_id": "DP-1",
        "for": "SUBJ-1",
        "type": "openngs-dp:percent_duplication",
        "kind": "number",
        "value": "12.3",
    }
    assert client.post("/datapoints", json=body, params=RETURN).json()["created"] is True
    assert client.post("/datapoints", json=body, params=RETURN).json()["created"] is False

    changed = client.post("/datapoints", json={**body, "value": "14.7"}, params=RETURN)
    assert changed.status_code == 409
    assert "correct" in changed.json()["detail"]["detail"]


def test_a_batch_datapoint_and_schema_are_rerunnable_too(env: dict[str, str]) -> None:
    """The batch path applies the same repeat-versus-correction rule the individual routes
    do, so a retried batch carrying a measurement or a schema registration is safe."""
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    ops = {
        "operations": [
            {
                "op": "create_datapoint",
                "local_id": "DP-1",
                "for": "SUBJ-1",
                "datapoint_type": "openngs-dp:percent_duplication",
                "kind": "number",
                "value": "12.3",
                "if_exists": "return",
            },
            {
                "op": "register_schema",
                "local_id": "qc",
                "json_schema": {"$defs": {"A": {"type": "object"}}},
                "if_exists": "return",
            },
        ]
    }
    first = client.post("/batch", json=ops)
    second = client.post("/batch", json=ops)
    assert first.status_code == second.status_code == 200, second.text
    assert [x["created"] for x in first.json()["results"]] == [True, True]
    assert [x["created"] for x in second.json()["results"]] == [False, False]
    assert len(client.get("/datapoints").json()) == 1
    assert len(client.get("/facet-schemas").json()) == 1

    # A changed measurement is a correction, not a repeat, and says so.
    changed = dict(ops["operations"][0], value="14.7")
    r = client.post("/batch", json={"operations": [changed]})
    assert r.status_code == 409
    assert "correct it" in r.json()["detail"]


def test_facet_schema_identical_content_adds_no_version(env: dict[str, str]) -> None:
    schema = {"local_id": "qc", "json_schema": {"$defs": {"A": {"type": "object"}}}}
    first = client.post("/facet-schemas", json=schema, params=RETURN).json()
    again = client.post("/facet-schemas", json=schema, params=RETURN).json()
    assert again["created"] is False
    assert again["schema_id"] == first["schema_id"]

    changed = client.post(
        "/facet-schemas",
        json={"local_id": "qc", "json_schema": {"$defs": {"B": {"type": "object"}}}},
        params=RETURN,
    ).json()
    assert changed["created"] is True  # different content is a genuine new version
    assert len(client.get("/facet-schemas").json()) == 2


def test_cli_if_exists(env: dict[str, str]) -> None:
    runner.invoke(cli_app, ["subject", "create", "SUBJ-1"], env=env)
    r = runner.invoke(
        cli_app,
        ["subject", "create", "SUBJ-1", "--if-exists", "return", "--output", "json"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["name"].endswith("/SUBJ-1")

    # default is still to refuse, and the message says how to opt in
    r = runner.invoke(cli_app, ["subject", "create", "SUBJ-1"], env=env)
    assert r.exit_code == 1
    assert "--if-exists return" in r.output

    # links too, so a shell script that re-runs is safe end to end
    runner.invoke(cli_app, ["context", "create", "COHORT-1"], env=env)
    args = ["link", "part-of", "--from", "SUBJ-1", "--to", "COHORT-1", "--if-exists", "return"]
    first = runner.invoke(cli_app, args, env=env)
    second = runner.invoke(cli_app, args, env=env)
    assert first.exit_code == second.exit_code == 0
    assert first.output.strip() == second.output.strip()


# --- the database is the guarantee (#14) ---------------------------------------------


def test_two_concurrent_writers_cannot_both_create_the_name(env: dict[str, str]) -> None:
    """The client-side check is two statements and cannot be atomic; parallel workers both
    pass it. The unique index is what actually stops them."""
    from datetime import UTC, datetime

    from openngs.store import Database, NameTakenError, build_name, record_entity_created

    url = env["OPENNGS_DB_URL"]
    now = datetime.now(UTC)
    name = build_name("acme-genomics", "core-lab", "Subject", "RACE")

    first = Database.connect(url)
    second = Database.connect(url)
    try:
        record_entity_created(first, "worker-1", "Subject", name, [], now, now)
        first.commit()
        with pytest.raises(NameTakenError, match="already exists"):
            record_entity_created(second, "worker-2", "Subject", name, [], now, now)
            second.commit()
    finally:
        first.close()
        second.close()

    assert len(client.get("/subjects").json()) == 1


def test_a_retracted_name_is_free_again(env: dict[str, str]) -> None:
    """The index is partial, so retraction genuinely releases the name."""
    first = client.post("/subjects", json={"local_id": "REUSE"}).json()["internal_id"]
    client.post("/subjects/REUSE/retract", json={"reason": "mislabelled"})
    second = client.post("/subjects", json={"local_id": "REUSE"})
    assert second.status_code == 200, second.text
    assert second.json()["internal_id"] != first
    assert len(client.get("/subjects").json()) == 1
    assert len(client.get("/subjects", params={"include_retracted": True}).json()) == 2


def test_a_correction_cannot_steal_a_taken_name(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "TAKEN"})
    client.post("/subjects", json={"local_id": "OTHER"})
    r = client.post("/subjects/OTHER/correct", json={"local_id": "TAKEN", "reason": "typo"})
    assert r.status_code == 409
    assert "already has that name" in r.json()["detail"]
