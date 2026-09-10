"""End-to-end tests for the REST API's `event` routes (Phase 3 backlog item 5,
docs/api-design.md). Mirrors the relevant scenarios in tests/test_cli_events.py."""

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


def test_create_emits_event_with_api_source(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r.status_code == 200, r.text

    events = client.get("/events").json()
    assert len(events) == 1
    assert events[0]["type"] == "entity_created"
    assert events[0]["source"] == "openngs-api"


def test_event_list_respects_limit(env: None) -> None:
    for i in range(5):
        client.post("/subjects", json={"local_id": f"SUBJ-{i:03d}"})
    r = client.get("/events", params={"limit": 2})
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2


def test_event_show(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    event_id = client.get("/events").json()[0]["event_id"]
    r = client.get(f"/events/{event_id}")
    assert r.status_code == 200, r.text
    event = r.json()
    assert event["event_id"] == event_id
    assert event["payload"]["entity_type"] == "Subject"


def test_event_show_unknown_id_is_404(env: None) -> None:
    r = client.get("/events/018f5b2a-0000-7000-8000-999999999999")
    assert r.status_code == 404


def test_event_replay_requires_yes(env: None) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-001"})
    r = client.post("/events/replay")
    assert r.status_code == 400
    assert "yes=true" in r.text


def test_event_replay_reproduces_projection(env: None) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-001"})
    client.post("/specimens", json={"local_id": "SPEC-001", "subject": "SUBJ-001"})

    before = client.get("/specimens/SPEC-001").json()

    r = client.post("/events/replay", params={"yes": "true"})
    assert r.status_code == 200, r.text
    assert r.json()["replayed"] == 3  # Subject + Specimen entity_created + one edge_created

    after = client.get("/specimens/SPEC-001").json()
    assert after == before


def test_valid_time_is_stored_utc_aware(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001", "valid_time": "2026-01-15T09:00:00"})
    assert r.status_code == 200, r.text
    r = client.post(
        "/subjects", json={"local_id": "SUBJ-002", "valid_time": "2026-01-15T09:00:00+02:00"}
    )
    assert r.status_code == 200, r.text
    events = client.get("/events").json()
    by_name = {e["payload"]["name"].rsplit("/", 1)[1]: e["valid_time"] for e in events}
    assert by_name["SUBJ-001"] == "2026-01-15T09:00:00+00:00"  # naive -> taken as UTC
    assert by_name["SUBJ-002"] == "2026-01-15T07:00:00+00:00"  # offset -> converted
