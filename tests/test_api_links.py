"""End-to-end tests for the REST API's `link` routes (docs/api-design.md).
Mirrors the relevant scenarios in tests/test_cli_entities.py and
tests/test_store_repo.py, exercised over HTTP instead of the CLI."""

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


def test_link_used_type_validation(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    _create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    extract_id = _create("extracts", local_id="EXT-001", specimen="SPEC-001")

    # Subject is not a valid `used` target (Protocol/Reagent/Actor/DataFile/DataFileSet -
    # widened from just the first three).
    r = client.post("/links/used", json={"from": "EXT-001", "to": "SUBJ-001"})
    assert r.status_code == 400

    reagent_id = _create("reagents", local_id="REAGENT-001")
    r = client.post("/links/used", json={"from": "EXT-001", "to": "REAGENT-001"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["predicate"] == "used"
    assert body["from"] == extract_id
    assert body["to"] == reagent_id
    assert "edge_id" in body

    shown = client.get("/extracts/EXT-001").json()
    used_edges = [e for e in shown["outgoing"] if e["predicate"] == "used"]
    assert used_edges == [
        {
            "predicate": "used",
            "other_type": "Reagent",
            "other_id": reagent_id,
            "other_name": "openngs://acme-genomics/core-lab/reagent/REAGENT-001",
        }
    ]


def test_link_used_accepts_datafile_and_datafileset(env: None) -> None:
    """An AnalysisRun can `used` a DataFile/DataFileSet directly - e.g.
    "this secondary pipeline run consumed exactly this FASTQ output" - rather than only
    being reconstructable by walking derived_from backward from its own outputs."""
    _create("sequencing-runs", local_id="RUN-001")
    _create("data-file-sets", local_id="RUN-001-FASTQ", produced_by="RUN-001")
    data_file_id = _create("data-files", local_id="R1.fastq.gz", produced_by="RUN-001")
    analysis_id = _create("analysis-runs", local_id="PIPE-001")

    r = client.post("/links/used", json={"from": "PIPE-001", "to": "RUN-001-FASTQ"})
    assert r.status_code == 200, r.text
    r = client.post("/links/used", json={"from": "PIPE-001", "to": "R1.fastq.gz"})
    assert r.status_code == 200, r.text

    shown = client.get(f"/analysis-runs/{analysis_id}").json()
    used_targets = {e["other_id"] for e in shown["outgoing"] if e["predicate"] == "used"}
    fastq_set_id = client.get("/data-file-sets/RUN-001-FASTQ").json()["internal_id"]
    assert used_targets == {fastq_set_id, data_file_id}


def test_link_used_accepts_pool_and_library(env: None) -> None:
    """A SequencingRun states the material it loaded, the same way an AnalysisRun
    states the data it consumed. Library as well as Pool, because a single-sample run has no
    pooling step and should not have to invent a pool of one."""
    _create("subjects", local_id="SUBJ-001")
    _create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _create("extracts", local_id="EXT-001", specimen="SPEC-001")
    library_id = _create("libraries", local_id="LIB-001", extract="EXT-001")
    pool_id = _create("pools", local_id="POOL-001")
    run_id = _create("sequencing-runs", local_id="RUN-001")
    solo_run_id = _create("sequencing-runs", local_id="RUN-002")

    assert client.post("/links/used", json={"from": "RUN-001", "to": "POOL-001"}).status_code == 200
    assert client.post("/links/used", json={"from": "RUN-002", "to": "LIB-001"}).status_code == 200

    shown = client.get(f"/sequencing-runs/{run_id}").json()
    assert [e["other_id"] for e in shown["outgoing"] if e["predicate"] == "used"] == [pool_id]
    solo = client.get(f"/sequencing-runs/{solo_run_id}").json()
    assert [e["other_id"] for e in solo["outgoing"] if e["predicate"] == "used"] == [library_id]

    # Nothing loads a Specimen or an Extract onto a sequencer, so neither was widened.
    for ref in ("SPEC-001", "EXT-001"):
        r = client.post("/links/used", json={"from": "RUN-001", "to": ref})
        assert r.status_code == 400, ref


@pytest.mark.parametrize(
    "slug", ["derived-from", "part-of", "used", "produced-by", "characterizes"]
)
def test_link_missing_field_is_422(env: None, slug: str) -> None:
    r = client.post(f"/links/{slug}", json={"from": "X"})
    assert r.status_code == 422


def test_link_unknown_ref_is_400(env: None) -> None:
    _create("pools", local_id="POOL-001")
    r = client.post("/links/part-of", json={"from": "NOPE", "to": "POOL-001"})
    assert r.status_code == 400


def test_link_produced_by(env: None) -> None:
    # Pool has no produced_by parent at create time - /links/produced-by is the generic
    # escape hatch (docs/cli-design.md) for attaching one after the fact.
    run_id = _create("sequencing-runs", local_id="RUN-001")
    pool_id = _create("pools", local_id="POOL-001")
    r = client.post("/links/produced-by", json={"from": "POOL-001", "to": "RUN-001"})
    assert r.status_code == 200, r.text

    shown = client.get(f"/pools/{pool_id}").json()
    assert shown["outgoing"] == [
        {
            "predicate": "produced_by",
            "other_type": "SequencingRun",
            "other_id": run_id,
            "other_name": "openngs://acme-genomics/core-lab/sequencing-run/RUN-001",
        }
    ]

    # AnalysisRun is also a valid produced_by target.
    analysis_id = _create("analysis-runs", local_id="ANALYSIS-001")
    r = client.post("/links/produced-by", json={"from": "POOL-001", "to": "ANALYSIS-001"})
    assert r.status_code == 200, r.text
    outgoing = client.get(f"/pools/{pool_id}").json()["outgoing"]
    assert {e["other_id"] for e in outgoing} == {run_id, analysis_id}


def test_link_characterizes_source_must_be_datapoint(env: None) -> None:
    # characterizes has no target-type constraint (LINK_TARGET_TYPES == ENTITY_TYPES) but
    # its source must be a DataPoint - the schema defines it as DataPoint -> Entity.
    _create("subjects", local_id="SUBJ-001")
    run_id = _create("sequencing-runs", local_id="RUN-001")
    r = client.post("/links/characterizes", json={"from": "SUBJ-001", "to": "RUN-001"})
    assert r.status_code == 400
    assert "DataPoint" in r.json()["detail"]

    r = client.post(
        "/datapoints",
        json={"local_id": "DP-1", "for": "SUBJ-001", "type": "x:y", "kind": "text", "value": "v"},
    )
    dp_id = r.json()["internal_id"]
    r = client.post("/links/characterizes", json={"from": "DP-1", "to": "RUN-001"})
    assert r.status_code == 200, r.text
    assert r.json() == {
        "edge_id": r.json()["edge_id"],
        "predicate": "characterizes",
        "from": dp_id,
        "to": run_id,
        "created": True,
    }


def test_link_valid_time(env: None) -> None:
    subject_id = _create("subjects", local_id="SUBJ-001")
    _create("contexts", local_id="COHORT-001")
    r = client.post(
        "/links/part-of",
        json={"from": "SUBJ-001", "to": "COHORT-001", "valid_time": "2026-01-15T09:00:00"},
    )
    assert r.status_code == 200, r.text

    shown = client.get(f"/subjects/{subject_id}", params={"events": "true"})
    edge_events = [e for e in shown.json()["events"] if e["type"] == "edge_created"]
    assert any(e["valid_time"].startswith("2026-01-15T09:00:00") for e in edge_events)


def test_link_same_as_full_round_trip(env: None) -> None:
    a_id = _create("subjects", local_id="SUBJ-A")
    b_id = _create("subjects", local_id="SUBJ-B")
    actor_id = _create("actors", local_id="ACTOR-1")

    r = client.post(
        "/links/same-as",
        json={
            "from": "SUBJ-A",
            "to": "SUBJ-B",
            "asserted_by": "ACTOR-1",
            "method": "barcode_scan",
            "confidence": 0.95,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["from"] == a_id
    assert body["to"] == b_id
    assert body["asserted_by"] == actor_id
    assert body["method"] == "barcode_scan"
    assert body["confidence"] == 0.95

    shown = client.get(f"/subjects/{a_id}").json()
    assert shown["outgoing"] == [
        {
            "predicate": "same_as",
            "other_type": "Subject",
            "other_id": b_id,
            "other_name": "openngs://acme-genomics/core-lab/subject/SUBJ-B",
            "asserted_by": actor_id,
            "method": "barcode_scan",
            "confidence": 0.95,
        }
    ]


@pytest.mark.parametrize("field", ["asserted_by", "method", "confidence"])
def test_link_same_as_missing_required_field_is_422(env: None, field: str) -> None:
    body = {
        "from": "SUBJ-A",
        "to": "SUBJ-B",
        "asserted_by": "ACTOR-1",
        "method": "barcode_scan",
        "confidence": 0.95,
    }
    del body[field]
    r = client.post("/links/same-as", json=body)
    assert r.status_code == 422


def test_link_same_as_confidence_out_of_range_is_422(env: None) -> None:
    r = client.post(
        "/links/same-as",
        json={
            "from": "SUBJ-A",
            "to": "SUBJ-B",
            "asserted_by": "ACTOR-1",
            "method": "barcode_scan",
            "confidence": 1.5,
        },
    )
    assert r.status_code == 422


def test_link_duplicate_and_self_loop_are_400(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    _create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    # the create already made SPEC-001 derived_from SUBJ-001
    r = client.post("/links/derived-from", json={"from": "SPEC-001", "to": "SUBJ-001"})
    assert r.status_code == 400
    assert "already exists" in r.json()["detail"]
    r = client.post("/links/part-of", json={"from": "SUBJ-001", "to": "SUBJ-001"})
    assert r.status_code == 400
    assert "itself" in r.json()["detail"]
    _create("actors", local_id="ACTOR-001")
    r = client.post(
        "/links/same-as",
        json={
            "from": "SUBJ-001",
            "to": "SUBJ-001",
            "asserted_by": "ACTOR-001",
            "method": "m",
            "confidence": 0.5,
        },
    )
    assert r.status_code == 400
