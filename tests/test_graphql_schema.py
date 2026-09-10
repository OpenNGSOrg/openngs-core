"""End-to-end tests for the GraphQL schema - the `Node` interface,
traversal, and per-entity `Query` fields for the 14 `EntityConfig` entity types (items
1-3), plus `DataPoint`/`facet`/`facet schema`/`event` read access (item 4,
docs/graphql-design.md). Exercised the same way tests/test_api_*.py exercise the REST API:
FastAPI's `TestClient` against the real mounted app, not `schema.execute()` directly - this
is also what caught the cross-thread SQLite bug `graphql_schema.py`'s module docstring
documents; a bare `schema.execute()` call doesn't dispatch resolvers through the same
thread pool a live ASGI request does, so it wouldn't have caught it."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

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


def _rest_create(plural: str, **fields: object) -> str:
    r = client.post(f"/{plural}", json=fields)
    assert r.status_code == 200, r.text
    return str(r.json()["internal_id"])


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    r = client.post("/graphql", json={"query": query, "variables": variables or {}})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_graphiql_served(env: None) -> None:
    r = client.get("/graphql")
    assert r.status_code == 200
    assert "graphiql" in r.text.lower()


def test_schema_has_expected_query_fields(env: None) -> None:
    result = _gql('{ __type(name: "Query") { fields { name } } }')
    names = {f["name"] for f in result["data"]["__type"]["fields"]}
    assert {
        "node",
        "subject",
        "subjects",
        "specimen",
        "specimens",
        "dataFile",
        "dataFiles",
    } <= names


def test_show_and_traversal_across_multiple_fields(env: None) -> None:
    """Touches xrefs, outgoing, AND incoming in one query - the shape that surfaced the
    cross-thread SQLite bug when the fix was still a shared per-request connection."""
    subject_id = _rest_create("subjects", local_id="SUBJ-001", xrefs=["biosample:SAMN1"])
    specimen_id = _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    actor_id = _rest_create("actors", local_id="ACTOR-1")
    client.post("/links/used", json={"from": "SPEC-001", "to": "ACTOR-1"})

    result = _gql(
        """
        query {
          specimen(ref: "SPEC-001") {
            internalId
            name
            xrefs
            outgoing {
              predicate
              other { internalId name ... on Subject { xrefs } ... on Actor { xrefs } }
            }
            incoming { predicate other { internalId } }
          }
        }
        """
    )
    assert result.get("errors") is None, result
    specimen = result["data"]["specimen"]
    assert specimen["internalId"] == specimen_id
    assert specimen["xrefs"] == []
    predicates = {e["predicate"] for e in specimen["outgoing"]}
    assert predicates == {"derived_from", "used"}
    subject_edge = next(e for e in specimen["outgoing"] if e["predicate"] == "derived_from")
    assert subject_edge["other"]["internalId"] == subject_id
    assert subject_edge["other"]["xrefs"] == ["biosample:SAMN1"]
    actor_edge = next(e for e in specimen["outgoing"] if e["predicate"] == "used")
    assert actor_edge["other"]["internalId"] == actor_id
    assert specimen["incoming"] == []


def test_generic_node_lookup_is_polymorphic(env: None) -> None:
    _rest_create("actors", local_id="ACTOR-1", xrefs=["orcid:0000"])
    result = _gql('{ node(ref: "ACTOR-1") { internalId name ... on Actor { xrefs } } }')
    assert result.get("errors") is None, result
    assert result["data"]["node"]["xrefs"] == ["orcid:0000"]


def test_node_lookup_unknown_ref_returns_null(env: None) -> None:
    result = _gql('{ node(ref: "NOPE") { internalId } }')
    assert result.get("errors") is None, result
    assert result["data"]["node"] is None


def test_show_unknown_ref_returns_null_not_error(env: None) -> None:
    result = _gql('{ specimen(ref: "NOPE") { internalId } }')
    assert result.get("errors") is None, result
    assert result["data"]["specimen"] is None


def test_list_with_parent_filter_uses_camel_case_arg_name(env: None) -> None:
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-002", subject="SUBJ-001")
    _rest_create("subjects", local_id="SUBJ-002")
    _rest_create("specimens", local_id="SPEC-003", subject="SUBJ-002")

    result = _gql('{ specimens(subject: "SUBJ-001") { name } }')
    assert result.get("errors") is None, result
    names = {s["name"] for s in result["data"]["specimens"]}
    assert names == {
        "openngs://acme-genomics/core-lab/specimen/SPEC-001",
        "openngs://acme-genomics/core-lab/specimen/SPEC-002",
    }


def test_list_with_camel_case_produced_by_arg(env: None) -> None:
    _rest_create("sequencing-runs", local_id="RUN-001")
    _rest_create("data-files", local_id="R1.fastq.gz", produced_by="RUN-001")

    result = _gql('{ dataFiles(producedBy: "RUN-001") { name } }')
    assert result.get("errors") is None, result
    assert len(result["data"]["dataFiles"]) == 1


def test_list_without_parent_has_no_filter_arg(env: None) -> None:
    _rest_create("pools", local_id="POOL-001")
    result = _gql("{ pools { name } }")
    assert result.get("errors") is None, result
    assert len(result["data"]["pools"]) == 1


def test_list_respects_limit(env: None) -> None:
    for i in range(3):
        _rest_create("actors", local_id=f"ACTOR-{i}")
    result = _gql("{ actors(limit: 2) { name } }")
    assert result.get("errors") is None, result
    assert len(result["data"]["actors"]) == 2


def test_same_as_edge_carries_evidentiary_fields(env: None) -> None:
    _rest_create("subjects", local_id="SUBJ-A")
    _rest_create("subjects", local_id="SUBJ-B")
    _rest_create("actors", local_id="ACTOR-1")
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

    result = _gql(
        '{ subject(ref: "SUBJ-A") { outgoing { predicate assertedBy method confidence '
        "other { internalId } } } }"
    )
    assert result.get("errors") is None, result
    edge = result["data"]["subject"]["outgoing"][0]
    assert edge["predicate"] == "same_as"
    assert edge["method"] == "barcode_scan"
    assert edge["confidence"] == 0.95
    assert edge["assertedBy"] is not None


# --- item 4: DataPoint / facet / facet schema / event read access ------------------------


def test_datapoint_is_a_node_with_its_own_fields(env: None) -> None:
    """DataPoint isn't EntityConfig-registered, so it's hand-added to the schema (unlike
    the 14 looped types) - checks its Node fields (xrefs included, unlike REST's own
    datapoint show/list, which never selects xrefs - a pre-existing store-layer gap this
    doesn't need to fix, since Node.xrefs reads the xrefs table directly) and its own
    datapoint-specific fields all resolve together."""
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    dp_id = _rest_create(
        "datapoints",
        local_id="SPEC-001-flag",
        **{"for": "SPEC-001", "type": "acme:flagged", "kind": "boolean", "value": "true"},
        xrefs=["acme:xref-1"],
    )

    result = _gql(
        """
        query {
          datapoint(ref: "SPEC-001-flag") {
            internalId
            name
            xrefs
            datapointType
            valueKind
            value
            outgoing { predicate other { internalId } }
          }
        }
        """
    )
    assert result.get("errors") is None, result
    dp = result["data"]["datapoint"]
    assert dp["internalId"] == dp_id
    assert dp["xrefs"] == ["acme:xref-1"]
    assert dp["datapointType"] == "acme:flagged"
    assert dp["valueKind"] == "boolean"
    assert dp["value"] is True
    assert dp["outgoing"][0]["predicate"] == "characterizes"


def test_datapoint_reachable_via_traversal_and_polymorphic_node(env: None) -> None:
    """The actual point of giving DataPoint a Node type: reaching it as an edge endpoint
    from an arbitrary starting entity (here, a Specimen's `incoming`), and via the generic
    `node(ref)` lookup - both without the caller knowing ahead of time it's a DataPoint."""
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _rest_create(
        "datapoints",
        local_id="SPEC-001-flag",
        **{"for": "SPEC-001", "type": "acme:flagged", "kind": "number", "value": "3.5"},
    )

    result = _gql(
        '{ specimen(ref: "SPEC-001") { incoming { predicate other { internalId '
        "... on DataPoint { valueKind value } } } } }"
    )
    assert result.get("errors") is None, result
    other = result["data"]["specimen"]["incoming"][0]["other"]
    assert other["valueKind"] == "number"
    assert other["value"] == 3.5

    result = _gql(
        '{ node(ref: "SPEC-001-flag") { internalId ... on DataPoint { datapointType } } }'
    )
    assert result.get("errors") is None, result
    assert result["data"]["node"]["datapointType"] == "acme:flagged"


def test_datapoint_list_filtered_by_for(env: None) -> None:
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-002", subject="SUBJ-001")
    _rest_create(
        "datapoints",
        local_id="SPEC-001-flag",
        **{"for": "SPEC-001", "type": "acme:flagged", "kind": "boolean", "value": "true"},
    )
    _rest_create(
        "datapoints",
        local_id="SPEC-002-flag",
        **{"for": "SPEC-002", "type": "acme:flagged", "kind": "boolean", "value": "false"},
    )

    result = _gql('{ datapoints(for: "SPEC-001") { name } }')
    assert result.get("errors") is None, result
    names = {d["name"] for d in result["data"]["datapoints"]}
    assert names == {"openngs://acme-genomics/core-lab/datapoint/SPEC-001-flag"}


def test_datapoint_unknown_ref_returns_null(env: None) -> None:
    result = _gql('{ datapoint(ref: "NOPE") { internalId } }')
    assert result.get("errors") is None, result
    assert result["data"]["datapoint"] is None


def _register_and_attach_facet(schema_local_id: str, to_ref: str) -> tuple[str, str]:
    """Returns (schema_id, facet_id)."""
    r = client.post(
        "/facet-schemas",
        json={
            "local_id": schema_local_id,
            "json_schema": {
                "title": "Qc",
                "type": "object",
                "properties": {"x": {"type": "number"}},
            },
        },
    )
    assert r.status_code == 200, r.text
    schema_id = str(r.json()["schema_id"])
    r = client.post(
        "/facets",
        json={
            "to": to_ref,
            "schema_id": schema_id,
            "type": "Qc",
            "producer": "acme-tool@1.0",
            "data": {"x": 1.5},
        },
    )
    assert r.status_code == 200, r.text
    return schema_id, str(r.json()["facet_id"])


def test_facet_show_and_list(env: None) -> None:
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _, facet_id = _register_and_attach_facet("qc", "SPEC-001")

    result = _gql(
        f'{{ facet(facetId: "{facet_id}") {{ '
        "facetId facetType _producer _schemaURL attachedTo data } }"
    )
    assert result.get("errors") is None, result
    facet = result["data"]["facet"]
    assert facet["facetId"] == facet_id
    assert facet["facetType"] == "Qc"
    assert facet["_producer"] == "acme-tool@1.0"
    assert facet["data"] == {"x": 1.5}

    result = _gql('{ facets(to: "SPEC-001") { facetId facetType } }')
    assert result.get("errors") is None, result
    assert [f["facetId"] for f in result["data"]["facets"]] == [facet_id]


def test_facet_unknown_id_returns_null(env: None) -> None:
    result = _gql('{ facet(facetId: "00000000-0000-7000-8000-000000000000") { facetId } }')
    assert result.get("errors") is None, result
    assert result["data"]["facet"] is None


def test_facet_schema_show_and_list(env: None) -> None:
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    schema_id, _ = _register_and_attach_facet("qc", "SPEC-001")

    result = _gql('{ facetSchema(ref: "qc") { schemaId schemaName jsonSchema } }')
    assert result.get("errors") is None, result
    schema = result["data"]["facetSchema"]
    assert schema["schemaId"] == schema_id
    assert schema["jsonSchema"]["title"] == "Qc"

    result = _gql('{ facetSchemas(name: "qc") { schemaId } }')
    assert result.get("errors") is None, result
    assert [s["schemaId"] for s in result["data"]["facetSchemas"]] == [schema_id]


def test_facet_schema_unknown_ref_returns_null(env: None) -> None:
    result = _gql('{ facetSchema(ref: "NOPE") { schemaId } }')
    assert result.get("errors") is None, result
    assert result["data"]["facetSchema"] is None


def test_event_show_and_list(env: None) -> None:
    subject_id = _rest_create("subjects", local_id="SUBJ-001")

    result = _gql("{ events(limit: 5) { eventId source type subject validTime payload } }")
    assert result.get("errors") is None, result
    events = result["data"]["events"]
    assert len(events) == 1
    event = events[0]
    assert event["source"] == "openngs-api"
    assert event["type"] == "entity_created"
    assert event["subject"] == subject_id
    assert isinstance(event["validTime"], str) and "T" in event["validTime"]
    assert event["payload"]["internal_id"] == subject_id

    result = _gql(f'{{ event(eventId: "{event["eventId"]}") {{ type supersedes }} }}')
    assert result.get("errors") is None, result
    assert result["data"]["event"]["type"] == "entity_created"
    assert result["data"]["event"]["supersedes"] is None


def test_event_unknown_id_returns_null(env: None) -> None:
    result = _gql('{ event(eventId: "00000000-0000-7000-8000-000000000000") { eventId } }')
    assert result.get("errors") is None, result
    assert result["data"]["event"] is None


def test_events_filtered_by_ref_includes_touching_edges(env: None) -> None:
    """events(ref:) mirrors REST's show(events=true): an entity's own entity_created event,
    plus edge_created/same_as_edge_created for every edge touching it - not just events
    whose raw `subject` literally equals the REF. Added after Claude Desktop's execute_graphql
    testing surfaced that the unfiltered events field alone forces a full-log scan to find
    one entity's events, unlike REST's per-entity show(events=true)."""
    _rest_create("subjects", local_id="SUBJ-001")
    _rest_create("specimens", local_id="SPEC-001", subject="SUBJ-001")
    _rest_create("actors", local_id="ACTOR-1")
    r = client.post("/links/used", json={"from": "SPEC-001", "to": "ACTOR-1"})
    assert r.status_code == 200, r.text
    edge_id = r.json()["edge_id"]

    result = _gql('{ events(ref: "SPEC-001") { type subject } }')
    assert result.get("errors") is None, result
    events = result["data"]["events"]
    assert {e["type"] for e in events} == {"entity_created", "edge_created"}
    assert sum(1 for e in events if e["type"] == "edge_created") == 2  # derived_from + used

    # a bare edge_id resolves too, and doesn't try to expand further (edges have no edges)
    result = _gql(f'{{ events(ref: "{edge_id}") {{ type subject }} }}')
    assert result.get("errors") is None, result
    assert [e["subject"] for e in result["data"]["events"]] == [edge_id]


def test_events_filtered_by_unknown_ref_returns_empty_list(env: None) -> None:
    result = _gql('{ events(ref: "NOPE") { eventId } }')
    assert result.get("errors") is None, result
    assert result["data"]["events"] == []


def test_nested_datafileset_and_used_widening_need_no_graphql_code_change(env: None) -> None:
    """DataFileSet.produced_by accepts SequencingRun, and `used`
    now accepts DataFile/DataFileSet - both write-path (entities.py) changes only. This
    confirms the read path needed nothing: outgoing/incoming already resolve any
    predicate/target pair generically, regardless of what the write-path type check allows."""
    client.post("/sequencing-runs", json={"local_id": "RUN-001"})
    client.post("/data-file-sets", json={"local_id": "RUN-001-BCL", "produced_by": "RUN-001"})
    client.post("/analysis-runs", json={"local_id": "BCLCONVERT-1"})
    client.post("/links/used", json={"from": "BCLCONVERT-1", "to": "RUN-001-BCL"})
    client.post(
        "/data-file-sets", json={"local_id": "RUN-001-FASTQ", "produced_by": "BCLCONVERT-1"}
    )
    client.post(
        "/data-file-sets",
        json={"local_id": "SAMPLE-042-FASTQ", "produced_by": "BCLCONVERT-1"},
    )
    r = client.post("/links/part-of", json={"from": "SAMPLE-042-FASTQ", "to": "RUN-001-FASTQ"})
    assert r.status_code == 200, r.text

    result = _gql(
        """
        query {
          dataFileSet(ref: "RUN-001-BCL") {
            name
            outgoing { predicate other { internalId name ... on SequencingRun { name } } }
            incoming { predicate other { internalId name ... on AnalysisRun { name } } }
          }
        }
        """
    )
    assert result.get("errors") is None, result
    bcl_set = result["data"]["dataFileSet"]
    assert bcl_set["outgoing"] == [
        {
            "predicate": "produced_by",
            "other": {
                "internalId": bcl_set["outgoing"][0]["other"]["internalId"],
                "name": "openngs://acme-genomics/core-lab/sequencing-run/RUN-001",
            },
        }
    ]
    assert bcl_set["incoming"][0]["predicate"] == "used"
    assert bcl_set["incoming"][0]["other"]["name"].endswith("BCLCONVERT-1")

    result = _gql('{ dataFileSet(ref: "SAMPLE-042-FASTQ") { outgoing { predicate } } }')
    assert result.get("errors") is None, result
    predicates = {e["predicate"] for e in result["data"]["dataFileSet"]["outgoing"]}
    assert predicates == {"produced_by", "part_of"}


def test_dangling_edge_resolves_to_null_other_not_an_error(env: None, tmp_path: Path) -> None:
    """Edge.edge_subject/object have no FK, so an edge can point at an id no
    entity table holds. REST renders that as other_type null; GraphQL must match rather
    than raise and null the whole parent entity."""
    subject_id = _rest_create("subjects", local_id="SUBJ-001")
    conn = sqlite3.connect(tmp_path / "test.db")
    conn.execute(
        'INSERT INTO "Edge" (edge_id, edge_subject, predicate, object, valid_time) '
        "VALUES (?, ?, ?, ?, ?)",
        (
            "019a0000-0000-7000-8000-000000000001",
            subject_id,
            "part_of",
            "019a0000-0000-7000-8000-0000000000ff",
            "2026-01-15T09:00:00+00:00",
        ),
    )
    conn.commit()
    conn.close()
    body = _gql('{ subject(ref: "SUBJ-001") { name outgoing { predicate other { name } } } }')
    assert "errors" not in body, body
    assert body["data"]["subject"]["outgoing"] == [{"predicate": "part_of", "other": None}]
