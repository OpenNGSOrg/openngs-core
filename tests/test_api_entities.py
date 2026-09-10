"""End-to-end tests for the REST API's entity CRUD routes (docs/api-design.md).
Mirrors tests/test_cli_entities.py's scenarios against the same store layer,
exercised over HTTP instead of the CLI."""

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


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_missing_org_ns_returns_500(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.delenv("OPENNGS_ORG", raising=False)
    monkeypatch.delenv("OPENNGS_NAMESPACE", raising=False)
    monkeypatch.setenv("OPENNGS_DB_URL", f"sqlite:///{db_path}")
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r.status_code == 500


def test_create_specimen_requires_parent_field(env: None) -> None:
    r = client.post("/specimens", json={"local_id": "SPEC-001"})
    assert r.status_code == 422


def test_full_lineage_via_api(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r.status_code == 200, r.text
    subject_id = r.json()["internal_id"]

    r = client.post("/specimens", json={"local_id": "SPEC-001", "subject": "SUBJ-001"})
    assert r.status_code == 200, r.text
    specimen_id = r.json()["internal_id"]
    assert specimen_id != subject_id

    r = client.get("/specimens", params={"subject": "SUBJ-001"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["internal_id"] == specimen_id

    r = client.get(f"/specimens/{specimen_id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["type"] == "Specimen"
    assert body["outgoing"] == [
        {
            "predicate": "derived_from",
            "other_type": "Subject",
            "other_id": subject_id,
            "other_name": "openngs://acme-genomics/core-lab/subject/SUBJ-001",
        }
    ]
    assert body["incoming"] == []

    # bare local_id resolves the same way a CLI REF would
    r = client.get("/specimens/SPEC-001")
    assert r.status_code == 200, r.text
    assert r.json()["internal_id"] == specimen_id


def test_show_events_flag(env: None) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-001"})
    client.post("/specimens", json={"local_id": "SPEC-001", "subject": "SUBJ-001"})

    without = client.get("/specimens/SPEC-001")
    assert "events" not in without.json()

    r = client.get("/specimens/SPEC-001", params={"events": "true"})
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    assert {e["type"] for e in events} == {"entity_created", "edge_created"}


def test_show_unknown_ref_returns_404(env: None) -> None:
    r = client.get("/specimens/NOPE")
    assert r.status_code == 404


def test_show_by_full_name_ref(env: None) -> None:
    """The full openngs://{org}/{ns}/{type}/{local_id} name is one of the three documented
    REF forms (docs/api-design.md), but it contains literal "/"s - a bare {ref} path
    parameter's default Starlette converter refuses to match those and 404s before
    resolve_ref ever runs. Found live (Claude Desktop's execute_graphql MCP tool worked
    fine with this form; show_subject, built on this same route, didn't)."""
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r.status_code == 200, r.text
    internal_id = r.json()["internal_id"]

    r = client.get("/subjects/openngs://acme-genomics/core-lab/subject/SUBJ-001")
    assert r.status_code == 200, r.text
    assert r.json()["internal_id"] == internal_id


def test_create_with_bad_parent_ref_returns_400(env: None) -> None:
    r = client.post("/specimens", json={"local_id": "SPEC-001", "subject": "NOPE"})
    assert r.status_code == 400


def test_duplicate_name_without_force_returns_409(env: None) -> None:
    r1 = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r1.status_code == 200, r1.text
    r2 = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r2.status_code == 409


def test_a_name_cannot_be_taken_twice(env: None) -> None:
    """The database enforces it now; there is no override."""
    assert client.post("/subjects", json={"local_id": "SUBJ-001"}).status_code == 200
    r = client.post("/subjects", json={"local_id": "SUBJ-001"})
    assert r.status_code == 409
    assert (
        client.post(
            "/subjects", json={"local_id": "SUBJ-001"}, params={"force": "true"}
        ).status_code
        == 409
    )


def test_data_file_derived_from_and_produced_by(env: None) -> None:
    client.post("/sequencing-runs", json={"local_id": "RUN-001"})
    r1 = client.post(
        "/data-files",
        json={"local_id": "R1.fastq.gz", "produced_by": "RUN-001", "derived_from": []},
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/data-files",
        json={
            "local_id": "MERGED.bam",
            "produced_by": "RUN-001",
            "derived_from": ["R1.fastq.gz"],
        },
    )
    assert r2.status_code == 200, r2.text

    shown = client.get("/data-files/MERGED.bam").json()
    predicates = {(e["predicate"], e["other_type"]) for e in shown["outgoing"]}
    assert predicates == {("produced_by", "SequencingRun"), ("derived_from", "DataFile")}


def test_xrefs_round_trip(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001", "xrefs": ["biosample:SAMN1"]})
    assert r.status_code == 200, r.text
    shown = client.get("/subjects/SUBJ-001").json()
    assert shown["xrefs"] == ["biosample:SAMN1"]


def test_valid_time_is_accepted_and_diverges_from_transaction_time(env: None) -> None:
    r = client.post("/subjects", json={"local_id": "SUBJ-001", "valid_time": "2026-01-15T09:00:00"})
    assert r.status_code == 200, r.text
    internal_id = r.json()["internal_id"]
    shown = client.get(f"/subjects/{internal_id}", params={"events": "true"})
    events = shown.json()["events"]
    assert events[0]["valid_time"].startswith("2026-01-15T09:00:00")
    assert not events[0]["transaction_time"].startswith("2026-01-15T09:00:00")


def test_no_parent_entity_list_has_no_parent_filter(env: None) -> None:
    client.post("/pools", json={"local_id": "POOL-001"})
    r = client.get("/pools")
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1


# --- DataFileSet.produced_by widened to SequencingRun ----------------


def test_datafileset_produced_by_sequencing_run(env: None) -> None:
    """A raw BCL run folder - many per-cycle files produced together by one SequencingRun,
    pre-demultiplexing - is exactly the "produced together as a group" shape DataFileSet
    exists for. DataFileSet's --produced-by originally accepted only AnalysisRun
    (the first design had analysis-output grouping in mind); DataFile's own ParentSpec already
    allowed both."""
    run_id = client.post("/sequencing-runs", json={"local_id": "RUN-001"}).json()["internal_id"]
    r = client.post("/data-file-sets", json={"local_id": "RUN-001-BCL", "produced_by": "RUN-001"})
    assert r.status_code == 200, r.text
    set_id = r.json()["internal_id"]

    shown = client.get(f"/data-file-sets/{set_id}").json()
    assert shown["outgoing"] == [
        {
            "predicate": "produced_by",
            "other_type": "SequencingRun",
            "other_id": run_id,
            "other_name": "openngs://acme-genomics/core-lab/sequencing-run/RUN-001",
        }
    ]

    # AnalysisRun (the original, still-valid case) keeps working unchanged.
    analysis_id = client.post("/analysis-runs", json={"local_id": "PIPE-001"}).json()["internal_id"]
    r = client.post("/data-file-sets", json={"local_id": "PIPE-001-OUT", "produced_by": "PIPE-001"})
    assert r.status_code == 200, r.text
    assert (
        client.get(f"/data-file-sets/{r.json()['internal_id']}").json()["outgoing"][0]["other_id"]
        == analysis_id
    )


def test_nested_datafileset_part_of_datafileset(env: None) -> None:
    """A multi-sample demux run's output is one run-level DataFileSet; a per-sample subset
    of it (this sample's R1/R2) is itself a DataFileSet, part_of the run-level one - the
    same "produced together as a named group" shape, nested one level.
    part_of's type check was always unrestricted (LINK_TARGET_TYPES["part_of"] ==
    ENTITY_TYPES), so this already worked mechanically; this test is the explicit coverage
    for what is intended usage rather than an accident of permissiveness."""
    client.post("/sequencing-runs", json={"local_id": "RUN-001"})
    client.post("/data-file-sets", json={"local_id": "RUN-001-BCL", "produced_by": "RUN-001"})
    client.post("/analysis-runs", json={"local_id": "BCLCONVERT-1"})
    r = client.post("/links/used", json={"from": "BCLCONVERT-1", "to": "RUN-001-BCL"})
    assert r.status_code == 200, r.text  # DataFileSet is now a valid `used` target too

    run_set_id = client.post(
        "/data-file-sets", json={"local_id": "RUN-001-FASTQ", "produced_by": "BCLCONVERT-1"}
    ).json()["internal_id"]
    sample_set_id = client.post(
        "/data-file-sets",
        json={"local_id": "SAMPLE-042-FASTQ", "produced_by": "BCLCONVERT-1"},
    ).json()["internal_id"]
    r = client.post("/links/part-of", json={"from": "SAMPLE-042-FASTQ", "to": "RUN-001-FASTQ"})
    assert r.status_code == 200, r.text

    r1_id = client.post(
        "/data-files", json={"local_id": "S042_R1.fastq.gz", "produced_by": "BCLCONVERT-1"}
    ).json()["internal_id"]
    client.post("/links/part-of", json={"from": "S042_R1.fastq.gz", "to": "SAMPLE-042-FASTQ"})

    client.post("/analysis-runs", json={"local_id": "WGS-PIPE-042"})
    r = client.post("/links/used", json={"from": "WGS-PIPE-042", "to": "SAMPLE-042-FASTQ"})
    assert r.status_code == 200, r.text

    shown = client.get(f"/data-file-sets/{sample_set_id}").json()
    outgoing_predicates = {e["predicate"] for e in shown["outgoing"]}
    assert outgoing_predicates == {"produced_by", "part_of"}
    produced_by_edge = next(e for e in shown["outgoing"] if e["predicate"] == "produced_by")
    assert produced_by_edge["other_type"] == "AnalysisRun"
    part_of_edge = next(e for e in shown["outgoing"] if e["predicate"] == "part_of")
    assert part_of_edge["other_id"] == run_set_id
    assert part_of_edge["other_type"] == "DataFileSet"

    incoming_predicates = {(e["predicate"], e["other_type"]) for e in shown["incoming"]}
    assert incoming_predicates == {("part_of", "DataFile"), ("used", "AnalysisRun")}
    incoming_by_id = {e["other_id"]: e for e in shown["incoming"]}
    assert incoming_by_id[r1_id]["predicate"] == "part_of"


def test_duplicate_xref_is_stored_once(env: None) -> None:
    r = client.post(
        "/subjects", json={"local_id": "SUBJ-001", "xrefs": ["biosample:SAMN1", "biosample:SAMN1"]}
    )
    assert r.status_code == 200, r.text
    assert client.get("/subjects/SUBJ-001").json()["xrefs"] == ["biosample:SAMN1"]


def test_empty_local_id_is_422(env: None) -> None:
    assert client.post("/subjects", json={"local_id": ""}).status_code == 422
    assert (
        client.post("/facet-schemas", json={"local_id": "", "json_schema": {}}).status_code == 422
    )
    r = client.post(
        "/datapoints",
        json={"local_id": "", "for": "X", "type": "t", "kind": "text", "value": "v"},
    )
    assert r.status_code == 422
