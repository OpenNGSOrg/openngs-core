"""Unit tests for the append-only event log."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openngs.model import EdgePredicate
from openngs.store import (
    DEFAULT_SOURCE,
    Database,
    apply_event,
    build_schema_name,
    emit_event,
    get_datapoint,
    get_event,
    get_facet_instance,
    get_facet_schema,
    list_events,
    list_events_for_subjects,
    lookup_entity,
    record_datapoint_created,
    record_edge_created,
    record_entity_created,
    record_facet_instance_attached,
    record_facet_instance_attached_from_store,
    record_facet_schema_registered,
    record_same_as_edge_created,
    replay,
)
from openngs.store.events import EventType
from openngs.store.repo import RepoError

FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")
FIXTURE_SCHEMA_TEXT = Path(FIXTURE_SCHEMA).read_text()
ORG = "acme-genomics"
NS = "core-lab"
NOW = datetime.now(UTC)


@pytest.fixture
def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return Database.connect(f"sqlite:///{db_path}")


def _name(entity_type: str, local_id: str) -> str:
    return f"openngs://{ORG}/{NS}/{entity_type.lower()}/{local_id}"


def test_emit_event_and_get_event_round_trip(db: Database) -> None:
    event_id = emit_event(
        db,
        DEFAULT_SOURCE,
        EventType.entity_created,
        "some-subject",
        NOW,
        NOW,
        {"hello": "world"},
    )
    event = get_event(db, event_id)
    assert event is not None
    assert event["event_id"] == event_id
    assert event["type"] == "entity_created"
    assert event["subject"] == "some-subject"
    assert event["payload"] == {"hello": "world"}
    assert event["supersedes"] is None
    assert event["supersede_reason"] is None


def test_get_event_not_found(db: Database) -> None:
    assert get_event(db, "018f5b2a-0000-7000-8000-999999999999") is None


def test_list_events_orders_chronologically_and_respects_limit(db: Database) -> None:
    for i in range(3):
        emit_event(db, DEFAULT_SOURCE, EventType.entity_created, f"subj-{i}", NOW, NOW, {"i": i})
    events = list_events(db)
    assert [e["payload"]["i"] for e in events] == [0, 1, 2]
    assert len(list_events(db, limit=2)) == 2


def test_list_events_for_subjects_empty_input_returns_empty(db: Database) -> None:
    assert list_events_for_subjects(db, []) == []


def test_list_events_for_subjects_filters_and_orders(db: Database) -> None:
    subj_id, subj_event_id = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "SUBJ-001"), [], NOW, NOW
    )
    spec_id, spec_event_id = record_entity_created(
        db, DEFAULT_SOURCE, "Specimen", _name("specimen", "SPEC-001"), [], NOW, NOW
    )
    edge_id, edge_event_id = record_edge_created(
        db, DEFAULT_SOURCE, spec_id, EdgePredicate.derived_from, subj_id, NOW, NOW
    )

    # Everything related to the Specimen: its own creation event, plus the edge_created
    # event whose subject is the edge_id (not either entity's internal_id).
    events = list_events_for_subjects(db, [spec_id, edge_id])
    assert [e["event_id"] for e in events] == [spec_event_id, edge_event_id]

    # An unrelated subject (Subject's own creation) isn't pulled in.
    assert subj_event_id not in [e["event_id"] for e in events]


def test_record_entity_created_writes_event_and_projection(db: Database) -> None:
    internal_id, event_id = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "SUBJ-001"), [], NOW, NOW
    )
    found = lookup_entity(db, internal_id)
    assert found == ("Subject", _name("subject", "SUBJ-001"))
    event = get_event(db, event_id)
    assert event is not None
    assert event["type"] == "entity_created"
    assert event["payload"]["entity_type"] == "Subject"
    assert event["payload"]["internal_id"] == internal_id


def test_record_datapoint_created_writes_event_and_projection(db: Database) -> None:
    internal_id, event_id = record_datapoint_created(
        db,
        DEFAULT_SOURCE,
        _name("datapoint", "DP-001"),
        [],
        "openngs-dp:percent_duplication",
        "number",
        12.3,
        None,
        None,
        NOW,
        NOW,
    )
    row = get_datapoint(db, internal_id)
    assert row is not None
    assert row["value_number"] == 12.3
    event = get_event(db, event_id)
    assert event is not None
    assert event["payload"]["entity_type"] == "DataPoint"
    assert event["payload"]["value_number"] == 12.3


def test_record_edge_created_writes_event_and_projection(db: Database) -> None:
    subj_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Specimen", _name("specimen", "SPEC-001"), [], NOW, NOW
    )
    obj_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "SUBJ-001"), [], NOW, NOW
    )
    edge_id, event_id = record_edge_created(
        db, DEFAULT_SOURCE, subj_id, EdgePredicate.derived_from, obj_id, NOW, NOW
    )
    event = get_event(db, event_id)
    assert event is not None
    assert event["subject"] == edge_id
    assert event["payload"]["predicate"] == "derived_from"  # not "EdgePredicate.derived_from"


def test_record_same_as_edge_created_writes_event_and_projection(db: Database) -> None:
    a_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "A"), [], NOW, NOW
    )
    b_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "B"), [], NOW, NOW
    )
    edge_id, event_id = record_same_as_edge_created(
        db, DEFAULT_SOURCE, a_id, b_id, "actor-1", "manual", 0.9, NOW, NOW
    )
    event = get_event(db, event_id)
    assert event is not None
    assert event["type"] == "same_as_edge_created"
    assert event["payload"]["edge_id"] == edge_id
    assert event["payload"]["confidence"] == 0.9
    # asserted_at is when the assertion was made in the lab, i.e. valid_time (invariant 2)
    assert event["payload"]["asserted_at"] == NOW.isoformat()
    assert event["payload"]["asserted_at"] == event["valid_time"]


def test_record_same_as_edge_asserted_at_follows_valid_time(db: Database) -> None:
    from datetime import timedelta

    a_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "A"), [], NOW, NOW
    )
    b_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "B"), [], NOW, NOW
    )
    monday = NOW - timedelta(days=2)
    edge_id, _ = record_same_as_edge_created(
        db, DEFAULT_SOURCE, a_id, b_id, "actor-1", "barcode_scan", 1.0, monday, NOW
    )
    row = db.fetchone(
        f'SELECT asserted_at FROM "SameAsEdge" WHERE edge_id = {db.ph(1)}', (edge_id,)
    )
    assert row is not None
    assert row[0] == monday.isoformat()


def test_record_edge_created_refuses_duplicates_and_self_loops(db: Database) -> None:
    from openngs.store.repo import RepoError

    subj_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "SUBJ-001"), [], NOW, NOW
    )
    spec_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Specimen", _name("specimen", "SPEC-001"), [], NOW, NOW
    )
    record_edge_created(db, DEFAULT_SOURCE, spec_id, EdgePredicate.derived_from, subj_id, NOW, NOW)
    with pytest.raises(RepoError, match="already exists"):
        record_edge_created(
            db, DEFAULT_SOURCE, spec_id, EdgePredicate.derived_from, subj_id, NOW, NOW
        )
    with pytest.raises(RepoError, match="itself"):
        record_edge_created(
            db, DEFAULT_SOURCE, spec_id, EdgePredicate.derived_from, spec_id, NOW, NOW
        )
    with pytest.raises(RepoError, match="itself"):
        record_same_as_edge_created(
            db, DEFAULT_SOURCE, spec_id, spec_id, "actor-1", "manual", 0.5, NOW, NOW
        )
    # a second, independent same_as assertion for the same pair is fine (invariant 3)
    record_same_as_edge_created(
        db, DEFAULT_SOURCE, spec_id, subj_id, "actor-1", "manual", 0.5, NOW, NOW
    )
    record_same_as_edge_created(
        db, DEFAULT_SOURCE, spec_id, subj_id, "actor-2", "manual", 0.9, NOW, NOW
    )


def test_record_facet_instance_attached_writes_event_and_projection(db: Database) -> None:
    entity_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "DataFile", _name("data-file", "R1.fastq.gz"), [], NOW, NOW
    )
    facet_id, event_id = record_facet_instance_attached(
        db,
        DEFAULT_SOURCE,
        entity_id,
        "multiqc",
        FIXTURE_SCHEMA,
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 12.3},
        NOW,
        NOW,
    )
    facet = get_facet_instance(db, facet_id)
    assert facet is not None
    event = get_event(db, event_id)
    assert event is not None
    assert event["payload"]["schema_mode"] == "url"


def test_record_facet_schema_registered_and_attached_from_store(db: Database) -> None:
    schema_name = build_schema_name(ORG, NS, "qc-metrics")
    schema_id, schema_event_id = record_facet_schema_registered(
        db, DEFAULT_SOURCE, schema_name, FIXTURE_SCHEMA_TEXT, NOW, NOW
    )
    schema_event = get_event(db, schema_event_id)
    assert schema_event is not None
    assert schema_event["type"] == "facet_schema_registered"
    assert schema_event["payload"]["schema_id"] == schema_id

    entity_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "DataFile", _name("data-file", "R2.fastq.gz"), [], NOW, NOW
    )
    facet_id, facet_event_id = record_facet_instance_attached_from_store(
        db,
        DEFAULT_SOURCE,
        entity_id,
        "multiqc",
        schema_id,
        FIXTURE_SCHEMA_TEXT,
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 9.9},
        NOW,
        NOW,
    )
    facet = get_facet_instance(db, facet_id)
    assert facet is not None
    facet_event = get_event(db, facet_event_id)
    assert facet_event is not None
    assert facet_event["payload"]["schema_mode"] == "store"
    assert facet_event["payload"]["schema_id"] == schema_id
    # the full schema text is NOT duplicated into the payload
    assert "json_schema" not in facet_event["payload"]


def test_apply_event_unknown_type_raises(db: Database) -> None:
    from openngs.store.repo import RepoError

    with pytest.raises(RepoError, match="unknown event type"):
        apply_event(db, {"type": "not_a_real_type", "payload": {}})


def test_replay_reproduces_projection(db: Database) -> None:
    """The acceptance criterion: replaying the log from scratch reproduces the exact
    same projection - same internal_ids, same edges, same facet/datapoint data."""
    subj_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "SUBJ-001"), ["biosample:SAMN1"], NOW, NOW
    )
    spec_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Specimen", _name("specimen", "SPEC-001"), [], NOW, NOW
    )
    record_edge_created(db, DEFAULT_SOURCE, spec_id, EdgePredicate.derived_from, subj_id, NOW, NOW)
    dp_id, _ = record_datapoint_created(
        db,
        DEFAULT_SOURCE,
        _name("datapoint", "DP-001"),
        [],
        "openngs-dp:percent_duplication",
        "number",
        12.3,
        None,
        None,
        NOW,
        NOW,
    )
    record_edge_created(db, DEFAULT_SOURCE, dp_id, EdgePredicate.characterizes, spec_id, NOW, NOW)
    schema_name = build_schema_name(ORG, NS, "qc-metrics")
    schema_id, _ = record_facet_schema_registered(
        db, DEFAULT_SOURCE, schema_name, FIXTURE_SCHEMA_TEXT, NOW, NOW
    )
    facet_id, _ = record_facet_instance_attached_from_store(
        db,
        DEFAULT_SOURCE,
        spec_id,
        "multiqc",
        schema_id,
        FIXTURE_SCHEMA_TEXT,
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 12.3},
        NOW,
        NOW,
    )
    a_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "A"), [], NOW, NOW
    )
    b_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "B"), [], NOW, NOW
    )
    record_same_as_edge_created(db, DEFAULT_SOURCE, a_id, b_id, "actor-1", "manual", 0.9, NOW, NOW)

    events_before = list_events(db)
    count = replay(db)
    assert count == len(events_before)
    assert list_events(db) == events_before  # replay never touches the Event table itself

    assert lookup_entity(db, subj_id) == ("Subject", _name("subject", "SUBJ-001"))
    assert lookup_entity(db, spec_id) == ("Specimen", _name("specimen", "SPEC-001"))
    row = get_datapoint(db, dp_id)
    assert row is not None
    assert row["value_number"] == 12.3
    facet = get_facet_instance(db, facet_id)
    assert facet is not None
    assert facet["data"]["metric_value"] == 12.3
    schema = get_facet_schema(db, schema_id)
    assert schema is not None

    outgoing = db.fetchall(
        'SELECT edge_subject, predicate, object FROM "Edge" ORDER BY edge_id', ()
    )
    assert (spec_id, "derived_from", subj_id) in outgoing
    assert (dp_id, "characterizes", spec_id) in outgoing
    same_as = db.fetchall('SELECT edge_subject, object FROM "SameAsEdge"', ())
    assert (a_id, b_id) in same_as

    # replaying a second time is idempotent - same result again
    count2 = replay(db)
    assert count2 == count
    assert lookup_entity(db, subj_id) == ("Subject", _name("subject", "SUBJ-001"))


def test_replay_does_not_depend_on_the_schema_url_file(db: Database, tmp_path: Path) -> None:
    """The projection must be rebuildable from the log alone. A --schema-url
    facet's data was validated when recorded; replay reinstates it without re-reading the
    schema file, so the file moving or vanishing later can't break replay."""
    import shutil

    schema_copy = tmp_path / "qc_metrics.schema.json"
    shutil.copy(FIXTURE_SCHEMA, schema_copy)
    entity_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "DataFile", _name("data-file", "R1.fastq.gz"), [], NOW, NOW
    )
    facet_id, _ = record_facet_instance_attached(
        db,
        DEFAULT_SOURCE,
        entity_id,
        "multiqc",
        str(schema_copy),
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 12.3},
        NOW,
        NOW,
    )
    schema_copy.unlink()

    assert replay(db) == 2
    facet = get_facet_instance(db, facet_id)
    assert facet is not None
    assert facet["_schemaURL"] == str(schema_copy)
    assert facet["data"]["metric_value"] == 12.3


def test_event_rows_normalize_datetime_columns_to_iso_strings() -> None:
    """SQLite returns the ISO string emit_event wrote; Postgres/pg8000 returns a datetime
    for its native TIMESTAMP columns. Either way callers (CLI json.dumps, REST, GraphQL)
    must see one shape."""
    from openngs.store.events import _event_row_to_dict

    when = datetime(2026, 1, 15, 9, 0, 0)
    row = (
        "018f5b2a-0000-7000-8000-000000000001",
        DEFAULT_SOURCE,
        "entity_created",
        "1.0",
        None,
        when,
        "application/json",
        when,
        "2026-01-15T09:00:00+00:00",
        None,
        None,
        None,
        "{}",
    )
    d = _event_row_to_dict(row)
    assert d["time"] == "2026-01-15T09:00:00"
    assert d["valid_time"] == "2026-01-15T09:00:00"
    assert d["transaction_time"] == "2026-01-15T09:00:00+00:00"


def test_event_rows_convert_aware_datetimes_to_utc() -> None:
    """Postgres returns TIMESTAMP WITH TIME ZONE values in the session's zone; the store
    hands out UTC regardless, so the same event reads identically from any backend."""
    from datetime import timedelta, timezone

    from openngs.store.events import _event_row_to_dict

    plus_two = datetime(2026, 1, 15, 9, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    row = (
        "id",
        DEFAULT_SOURCE,
        "entity_created",
        "1.0",
        None,
        plus_two,
        None,
        plus_two,
        plus_two,
        None,
        None,
        None,
        "{}",
    )
    d = _event_row_to_dict(row)
    assert d["valid_time"] == "2026-01-15T07:00:00+00:00"


# --- corrections and retractions -----------------------------------------------


def _subject(db: Database, local_id: str) -> str:
    internal_id, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", local_id), [], NOW, NOW
    )
    return internal_id


def test_entity_correction_replaces_content_and_frees_the_old_name(db: Database) -> None:
    from openngs.store import find_by_name, record_entity_corrected, resolve_ref

    old_name = _name("subject", "SUBJ-001")
    new_name = _name("subject", "SUBJ-002")
    internal_id, created_id = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", old_name, ["barcode:A"], NOW, NOW
    )
    event_id = record_entity_corrected(
        db, DEFAULT_SOURCE, "Subject", internal_id, new_name, ["barcode:B"], NOW, NOW, "typo"
    )

    assert lookup_entity(db, internal_id) == ("Subject", new_name)
    assert find_by_name(db, "Subject", old_name) is None
    assert find_by_name(db, "Subject", new_name) == internal_id
    xrefs = db.fetchall(
        f'SELECT xrefs FROM "Subject_xrefs" WHERE "Subject_internal_id" = {db.ph(1)}',
        (internal_id,),
    )
    assert [r[0] for r in xrefs] == ["barcode:B"]  # replaced wholesale, not merged

    event = get_event(db, event_id)
    assert event is not None
    assert event["supersedes"] == created_id
    assert event["supersede_reason"] == "typo"
    # the entity is still believed - a correction is not a retraction
    assert resolve_ref(db, internal_id, ORG, NS, ("Subject",)) == ("Subject", internal_id)


def test_correction_chain_is_linear(db: Database) -> None:
    from openngs.store import latest_event_id, record_entity_corrected

    internal_id, created_id = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "A"), [], NOW, NOW
    )
    first = record_entity_corrected(
        db, DEFAULT_SOURCE, "Subject", internal_id, _name("subject", "B"), [], NOW, NOW, "one"
    )
    # the next correction supersedes the correction, not the original
    assert latest_event_id(db, internal_id) == first
    second = record_entity_corrected(
        db, DEFAULT_SOURCE, "Subject", internal_id, _name("subject", "C"), [], NOW, NOW, "two"
    )
    ev = get_event(db, second)
    assert ev is not None
    assert ev["supersedes"] == first
    assert ev["supersedes"] != created_id
    assert lookup_entity(db, internal_id) == ("Subject", _name("subject", "C"))


def test_correction_requires_a_reason(db: Database) -> None:
    from openngs.store import record_entity_corrected

    internal_id = _subject(db, "SUBJ-001")
    with pytest.raises(RepoError, match="requires a reason"):
        record_entity_corrected(
            db, DEFAULT_SOURCE, "Subject", internal_id, _name("subject", "X"), [], NOW, NOW, "  "
        )


def test_datapoint_value_correction(db: Database) -> None:
    from openngs.store import record_datapoint_corrected

    internal_id, _ = record_datapoint_created(
        db,
        DEFAULT_SOURCE,
        _name("datapoint", "DP-1"),
        [],
        "x:m",
        "number",
        12.3,
        None,
        None,
        NOW,
        NOW,
    )
    record_datapoint_corrected(
        db,
        DEFAULT_SOURCE,
        internal_id,
        _name("datapoint", "DP-1"),
        [],
        "x:m",
        "number",
        14.7,
        None,
        None,
        NOW,
        NOW,
        "re-measured",
    )
    row = get_datapoint(db, internal_id)
    assert row is not None
    assert row["value_number"] == 14.7


def test_edge_retraction_hides_it_and_frees_the_pair(db: Database) -> None:
    from openngs.store import edge_exists, get_edges, record_edge_retracted

    spec = _subject(db, "SPEC-001")
    subj = _subject(db, "SUBJ-001")
    edge_id, _ = record_edge_created(
        db, DEFAULT_SOURCE, spec, EdgePredicate.derived_from, subj, NOW, NOW
    )
    assert edge_exists(db, spec, EdgePredicate.derived_from, subj)

    record_edge_retracted(db, DEFAULT_SOURCE, edge_id, "Edge", NOW, NOW, "wrong subject")

    outgoing, _ = get_edges(db, spec, 20)
    assert outgoing == []
    assert not edge_exists(db, spec, EdgePredicate.derived_from, subj)
    # the same relationship can be asserted again after being withdrawn
    record_edge_created(db, DEFAULT_SOURCE, spec, EdgePredicate.derived_from, subj, NOW, NOW)
    assert len(get_edges(db, spec, 20)[0]) == 1
    # ...and it is still visible when explicitly asked for
    assert len(get_edges(db, spec, 20, include_retracted=True)[0]) == 2


def test_entity_retraction_refuses_live_edges_then_cascades(db: Database) -> None:
    from openngs.store import get_edges, record_entity_retracted, resolve_ref

    spec = _subject(db, "SPEC-001")
    subj = _subject(db, "SUBJ-001")
    record_edge_created(db, DEFAULT_SOURCE, spec, EdgePredicate.derived_from, subj, NOW, NOW)

    with pytest.raises(RepoError, match="live edge"):
        record_entity_retracted(db, DEFAULT_SOURCE, "Subject", subj, NOW, NOW, "duplicate")

    event_id, retracted_edges = record_entity_retracted(
        db, DEFAULT_SOURCE, "Subject", subj, NOW, NOW, "duplicate", cascade=True
    )
    assert len(retracted_edges) == 1
    assert lookup_entity(db, subj) is None
    assert lookup_entity(db, subj, include_retracted=True) == (
        "Subject",
        _name("subject", "SUBJ-001"),
    )
    assert get_edges(db, spec, 20)[0] == []
    with pytest.raises(RepoError):
        resolve_ref(db, subj, ORG, NS, ("Subject",))

    event = get_event(db, event_id)
    assert event is not None
    assert event["type"] == "entity_retracted"
    assert event["supersede_reason"] == "duplicate"


def test_facet_correction_and_retraction(db: Database) -> None:
    from openngs.store import (
        get_facet_instance,
        list_facet_instances,
        record_facet_instance_corrected,
        record_facet_instance_retracted,
    )

    entity_id = _subject(db, "SUBJ-001")
    facet_id, _ = record_facet_instance_attached(
        db,
        DEFAULT_SOURCE,
        entity_id,
        "multiqc",
        FIXTURE_SCHEMA,
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 12.3},
        NOW,
        NOW,
    )
    record_facet_instance_corrected(
        db,
        DEFAULT_SOURCE,
        facet_id,
        "QcMetricsFacet",
        {"metric_name": "percent_duplication", "metric_value": 14.7},
        NOW,
        NOW,
        "re-run",
    )
    instance = get_facet_instance(db, facet_id)
    assert instance is not None
    assert instance["data"]["metric_value"] == 14.7

    record_facet_instance_retracted(db, DEFAULT_SOURCE, facet_id, NOW, NOW, "wrong file")
    assert get_facet_instance(db, facet_id) is None
    assert get_facet_instance(db, facet_id, include_retracted=True) is not None
    assert list_facet_instances(db, entity_id, 50) == []


def test_replay_reproduces_corrections_and_retractions(db: Database) -> None:
    """The acceptance criterion invariant 1 asks for, extended to corrections: a log
    containing corrections and retractions replays to exactly the same projection."""
    from openngs.store import (
        get_edges,
        record_datapoint_corrected,
        record_entity_corrected,
        record_entity_retracted,
    )

    kept = _subject(db, "KEEP-001")
    corrected, _ = record_entity_created(
        db, DEFAULT_SOURCE, "Subject", _name("subject", "OLD"), ["a:1"], NOW, NOW
    )
    record_entity_corrected(
        db,
        DEFAULT_SOURCE,
        "Subject",
        corrected,
        _name("subject", "NEW"),
        ["a:2"],
        NOW,
        NOW,
        "typo",
    )
    doomed = _subject(db, "GONE-001")
    record_edge_created(db, DEFAULT_SOURCE, doomed, EdgePredicate.part_of, kept, NOW, NOW)
    record_entity_retracted(
        db, DEFAULT_SOURCE, "Subject", doomed, NOW, NOW, "never existed", cascade=True
    )
    dp_id, _ = record_datapoint_created(
        db,
        DEFAULT_SOURCE,
        _name("datapoint", "DP-1"),
        [],
        "x:m",
        "number",
        1.0,
        None,
        None,
        NOW,
        NOW,
    )
    record_datapoint_corrected(
        db,
        DEFAULT_SOURCE,
        dp_id,
        _name("datapoint", "DP-1"),
        [],
        "x:m",
        "number",
        2.0,
        None,
        None,
        NOW,
        NOW,
        "re-measured",
    )

    def snapshot() -> tuple:
        dp = get_datapoint(db, dp_id)
        return (
            lookup_entity(db, corrected),
            lookup_entity(db, doomed),
            lookup_entity(db, doomed, include_retracted=True),
            get_edges(db, kept, 20),
            None if dp is None else dp["value_number"],
            db.fetchall('SELECT xrefs FROM "Subject_xrefs" ORDER BY xrefs'),
        )

    before = snapshot()
    events_before = list_events(db)
    replay(db)
    assert list_events(db) == events_before
    after = snapshot()
    assert after[0] == before[0] == ("Subject", _name("subject", "NEW"))
    assert after[1] is before[1] is None
    assert after[2] == before[2]
    assert [e.edge_id for e in after[3][0]] == [e.edge_id for e in before[3][0]]
    assert [e.edge_id for e in after[3][1]] == [e.edge_id for e in before[3][1]]
    assert after[4] == before[4] == 2.0
    assert after[5] == before[5] == [("a:2",)]
