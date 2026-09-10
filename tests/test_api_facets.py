"""End-to-end tests for the REST API's `facet`/`facet schema` routes (Phase 3 backlog item
3, docs/api-design.md). Mirrors the relevant scenarios in tests/test_cli_facets.py."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openngs.api import app

client = TestClient(app)
FIXTURE_SCHEMA_PATH = Path(__file__).parent / "fixtures" / "qc_metrics.schema.json"
FIXTURE_SCHEMA_JSON = json.loads(FIXTURE_SCHEMA_PATH.read_text())


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


def _setup_data_file(local_id: str = "R1.fastq.gz") -> str:
    _create("sequencing-runs", local_id="RUN-001")
    return _create("data-files", local_id=local_id, produced_by="RUN-001")


def test_attach_requires_exactly_one_schema_source(env: None) -> None:
    _setup_data_file()
    r = client.post(
        "/facets",
        json={
            "to": "R1.fastq.gz",
            "schema_url": str(FIXTURE_SCHEMA_PATH),
            "schema_id": "whatever",
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "x", "metric_value": 1.0},
        },
    )
    assert r.status_code == 422

    r = client.post(
        "/facets",
        json={
            "to": "R1.fastq.gz",
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "x", "metric_value": 1.0},
        },
    )
    assert r.status_code == 422


def test_attach_list_show_round_trip(env: None) -> None:
    data_file_id = _setup_data_file()
    r = client.post(
        "/facets",
        json={
            "to": "R1.fastq.gz",
            "schema_url": str(FIXTURE_SCHEMA_PATH),
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "percent_duplication", "metric_value": 12.3},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    facet_id = body["facet_id"]
    assert body["attached_to"] == data_file_id

    r = client.get("/facets", params={"to": "R1.fastq.gz"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["facet_id"] == facet_id
    assert rows[0]["facet_type"] == "QcMetricsFacet"

    r = client.get(f"/facets/{facet_id}")
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["data"] == {"metric_name": "percent_duplication", "metric_value": 12.3}
    assert shown["attached_to"] == data_file_id
    assert shown["_producer"] == "fastqc/0.12.1"
    assert "events" not in shown

    r = client.get(f"/facets/{facet_id}", params={"events": "true"})
    events = r.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "facet_instance_attached"


def test_attach_rejects_invalid_data(env: None) -> None:
    _setup_data_file()
    r = client.post(
        "/facets",
        json={
            "to": "R1.fastq.gz",
            "schema_url": str(FIXTURE_SCHEMA_PATH),
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_value": 12.3},  # missing required metric_name
        },
    )
    assert r.status_code == 400
    assert "required" in r.text


def test_facet_show_not_found(env: None) -> None:
    r = client.get("/facets/nope")
    assert r.status_code == 404


def test_attach_to_unknown_ref_is_400(env: None) -> None:
    r = client.post(
        "/facets",
        json={
            "to": "NOPE",
            "schema_url": str(FIXTURE_SCHEMA_PATH),
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "x", "metric_value": 1.0},
        },
    )
    assert r.status_code == 400


def test_schema_register_list_show_round_trip(env: None) -> None:
    r = client.post(
        "/facet-schemas", json={"local_id": "qc-metrics", "json_schema": FIXTURE_SCHEMA_JSON}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    schema_id = body["schema_id"]
    assert body["schema_name"] == "openngs://acme-genomics/core-lab/facet-schema/qc-metrics"

    r = client.get("/facet-schemas", params={"name": "qc-metrics"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["schema_id"] == schema_id

    r = client.get(f"/facet-schemas/{schema_id}")
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["json_schema"] == FIXTURE_SCHEMA_JSON
    assert "events" not in shown

    r = client.get("/facet-schemas/qc-metrics", params={"events": "true"})
    assert r.status_code == 200, r.text
    shown = r.json()
    assert shown["schema_id"] == schema_id  # bare local_id resolves to the newest version
    assert shown["events"][0]["type"] == "facet_schema_registered"

    # full name form - a {ref} path parameter's default Starlette converter refuses to
    # match literal "/"s, which the full openngs://... name always has; see the matching
    # test in test_api_entities.py for how this was found.
    r = client.get(f"/facet-schemas/{body['schema_name']}")
    assert r.status_code == 200, r.text
    assert r.json()["schema_id"] == schema_id


def test_schema_reregister_creates_new_version(env: None) -> None:
    r1 = client.post(
        "/facet-schemas", json={"local_id": "qc-metrics", "json_schema": FIXTURE_SCHEMA_JSON}
    )
    r2 = client.post(
        "/facet-schemas", json={"local_id": "qc-metrics", "json_schema": FIXTURE_SCHEMA_JSON}
    )
    assert r1.json()["schema_id"] != r2.json()["schema_id"]

    rows = client.get("/facet-schemas", params={"name": "qc-metrics"}).json()
    assert len(rows) == 2

    # bare local_id show resolves to the newest (r2's) version
    shown = client.get("/facet-schemas/qc-metrics").json()
    assert shown["schema_id"] == r2.json()["schema_id"]


def test_schema_show_not_found(env: None) -> None:
    r = client.get("/facet-schemas/nope")
    assert r.status_code == 404


def test_attach_with_schema_id(env: None) -> None:
    _setup_data_file()
    schema_id = client.post(
        "/facet-schemas", json={"local_id": "qc-metrics", "json_schema": FIXTURE_SCHEMA_JSON}
    ).json()["schema_id"]

    r = client.post(
        "/facets",
        json={
            "to": "R1.fastq.gz",
            "schema_id": schema_id,
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "percent_duplication", "metric_value": 9.9},
        },
    )
    assert r.status_code == 200, r.text
    facet_id = r.json()["facet_id"]

    shown = client.get(f"/facets/{facet_id}").json()
    assert shown["_schemaURL"] == f"openngs-schema://{schema_id}"
