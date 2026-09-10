"""Unit tests for DataPoint storage."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openngs.store import (
    Database,
    RepoError,
    datapoint_value,
    get_datapoint,
    insert_datapoint,
    list_datapoints,
    new_id,
    parse_value,
)

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


def test_parse_value_number() -> None:
    assert parse_value("number", "12.3") == (12.3, None, None)


def test_parse_value_text() -> None:
    assert parse_value("text", "PASS") == (None, "PASS", None)


def test_parse_value_boolean_true_variants() -> None:
    for raw in ("true", "True", "1", "yes"):
        assert parse_value("boolean", raw) == (None, None, True)


def test_parse_value_boolean_false_variants() -> None:
    for raw in ("false", "False", "0", "no"):
        assert parse_value("boolean", raw) == (None, None, False)


def test_parse_value_bad_number() -> None:
    with pytest.raises(RepoError, match="not a valid number"):
        parse_value("number", "nope")


def test_parse_value_bad_boolean() -> None:
    with pytest.raises(RepoError, match="not a valid boolean"):
        parse_value("boolean", "maybe")


def test_parse_value_bad_kind() -> None:
    with pytest.raises(RepoError, match="must be one of"):
        parse_value("weird", "1")


def test_insert_and_get_datapoint_number(db: Database) -> None:
    internal_id = new_id()
    obj = insert_datapoint(
        db,
        internal_id,
        "openngs://acme/core/datapoint/DP-001",
        [],
        "openngs-dp:percent_duplication",
        "number",
        12.3,
        None,
        None,
        NOW,
    )
    assert obj.internal_id == internal_id
    row = get_datapoint(db, internal_id)
    assert row is not None
    assert row["datapoint_type"] == "openngs-dp:percent_duplication"
    assert row["value_kind"] == "number"
    assert datapoint_value(row) == 12.3


def test_insert_and_get_datapoint_boolean_round_trips_as_bool(db: Database) -> None:
    internal_id = new_id()
    insert_datapoint(
        db,
        internal_id,
        "openngs://acme/core/datapoint/DP-002",
        [],
        "acme:flagged",
        "boolean",
        None,
        None,
        True,
        NOW,
    )
    row = get_datapoint(db, internal_id)
    assert row is not None
    assert row["value_boolean"] is True  # not 1 - see _row_to_dict's SQLite coercion
    assert datapoint_value(row) is True


def test_get_datapoint_not_found(db: Database) -> None:
    assert get_datapoint(db, "018f5b2a-0000-7000-8000-999999999999") is None


def test_list_datapoints_filters_by_characterizes(db: Database) -> None:
    from openngs.model import EdgePredicate
    from openngs.store import insert_edge

    dp_a1 = new_id()
    dp_a2 = new_id()
    dp_b1 = new_id()
    insert_datapoint(
        db,
        dp_a1,
        "openngs://acme/core/datapoint/A1",
        [],
        "x:m",
        "number",
        1.0,
        None,
        None,
        NOW,
    )
    insert_datapoint(
        db,
        dp_a2,
        "openngs://acme/core/datapoint/A2",
        [],
        "x:m",
        "number",
        2.0,
        None,
        None,
        NOW,
    )
    insert_datapoint(
        db,
        dp_b1,
        "openngs://acme/core/datapoint/B1",
        [],
        "x:m",
        "number",
        3.0,
        None,
        None,
        NOW,
    )
    insert_edge(db, dp_a1, EdgePredicate.characterizes, "entity-a", NOW)
    insert_edge(db, dp_a2, EdgePredicate.characterizes, "entity-a", NOW)
    insert_edge(db, dp_b1, EdgePredicate.characterizes, "entity-b", NOW)

    assert len(list_datapoints(db, "entity-a", limit=50)) == 2
    assert len(list_datapoints(db, "entity-b", limit=50)) == 1
    assert len(list_datapoints(db, None, limit=50)) == 3
    assert len(list_datapoints(db, "entity-a", limit=1)) == 1
