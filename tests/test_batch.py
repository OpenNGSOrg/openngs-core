"""Atomic batch writes (#13)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openngs.api import app

client = TestClient(app)
FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")


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


def _batch(operations: list[dict[str, Any]], **params: Any) -> Any:
    return client.post("/batch", json={"operations": operations}, params=params)


def test_registering_a_run_is_one_transaction(env: None) -> None:
    """The persona's case: a sequencing run is the run, its raw output set, a derived_from
    to the pool and a used to the instrument. Four writes, one fact."""
    r = _batch(
        [
            {"op": "create", "entity_type": "pool", "local_id": "POOL-1"},
            {"op": "create", "entity_type": "actor", "local_id": "NOVASEQ-01"},
            {"op": "create", "entity_type": "sequencing-run", "local_id": "RUN-1"},
            {"op": "link", "predicate": "used", "from": "RUN-1", "to": "NOVASEQ-01"},
            {
                "op": "create",
                "entity_type": "data-file-set",
                "local_id": "BCL-1",
                "parent": "RUN-1",
                "xrefs": ["s3://bucket/run1/"],
            },
            {"op": "link", "predicate": "derived_from", "from": "BCL-1", "to": "POOL-1"},
        ]
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] == 6
    assert [x["op"] for x in body["results"]][:3] == ["create", "create", "create"]

    # a later operation resolved an entity created earlier in the same batch
    shown = client.get("/data-file-sets/BCL-1").json()
    assert {e["predicate"] for e in shown["outgoing"]} == {"produced_by", "derived_from"}
    assert shown["xrefs"] == ["s3://bucket/run1/"]


def test_a_failure_rolls_the_whole_batch_back(env: None) -> None:
    r = _batch(
        [
            {"op": "create", "entity_type": "subject", "local_id": "GOOD-1"},
            {"op": "link", "predicate": "used", "from": "GOOD-1", "to": "NOPE"},
        ]
    )
    assert r.status_code == 400
    assert "operation 1 (link)" in r.json()["detail"]
    # the create that "succeeded" is gone too, and so is its event
    assert client.get("/subjects/GOOD-1").status_code == 404
    assert client.get("/subjects").json() == []
    assert client.get("/events").json() == []


def test_dry_run_validates_and_writes_nothing(env: None) -> None:
    ops = [
        {"op": "create", "entity_type": "subject", "local_id": "SUBJ-1"},
        {"op": "create", "entity_type": "specimen", "local_id": "SPEC-1", "parent": "SUBJ-1"},
    ]
    r = _batch(ops, dry_run="true")
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 0
    assert r.json()["dry_run"] is True
    assert len(r.json()["results"]) == 2  # it did resolve everything
    assert client.get("/subjects").json() == []
    assert client.get("/events").json() == []

    # ...and a dry run that would fail reports the failure
    r = _batch([{"op": "link", "predicate": "used", "from": "X", "to": "Y"}], dry_run="true")
    assert r.status_code == 400


def test_every_operation_kind(env: None) -> None:
    r = _batch(
        [
            {"op": "register_schema", "local_id": "qc", "json_schema": {"$defs": {}}},
            {"op": "create", "entity_type": "subject", "local_id": "SUBJ-1"},
            {"op": "create", "entity_type": "actor", "local_id": "ACTOR-1"},
            {"op": "create", "entity_type": "subject", "local_id": "SUBJ-2"},
            {
                "op": "link",
                "predicate": "same_as",
                "from": "SUBJ-1",
                "to": "SUBJ-2",
                "asserted_by": "ACTOR-1",
                "method": "barcode_scan",
                "confidence": 1.0,
            },
            {
                "op": "attach_facet",
                "to": "SUBJ-1",
                "schema_url": FIXTURE_SCHEMA,
                "facet_type": "QcMetricsFacet",
                "producer": "p",
                "data": {"metric_name": "m", "metric_value": 1.0},
            },
            {
                "op": "create_datapoint",
                "local_id": "DP-1",
                "for": "SUBJ-1",
                "datapoint_type": "openngs-dp:percent_duplication",
                "kind": "number",
                "value": "12.3",
            },
        ]
    )
    assert r.status_code == 200, r.text
    kinds = [x["op"] for x in r.json()["results"]]
    assert kinds == [
        "register_schema",
        "create",
        "create",
        "create",
        "link",
        "attach_facet",
        "create_datapoint",
    ]
    assert client.get("/datapoints").json()[0]["value_number"] == 12.3
    assert len(client.get("/facets").json()) == 1


def test_entity_type_accepts_either_spelling(env: None) -> None:
    r = _batch(
        [
            {"op": "create", "entity_type": "sequencing-run", "local_id": "RUN-1"},
            {"op": "create", "entity_type": "SequencingRun", "local_id": "RUN-2"},
        ]
    )
    assert r.status_code == 200, r.text
    assert len(client.get("/sequencing-runs").json()) == 2


def test_request_shape_errors(env: None) -> None:
    assert _batch([{"op": "nope"}]).status_code == 422
    assert client.post("/batch", json={"operations": []}).status_code == 422
    # a specimen needs a parent or an explicit opt-out
    r = _batch([{"op": "create", "entity_type": "specimen", "local_id": "SPEC-1"}])
    assert r.status_code == 422
    assert "no_parent" in r.json()["detail"]
    # ...which it can give
    assert (
        _batch(
            [{"op": "create", "entity_type": "specimen", "local_id": "SPEC-1", "no_parent": True}]
        ).status_code
        == 200
    )
    r = _batch([{"op": "create", "entity_type": "unicorn", "local_id": "U-1"}])
    assert r.status_code == 422
    assert "unknown entity type" in r.json()["detail"]
    r = _batch([{"op": "attach_facet", "to": "X", "facet_type": "T", "producer": "p"}])
    assert r.status_code == 422


def test_batch_writes_are_ordinary_events(env: None) -> None:
    _batch(
        [
            {"op": "create", "entity_type": "subject", "local_id": "SUBJ-1"},
            {"op": "create", "entity_type": "specimen", "local_id": "SPEC-1", "parent": "SUBJ-1"},
        ]
    )
    events = client.get("/events").json()
    assert [e["type"] for e in events] == ["entity_created", "entity_created", "edge_created"]
    assert {e["source"] for e in events} == {"openngs-api"}
    # and the projection rebuilds from them
    before = client.get("/specimens/SPEC-1").json()
    assert client.post("/events/replay", params={"yes": "true"}).status_code == 200
    assert client.get("/specimens/SPEC-1").json() == before
