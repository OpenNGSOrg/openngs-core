"""DataPoint storage: an atomic, independently-correctable fact, with its value
held directly in typed columns instead of routed through the generic facet framework.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from openngs.model import DataPoint
from openngs.store.db import Database
from openngs.store.repo import (
    NameTakenError,
    RepoError,
    believed,
    dedupe_xrefs,
    iso_timestamp,
    keyset_after,
    valid_time_range,
)

VALUE_KINDS: tuple[str, ...] = ("number", "text", "boolean")


def parse_value(value_kind: str, raw: str) -> tuple[float | None, str | None, bool | None]:
    """Returns (value_number, value_text, value_boolean) - exactly one non-None."""
    if value_kind == "number":
        try:
            return float(raw), None, None
        except ValueError as exc:
            raise RepoError(f"--value {raw!r} is not a valid number") from exc
    if value_kind == "text":
        return None, raw, None
    if value_kind == "boolean":
        lowered = raw.strip().lower()
        if lowered in ("true", "1", "yes"):
            return None, None, True
        if lowered in ("false", "0", "no"):
            return None, None, False
        raise RepoError(f"--value {raw!r} is not a valid boolean (true/false)")
    raise RepoError(f"--kind must be one of {VALUE_KINDS}, got {value_kind!r}")


def datapoint_value(row: dict[str, Any]) -> Any:
    return {
        "number": row["value_number"],
        "text": row["value_text"],
        "boolean": row["value_boolean"],
    }[row["value_kind"]]


def insert_datapoint(
    db: Database,
    internal_id: str,
    name: str,
    xrefs: list[str],
    datapoint_type: str,
    value_kind: str,
    value_number: float | None,
    value_text: str | None,
    value_boolean: bool | None,
    valid_time: datetime,
) -> DataPoint:
    obj = DataPoint(
        internal_id=internal_id,
        name=name,
        xrefs=dedupe_xrefs(xrefs),
        datapoint_type=datapoint_type,
        value_kind=value_kind,
        value_number=value_number,
        value_text=value_text,
        value_boolean=value_boolean,
        valid_time=valid_time,
    )
    try:
        db.execute(
            'INSERT INTO "DataPoint" '
            "(internal_id, name, datapoint_type, value_kind, value_number, value_text, "
            f"value_boolean, valid_time) VALUES ({db.ph(8)})",
            (
                obj.internal_id,
                obj.name,
                obj.datapoint_type,
                str(obj.value_kind),
                obj.value_number,
                obj.value_text,
                obj.value_boolean,
                valid_time.isoformat(),
            ),
        )
    except Exception as exc:
        if not db.is_unique_violation(exc):
            raise
        raise NameTakenError(f"a DataPoint named {name!r} already exists") from exc
    for xref in obj.xrefs:
        db.execute(
            f'INSERT INTO "DataPoint_xrefs" ("DataPoint_internal_id", xrefs) VALUES ({db.ph(2)})',
            (obj.internal_id, xref),
        )
    return obj


def update_datapoint(
    db: Database,
    internal_id: str,
    name: str,
    xrefs: list[str],
    datapoint_type: str,
    value_kind: str,
    value_number: float | None,
    value_text: str | None,
    value_boolean: bool | None,
    valid_time: datetime,
) -> None:
    """Replace a DataPoint's correctable content in place - the whole point of
    the entity is its value, and a re-measured or mis-transcribed value is the archetypal
    independently-correctable fact."""
    ph = db.ph(1)
    db.execute(
        f'UPDATE "DataPoint" SET name = {ph}, datapoint_type = {ph}, value_kind = {ph}, '
        f"value_number = {ph}, value_text = {ph}, value_boolean = {ph}, valid_time = {ph} "
        f"WHERE internal_id = {ph}",
        (
            name,
            datapoint_type,
            value_kind,
            value_number,
            value_text,
            value_boolean,
            valid_time.isoformat(),
            internal_id,
        ),
    )
    db.execute(
        f'DELETE FROM "DataPoint_xrefs" WHERE "DataPoint_internal_id" = {db.ph(1)}',
        (internal_id,),
    )
    for xref in dedupe_xrefs(xrefs):
        db.execute(
            f'INSERT INTO "DataPoint_xrefs" ("DataPoint_internal_id", xrefs) VALUES ({db.ph(2)})',
            (internal_id, xref),
        )


def _row_to_dict(r: tuple[Any, ...]) -> dict[str, Any]:
    # SQLite has no native boolean type - a stored True/False round-trips as 1/0 through
    # the raw DB-API cursor, so coerce it back explicitly rather than displaying 0/1.
    return {
        "internal_id": r[0],
        "name": r[1],
        "datapoint_type": r[2],
        "value_kind": r[3],
        "value_number": r[4],
        "value_text": r[5],
        "value_boolean": None if r[6] is None else bool(r[6]),
        "valid_time": iso_timestamp(r[7]),
    }


def get_datapoint(
    db: Database, internal_id: str, include_retracted: bool = False
) -> dict[str, Any] | None:
    row = db.fetchone(
        "SELECT internal_id, name, datapoint_type, value_kind, value_number, value_text, "
        f'value_boolean, valid_time FROM "DataPoint" WHERE internal_id = {db.ph(1)}'
        f"{believed(include_retracted)}",
        (internal_id,),
    )
    if row is None:
        return None
    return _row_to_dict(row)


def list_datapoints(
    db: Database,
    characterizes: str | None,
    limit: int,
    include_retracted: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    after: str | None = None,
) -> list[dict[str, Any]]:
    """characterizes, if given, filters to DataPoints with a `characterizes` edge to that
    internal_id (the entity they describe). A retracted edge never joins, so a DataPoint
    whose characterizes edge was withdrawn stops being listed for that entity."""
    columns = (
        "internal_id, name, datapoint_type, value_kind, value_number, value_text, "
        "value_boolean, valid_time"
    )
    after_sql, after_params = keyset_after(
        db, "DataPoint", "internal_id", after, "name", alias="d" if characterizes else ""
    )
    if characterizes is None:
        range_sql, range_params = valid_time_range(db, valid_from, valid_to)
        rows = db.fetchall(
            f'SELECT {columns} FROM "DataPoint" WHERE 1=1'
            f"{believed(include_retracted)}{range_sql}{after_sql} "
            f"ORDER BY name, internal_id LIMIT {db.ph(1)}",
            (*range_params, *after_params, limit),
        )
    else:
        filt = "" if include_retracted else " AND d.retracted_at IS NULL"
        range_sql, range_params = valid_time_range(db, valid_from, valid_to, "d.valid_time")
        rows = db.fetchall(
            f"SELECT d.{', d.'.join(columns.split(', '))} "
            'FROM "DataPoint" d JOIN "Edge" e ON e.edge_subject = d.internal_id '
            "AND e.retracted_at IS NULL "
            f"WHERE e.predicate = {db.ph(1)} AND e.object = {db.ph(1)}{filt}{range_sql}"
            f"{after_sql} ORDER BY d.name, d.internal_id LIMIT {db.ph(1)}",
            ("characterizes", characterizes, *range_params, *after_params, limit),
        )
    return [_row_to_dict(r) for r in rows]
