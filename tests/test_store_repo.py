"""Unit tests for the repository layer (docs/cli-design.md)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openngs.model import EdgePredicate
from openngs.store import (
    Database,
    RepoError,
    build_name,
    get_edges,
    insert_edge,
    insert_entity,
    insert_same_as_edge,
    list_entities,
    lookup_entity,
    new_id,
    resolve_ref,
)

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


def make_subject(db: Database, local_id: str) -> str:
    internal_id = new_id()
    insert_entity(db, "Subject", internal_id, build_name(ORG, NS, "Subject", local_id), [], NOW)
    return internal_id


def make_specimen(db: Database, local_id: str, subject_id: str) -> str:
    internal_id = new_id()
    insert_entity(db, "Specimen", internal_id, build_name(ORG, NS, "Specimen", local_id), [], NOW)
    insert_edge(db, internal_id, EdgePredicate.derived_from, subject_id, NOW)
    return internal_id


def test_new_id_matches_schema_pattern() -> None:
    import re

    pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
    )
    assert pattern.match(new_id())


def test_resolve_ref_by_internal_id(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    entity_type, resolved = resolve_ref(db, subject_id, ORG, NS, ("Subject",))
    assert entity_type == "Subject"
    assert resolved == subject_id


def test_resolve_ref_by_full_name(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    name = build_name(ORG, NS, "Subject", "SUBJ-001")
    entity_type, resolved = resolve_ref(db, name, ORG, NS, ("Subject",))
    assert entity_type == "Subject"
    assert resolved == subject_id


def test_resolve_ref_by_bare_local_id(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    entity_type, resolved = resolve_ref(db, "SUBJ-001", ORG, NS, ("Subject",))
    assert entity_type == "Subject"
    assert resolved == subject_id


def test_resolve_ref_not_found(db: Database) -> None:
    with pytest.raises(RepoError, match="no entity found"):
        resolve_ref(db, "NOPE", ORG, NS, ("Subject",))


def test_resolve_ref_wrong_type_via_name(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    name = build_name(ORG, NS, "Subject", "SUBJ-001")
    with pytest.raises(RepoError, match="expected one of"):
        resolve_ref(db, name, ORG, NS, ("Specimen",))
    assert subject_id  # keep referenced


def test_resolve_ref_ambiguous_local_id(db: Database) -> None:
    # Same local_id under two different entity types is ambiguous when both are candidates.
    subject_id = new_id()
    insert_entity(db, "Subject", subject_id, build_name(ORG, NS, "Subject", "X-001"), [], NOW)
    specimen_id = new_id()
    insert_entity(db, "Specimen", specimen_id, build_name(ORG, NS, "Specimen", "X-001"), [], NOW)
    with pytest.raises(RepoError, match="ambiguous"):
        resolve_ref(db, "X-001", ORG, NS, ("Subject", "Specimen"))


def test_list_entities_no_filter(db: Database) -> None:
    make_subject(db, "SUBJ-001")
    make_subject(db, "SUBJ-002")
    rows = list_entities(db, "Subject", limit=50)
    assert len(rows) == 2
    assert rows == sorted(rows, key=lambda r: r[1])  # ordered by name
    assert all(r[2] for r in rows)  # valid_time comes back on every row


def test_list_entities_with_parent_filter(db: Database) -> None:
    subject_a = make_subject(db, "SUBJ-A")
    subject_b = make_subject(db, "SUBJ-B")
    make_specimen(db, "SPEC-A1", subject_a)
    make_specimen(db, "SPEC-A2", subject_a)
    make_specimen(db, "SPEC-B1", subject_b)

    rows = list_entities(db, "Specimen", limit=50, parent=("derived_from", subject_a))
    assert len(rows) == 2
    names = {name for _, name, _ in rows}
    assert names == {
        build_name(ORG, NS, "Specimen", "SPEC-A1"),
        build_name(ORG, NS, "Specimen", "SPEC-A2"),
    }


def test_get_edges_outgoing_incoming(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    specimen_id = make_specimen(db, "SPEC-001", subject_id)

    subj_outgoing, subj_incoming = get_edges(db, subject_id, edge_limit=20)
    assert subj_outgoing == []
    assert len(subj_incoming) == 1
    assert subj_incoming[0].predicate == "derived_from"
    assert subj_incoming[0].other_id == specimen_id

    spec_outgoing, spec_incoming = get_edges(db, specimen_id, edge_limit=20)
    assert len(spec_outgoing) == 1
    assert spec_outgoing[0].predicate == "derived_from"
    assert spec_outgoing[0].other_id == subject_id
    assert spec_incoming == []


def test_get_edges_same_as(db: Database) -> None:
    subject_a = make_subject(db, "SUBJ-A")
    subject_b = make_subject(db, "SUBJ-B")
    actor_id = new_id()
    insert_entity(db, "Actor", actor_id, build_name(ORG, NS, "Actor", "ACTOR-001"), [], NOW)

    insert_same_as_edge(db, subject_a, subject_b, actor_id, "operator_claim", 0.9, NOW)

    outgoing, _ = get_edges(db, subject_a, edge_limit=20)
    assert len(outgoing) == 1
    edge = outgoing[0]
    assert edge.predicate == "same_as"
    assert edge.other_id == subject_b
    assert edge.asserted_by == actor_id
    assert edge.method == "operator_claim"
    assert edge.confidence == 0.9


def test_lookup_entity(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    resolved = lookup_entity(db, subject_id)
    assert resolved == ("Subject", build_name(ORG, NS, "Subject", "SUBJ-001"))
    assert lookup_entity(db, new_id()) is None


def test_get_edges_limit_is_oldest_first_across_both_tables(db: Database) -> None:
    """edge_limit truncates the creation-ordered sequence as a whole; it must never drop
    every same_as row just because the plain Edge rows alone filled the limit."""
    a = make_subject(db, "A")
    b = make_subject(db, "B")
    c = make_subject(db, "C")
    d = make_subject(db, "D")
    actor_id = new_id()
    insert_entity(db, "Actor", actor_id, build_name(ORG, NS, "Actor", "ACTOR-001"), [], NOW)

    first = insert_edge(db, a, EdgePredicate.part_of, b, NOW)
    second = insert_same_as_edge(db, a, c, actor_id, "operator_claim", 0.9, NOW)
    third = insert_edge(db, a, EdgePredicate.part_of, d, NOW)

    outgoing, _ = get_edges(db, a, edge_limit=2)
    assert [e.edge_id for e in outgoing] == [first, second]
    outgoing, _ = get_edges(db, a, edge_limit=20)
    assert [e.edge_id for e in outgoing] == [first, second, third]
    assert [e.predicate for e in outgoing] == ["part_of", "same_as", "part_of"]


def test_list_entities_parent_filter_is_distinct_over_duplicate_edges(db: Database) -> None:
    subject_id = make_subject(db, "SUBJ-001")
    specimen_id = make_specimen(db, "SPEC-001", subject_id)
    # A log written before record_edge_created refused duplicates can hold two identical
    # rows (insert_edge itself doesn't check - replay must apply whatever the log says).
    insert_edge(db, specimen_id, EdgePredicate.derived_from, subject_id, NOW)
    rows = list_entities(db, "Specimen", limit=50, parent=("derived_from", subject_id))
    assert len(rows) == 1


def test_list_entities_filters_by_valid_time_range(db: Database) -> None:
    """valid_time is on the row, so a date range is a WHERE clause."""
    from datetime import timedelta

    from openngs.store import insert_entity

    june = datetime(2025, 6, 15, tzinfo=UTC)
    august = datetime(2025, 8, 20, tzinfo=UTC)
    december = datetime(2025, 12, 1, tzinfo=UTC)
    for local_id, when in (("JUN", june), ("AUG", august), ("DEC", december)):
        insert_entity(db, "Specimen", new_id(), build_name(ORG, NS, "Specimen", local_id), [], when)

    def names(**kwargs: object) -> set[str]:
        rows = list_entities(db, "Specimen", limit=50, **kwargs)  # type: ignore[arg-type]
        return {n.rsplit("/", 1)[1] for _, n, _ in rows}

    assert names() == {"JUN", "AUG", "DEC"}
    assert names(valid_from=datetime(2025, 6, 1, tzinfo=UTC)) == {"JUN", "AUG", "DEC"}
    assert names(valid_to=datetime(2025, 9, 1, tzinfo=UTC)) == {"JUN", "AUG"}
    assert names(
        valid_from=datetime(2025, 6, 1, tzinfo=UTC), valid_to=datetime(2025, 9, 1, tzinfo=UTC)
    ) == {"JUN", "AUG"}
    # both bounds are inclusive
    assert names(valid_from=june, valid_to=june) == {"JUN"}
    assert names(valid_from=june + timedelta(seconds=1)) == {"AUG", "DEC"}
