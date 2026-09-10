"""End-to-end REST and GraphQL tests for corrections and retractions."""

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


def _create(plural: str, **fields: object) -> str:
    r = client.post(f"/{plural}", json=fields)
    assert r.status_code == 200, r.text
    return str(r.json()["internal_id"])


def _gql(query: str) -> dict[str, Any]:
    r = client.post("/graphql", json={"query": query})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert "errors" not in body, body
    return body["data"]


# --- REST -----------------------------------------------------------------------------------


def test_correct_entity(env: None) -> None:
    _create("subjects", local_id="SUBJ-001", xrefs=["barcode:A"])
    r = client.post("/subjects/SUBJ-001/correct", json={"local_id": "SUBJ-999", "reason": "typo"})
    assert r.status_code == 200, r.text
    assert r.json()["name"].endswith("/SUBJ-999")

    assert client.get("/subjects/SUBJ-001").status_code == 404
    body = client.get("/subjects/SUBJ-999").json()
    assert body["xrefs"] == ["barcode:A"]  # omitted fields are kept
    assert "retracted_by_event" not in body

    # xrefs given replace the set; [] clears it
    client.post("/subjects/SUBJ-999/correct", json={"xrefs": ["barcode:B"], "reason": "rescan"})
    assert client.get("/subjects/SUBJ-999").json()["xrefs"] == ["barcode:B"]
    client.post("/subjects/SUBJ-999/correct", json={"xrefs": [], "reason": "not ours"})
    assert client.get("/subjects/SUBJ-999").json()["xrefs"] == []


def test_correct_requires_reason_and_a_change(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    assert client.post("/subjects/SUBJ-001/correct", json={"local_id": "X"}).status_code == 422
    assert client.post("/subjects/SUBJ-001/correct", json={"reason": ""}).status_code == 422
    r = client.post("/subjects/SUBJ-001/correct", json={"reason": "no-op"})
    assert r.status_code == 400
    assert "nothing to correct" in r.json()["detail"]
    assert client.post("/subjects/NOPE/correct", json={"reason": "x"}).status_code == 404


def test_retract_entity_refuses_live_edges_then_cascades(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    _create("specimens", local_id="SPEC-001", subject="SUBJ-001")

    r = client.post("/subjects/SUBJ-001/retract", json={"reason": "duplicate"})
    assert r.status_code == 400
    assert "live edge" in r.json()["detail"]

    r = client.post("/subjects/SUBJ-001/retract", json={"reason": "duplicate", "cascade": True})
    assert r.status_code == 200, r.text
    assert len(r.json()["retracted_edges"]) == 1

    assert client.get("/subjects/SUBJ-001").status_code == 404
    assert client.get("/subjects").json() == []
    shown = client.get("/subjects/SUBJ-001", params={"include_retracted": "true"})
    assert shown.status_code == 200
    assert shown.json()["retracted_by_event"]
    assert len(client.get("/subjects", params={"include_retracted": "true"}).json()) == 1
    # the specimen survives, minus the edge
    assert client.get("/specimens/SPEC-001").json()["outgoing"] == []


def test_retract_link_and_reassert(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    _create("contexts", local_id="COHORT-001")
    r = client.post("/links/part-of", json={"from": "SUBJ-001", "to": "COHORT-001"})
    edge_id = r.json()["edge_id"]

    r = client.post(f"/links/{edge_id}/retract", json={"reason": "wrong cohort"})
    assert r.status_code == 200, r.text
    assert client.get("/subjects/SUBJ-001").json()["outgoing"] == []

    # the same relationship may be asserted again once withdrawn
    assert (
        client.post("/links/part-of", json={"from": "SUBJ-001", "to": "COHORT-001"}).status_code
        == 200
    )
    assert client.post(f"/links/{edge_id}/retract", json={"reason": "again"}).status_code == 404


def test_correct_and_retract_datapoint(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    client.post(
        "/datapoints",
        json={
            "local_id": "DP-1",
            "for": "SUBJ-001",
            "type": "openngs-dp:percent_duplication",
            "kind": "number",
            "value": "12.3",
        },
    )
    r = client.post("/datapoints/DP-1/correct", json={"value": "14.7", "reason": "re-measured"})
    assert r.status_code == 200, r.text
    assert client.get("/datapoints/DP-1").json()["value_number"] == 14.7

    r = client.post("/datapoints/DP-1/correct", json={"kind": "text", "reason": "x"})
    assert r.status_code == 400
    assert "send value with it" in r.json()["detail"]

    assert client.post("/datapoints/DP-1/retract", json={"reason": "wrong"}).status_code == 400
    r = client.post("/datapoints/DP-1/retract", json={"reason": "wrong", "cascade": True})
    assert r.status_code == 200, r.text
    assert client.get("/datapoints").json() == []


def test_correct_and_retract_facet(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    r = client.post(
        "/facets",
        json={
            "to": "SUBJ-001",
            "schema_url": FIXTURE_SCHEMA,
            "type": "QcMetricsFacet",
            "producer": "fastqc/0.12.1",
            "data": {"metric_name": "m", "metric_value": 12.3},
        },
    )
    facet_id = r.json()["facet_id"]

    r = client.post(
        f"/facets/{facet_id}/correct",
        json={"data": {"metric_name": "m", "metric_value": 14.7}, "reason": "re-ran"},
    )
    assert r.status_code == 200, r.text
    assert client.get(f"/facets/{facet_id}").json()["data"]["metric_value"] == 14.7

    # corrected data still validates against the schema the instance was pinned to
    r = client.post(
        f"/facets/{facet_id}/correct", json={"data": {"tool": "fastqc"}, "reason": "bad"}
    )
    assert r.status_code == 400
    assert "does not validate" in r.json()["detail"]

    assert (
        client.post(f"/facets/{facet_id}/retract", json={"reason": "wrong entity"}).status_code
        == 200
    )
    assert client.get(f"/facets/{facet_id}").status_code == 404
    assert client.get("/facets", params={"to": "SUBJ-001"}).json() == []


def test_replay_reproduces_corrections_over_http(env: None) -> None:
    _create("subjects", local_id="KEEP-001")
    _create("subjects", local_id="GONE-001")
    client.post("/subjects/KEEP-001/correct", json={"local_id": "KEPT-001", "reason": "typo"})
    client.post("/subjects/GONE-001/retract", json={"reason": "duplicate"})

    before = client.get("/subjects", params={"include_retracted": "true"}).json()
    assert client.post("/events/replay", params={"yes": "true"}).status_code == 200
    assert client.get("/subjects", params={"include_retracted": "true"}).json() == before
    assert len(client.get("/subjects").json()) == 1


# --- GraphQL --------------------------------------------------------------------------------


def test_graphql_hides_retracted_by_default(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    _create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    client.post("/subjects/SUBJ-001/retract", json={"reason": "duplicate", "cascade": True})

    data = _gql('{ subject(ref: "SUBJ-001") { name } subjects { name } }')
    assert data["subject"] is None
    assert data["subjects"] == []
    # the specimen's edge to it went with the cascade
    assert (
        _gql('{ specimen(ref: "SPEC-001") { outgoing { predicate } } }')["specimen"]["outgoing"]
        == []
    )


def test_graphql_include_retracted_exposes_the_marker(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    client.post("/subjects/SUBJ-001/retract", json={"reason": "never existed"})

    data = _gql(
        '{ subject(ref: "SUBJ-001", includeRetracted: true) '
        "{ name validTime retractedAt retractedByEvent } }"
    )
    node = data["subject"]
    assert node["name"].endswith("/SUBJ-001")
    assert node["validTime"]
    assert node["retractedAt"]
    assert node["retractedByEvent"]

    live = _gql("{ subjects(includeRetracted: true) { name retractedAt } }")["subjects"]
    assert len(live) == 1


def test_graphql_shows_corrected_content(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    client.post("/subjects/SUBJ-001/correct", json={"local_id": "SUBJ-999", "reason": "typo"})
    data = _gql('{ node(ref: "SUBJ-999") { name retractedAt } }')
    assert data["node"]["name"].endswith("/SUBJ-999")
    assert data["node"]["retractedAt"] is None


# --- valid_time range filtering (#9) ---------------------------------------------------------


def _seasonal(env_unused: None = None) -> None:
    _create("subjects", local_id="SITE-LAKE-01")
    for local_id, when in (
        ("LK-JUN", "2025-06-15T09:00:00"),
        ("LK-AUG", "2025-08-20T09:00:00"),
        ("LK-DEC", "2025-12-01T09:00:00"),
    ):
        r = client.post(
            "/specimens",
            json={"local_id": local_id, "subject": "SITE-LAKE-01", "valid_time": when},
        )
        assert r.status_code == 200, r.text


def _names(**params: str) -> set[str]:
    r = client.get("/specimens", params=params)
    assert r.status_code == 200, r.text
    return {row["name"].rsplit("/", 1)[1] for row in r.json()}


def test_rest_list_filters_by_valid_time_range(env: None) -> None:
    _seasonal()
    assert _names() == {"LK-JUN", "LK-AUG", "LK-DEC"}
    assert _names(valid_from="2025-06-01") == {"LK-JUN", "LK-AUG", "LK-DEC"}
    assert _names(valid_to="2025-09-01") == {"LK-JUN", "LK-AUG"}
    assert _names(valid_from="2025-06-01", valid_to="2025-09-01") == {"LK-JUN", "LK-AUG"}
    # the parent filter and the range compose
    assert _names(subject="SITE-LAKE-01", valid_from="2025-11-01") == {"LK-DEC"}
    # both bounds inclusive
    assert _names(valid_from="2025-06-15T09:00:00", valid_to="2025-06-15T09:00:00") == {"LK-JUN"}


def test_rest_list_and_show_expose_valid_time(env: None) -> None:
    _seasonal()
    rows = client.get("/specimens").json()
    assert all(row["valid_time"] for row in rows)
    body = client.get("/specimens/LK-JUN").json()
    assert body["valid_time"].startswith("2025-06-15T09:00:00")


def test_rest_valid_time_bound_offset_is_honoured(env: None) -> None:
    _seasonal()
    # 2025-06-15T09:00:00+00:00 is 2025-06-15T11:00:00+02:00; a bound just after it in
    # its own zone must exclude the record, which only works if the offset is applied.
    assert "LK-JUN" not in _names(valid_from="2025-06-15T11:00:01+02:00")
    assert "LK-JUN" in _names(valid_from="2025-06-15T10:59:59+02:00")


def test_graphql_list_filters_by_valid_time_range(env: None) -> None:
    _seasonal()

    def names(args: str) -> set[str]:
        data = _gql(f"{{ specimens{args} {{ name }} }}")
        return {n["name"].rsplit("/", 1)[1] for n in data["specimens"]}

    assert names("") == {"LK-JUN", "LK-AUG", "LK-DEC"}
    assert names('(validTo: "2025-09-01")') == {"LK-JUN", "LK-AUG"}
    assert names('(validFrom: "2025-06-01", validTo: "2025-09-01")') == {"LK-JUN", "LK-AUG"}
    assert names('(subject: "SITE-LAKE-01", validFrom: "2025-11-01")') == {"LK-DEC"}
    # validTime is readable on the node itself
    data = _gql('{ specimen(ref: "LK-JUN") { validTime } }')
    assert data["specimen"]["validTime"].startswith("2025-06-15T09:00:00")


def test_datapoint_and_facet_lists_take_the_range(env: None) -> None:
    _create("subjects", local_id="SUBJ-001")
    for local_id, when in (("DP-JUN", "2025-06-15T09:00:00"), ("DP-DEC", "2025-12-01T09:00:00")):
        client.post(
            "/datapoints",
            json={
                "local_id": local_id,
                "for": "SUBJ-001",
                "type": "x:m",
                "kind": "number",
                "value": "1",
                "valid_time": when,
            },
        )
    rows = client.get("/datapoints", params={"valid_to": "2025-09-01"}).json()
    assert [r["name"].rsplit("/", 1)[1] for r in rows] == ["DP-JUN"]
    assert all(r["valid_time"] for r in rows)

    client.post(
        "/facets",
        json={
            "to": "SUBJ-001",
            "schema_url": FIXTURE_SCHEMA,
            "type": "QcMetricsFacet",
            "producer": "p",
            "data": {"metric_name": "m", "metric_value": 1.0},
            "valid_time": "2025-06-15T09:00:00",
        },
    )
    assert len(client.get("/facets", params={"valid_to": "2025-09-01"}).json()) == 1
    assert client.get("/facets", params={"valid_from": "2025-09-01"}).json() == []
