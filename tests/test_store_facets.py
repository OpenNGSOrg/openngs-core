"""Unit tests for generic facet-instance storage and validation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openngs.store import (
    Database,
    FacetValidationError,
    RepoError,
    build_schema_name,
    get_facet_instance,
    get_facet_schema,
    insert_facet_instance,
    insert_facet_instance_from_store,
    list_facet_instances,
    list_facet_schemas,
    register_facet_schema,
    resolve_facet_schema_ref,
    validate_facet_data,
)

FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")
FIXTURE_SCHEMA_TEXT = Path(FIXTURE_SCHEMA).read_text()
NOW = datetime.now(UTC)
ORG = "acme-genomics"
NS = "core-lab"


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return Database.connect(f"sqlite:///{db_path}")


def test_validate_facet_data_accepts_valid_instance() -> None:
    data = {"metric_name": "percent_duplication", "metric_value": 12.3}
    validate_facet_data(FIXTURE_SCHEMA, "QcMetricsFacet", data)


def test_validate_facet_data_rejects_missing_required_field() -> None:
    with pytest.raises(FacetValidationError, match="required"):
        validate_facet_data(FIXTURE_SCHEMA, "QcMetricsFacet", {"metric_value": 12.3})


def test_validate_facet_data_rejects_wrong_type() -> None:
    with pytest.raises(FacetValidationError):
        validate_facet_data(
            FIXTURE_SCHEMA, "QcMetricsFacet", {"metric_name": "x", "metric_value": "not-a-number"}
        )


def test_validate_facet_data_unknown_facet_type() -> None:
    with pytest.raises(RepoError, match="not found in schema"):
        validate_facet_data(FIXTURE_SCHEMA, "NoSuchFacet", {})


def test_load_json_schema_missing_file() -> None:
    with pytest.raises(RepoError, match="doesn't resolve to a local file"):
        validate_facet_data("/nope/nope.json", "QcMetricsFacet", {})


def test_insert_and_get_facet_instance_round_trips(db: Database) -> None:
    data = {"tool": "fastqc", "metric_name": "percent_duplication", "metric_value": 12.3}
    facet_id = insert_facet_instance(
        db,
        attached_to="018f5b2a-0000-7000-8000-000000000001",
        producer="fastqc/0.12.1",
        schema_url=FIXTURE_SCHEMA,
        facet_type="QcMetricsFacet",
        data=data,
        valid_time=NOW,
    )
    instance = get_facet_instance(db, facet_id)
    assert instance is not None
    assert instance["facet_type"] == "QcMetricsFacet"
    assert instance["data"] == data
    assert instance["_producer"] == "fastqc/0.12.1"
    assert instance["_schemaURL"] == FIXTURE_SCHEMA


def test_insert_facet_instance_rejects_invalid_data(db: Database) -> None:
    with pytest.raises(FacetValidationError):
        insert_facet_instance(
            db,
            attached_to="018f5b2a-0000-7000-8000-000000000001",
            producer="fastqc/0.12.1",
            schema_url=FIXTURE_SCHEMA,
            facet_type="QcMetricsFacet",
            data={"tool": "fastqc"},  # missing metric_name/metric_value
            valid_time=NOW,
        )


def test_get_facet_instance_not_found(db: Database) -> None:
    assert get_facet_instance(db, "018f5b2a-0000-7000-8000-999999999999") is None


def test_list_facet_instances_filters_by_attached_to(db: Database) -> None:
    data = {"metric_name": "percent_duplication", "metric_value": 1.0}
    insert_facet_instance(db, "entity-a", "p", FIXTURE_SCHEMA, "QcMetricsFacet", data, NOW)
    insert_facet_instance(db, "entity-a", "p", FIXTURE_SCHEMA, "QcMetricsFacet", data, NOW)
    insert_facet_instance(db, "entity-b", "p", FIXTURE_SCHEMA, "QcMetricsFacet", data, NOW)

    assert len(list_facet_instances(db, "entity-a", limit=50)) == 2
    assert len(list_facet_instances(db, "entity-b", limit=50)) == 1
    assert len(list_facet_instances(db, None, limit=50)) == 3
    assert len(list_facet_instances(db, "entity-a", limit=1)) == 1


# --- facet schema store --------------------------------------------------------


def test_register_and_get_facet_schema(db: Database) -> None:
    name = build_schema_name(ORG, NS, "qc-metrics")
    schema_id = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    fetched = get_facet_schema(db, schema_id)
    assert fetched is not None
    assert fetched["schema_name"] == name
    assert fetched["json_schema"]["$defs"]["QcMetricsFacet"]


def test_register_rejects_invalid_json(db: Database) -> None:
    with pytest.raises(RepoError, match="not valid JSON"):
        register_facet_schema(db, build_schema_name(ORG, NS, "bad"), "{not json")


def test_reregistering_creates_a_new_version_not_an_overwrite(db: Database) -> None:
    name = build_schema_name(ORG, NS, "qc-metrics")
    first = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    second = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    assert first != second
    assert get_facet_schema(db, first) is not None
    assert get_facet_schema(db, second) is not None
    assert len(list_facet_schemas(db, name, limit=50)) == 2


def test_resolve_facet_schema_ref_by_schema_id(db: Database) -> None:
    name = build_schema_name(ORG, NS, "qc-metrics")
    schema_id = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    resolved_id, text = resolve_facet_schema_ref(db, schema_id, ORG, NS)
    assert resolved_id == schema_id
    assert text == FIXTURE_SCHEMA_TEXT


def test_resolve_facet_schema_ref_by_local_id_picks_newest(db: Database) -> None:
    name = build_schema_name(ORG, NS, "qc-metrics")
    register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    newest = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    resolved_id, _ = resolve_facet_schema_ref(db, "qc-metrics", ORG, NS)
    assert resolved_id == newest


def test_resolve_facet_schema_ref_not_found(db: Database) -> None:
    with pytest.raises(RepoError, match="no registered schema found"):
        resolve_facet_schema_ref(db, "nope", ORG, NS)


def test_insert_facet_instance_from_store_pins_exact_schema_id(db: Database) -> None:
    name = build_schema_name(ORG, NS, "qc-metrics")
    schema_id = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    data = {"metric_name": "percent_duplication", "metric_value": 1.0}
    facet_id = insert_facet_instance_from_store(
        db, "entity-a", "p", schema_id, FIXTURE_SCHEMA_TEXT, "QcMetricsFacet", data, NOW
    )
    instance = get_facet_instance(db, facet_id)
    assert instance is not None
    assert instance["_schemaURL"] == f"openngs-schema://{schema_id}"

    # A newer version registered afterward must not affect what this instance points to.
    newer = register_facet_schema(db, name, FIXTURE_SCHEMA_TEXT)
    instance_again = get_facet_instance(db, facet_id)
    assert instance_again is not None
    assert instance_again["_schemaURL"] == f"openngs-schema://{schema_id}"
    assert instance_again["_schemaURL"] != f"openngs-schema://{newer}"


def test_insert_facet_instance_from_store_rejects_invalid_data(db: Database) -> None:
    schema_id = register_facet_schema(
        db, build_schema_name(ORG, NS, "qc-metrics"), FIXTURE_SCHEMA_TEXT
    )
    with pytest.raises(FacetValidationError):
        insert_facet_instance_from_store(
            db,
            "entity-a",
            "p",
            schema_id,
            FIXTURE_SCHEMA_TEXT,
            "QcMetricsFacet",
            {"tool": "x"},
            NOW,
        )


def test_validate_facet_data_resolves_refs_between_defs(tmp_path: Path) -> None:
    """LinkML emits a `$ref: "#/$defs/..."` for every enum-typed or nested-class slot. The
    class's definition must be validated with the rest of the document's defs still
    attached, or those refs can't resolve and every instance - valid or not - fails."""
    import json

    schema = {
        "$schema": "https://json-schema.org/draft/2019-09/schema",
        "$defs": {
            "Status": {"enum": ["pass", "fail"], "title": "Status"},
            "EnumFacet": {
                "type": "object",
                "title": "EnumFacet",
                "properties": {"status": {"$ref": "#/$defs/Status"}},
                "required": ["status"],
            },
        },
        "title": "acme_facet_enum",
        "type": "object",
    }
    path = tmp_path / "enum.schema.json"
    path.write_text(json.dumps(schema))

    validate_facet_data(str(path), "EnumFacet", {"status": "pass"})
    with pytest.raises(FacetValidationError, match="not one of"):
        validate_facet_data(str(path), "EnumFacet", {"status": "bogus"})


def test_validate_facet_data_unresolvable_ref_is_a_schema_error(tmp_path: Path) -> None:
    import json

    schema = {
        "$defs": {
            "BrokenFacet": {
                "type": "object",
                "properties": {"x": {"$ref": "#/$defs/DoesNotExist"}},
            }
        }
    }
    path = tmp_path / "broken.schema.json"
    path.write_text(json.dumps(schema))
    with pytest.raises(RepoError, match="unresolvable"):
        validate_facet_data(str(path), "BrokenFacet", {"x": 1})
