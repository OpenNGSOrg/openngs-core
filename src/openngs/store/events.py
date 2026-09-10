"""The append-only event log - the source of truth invariants 1 and 2 require.

Every write path gets a `record_*` wrapper here that emits a CloudEvents-shaped row into
the Event table, then applies it to the graph projection via the same `insert_*` functions
the projection has always used - in the same transaction, so an event and its projection
row commit or roll back together. `replay` rebuilds the entire projection from the log by
calling `apply_event` for every row in order; nothing here ever mutates or deletes an
existing Event row.

Corrections and retractions are events like any other: `record_*_corrected`
replaces a row's content in place, `record_*_retracted` sets the belief marker every read
filters on. Both carry `supersedes` (the latest event about that target) and a required
`supersede_reason`, and both are applied by `apply_event` like every other event, so
`replay` reproduces corrected and retracted state without special handling.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from openngs.model import EdgePredicate, Event, EventType
from openngs.store.datapoints import insert_datapoint, update_datapoint
from openngs.store.db import Database
from openngs.store.facets import (
    SCHEMA_URI_PREFIX,
    insert_facet_instance,
    insert_facet_instance_from_store,
    register_facet_schema,
    set_facet_instance_retracted,
    update_facet_instance,
    write_facet_instance,
)
from openngs.store.repo import (
    ENTITY_TYPES,
    RepoError,
    dedupe_xrefs,
    edge_exists,
    entity_has_xref,
    insert_edge,
    insert_entity,
    insert_entity_xref,
    insert_same_as_edge,
    keyset_after,
    live_edges_touching,
    new_id,
    set_edge_retracted,
    set_entity_retracted,
    update_entity,
)

DEFAULT_SOURCE = "openngs-cli"

# Every event type apply_event knows how to materialize. Checked before anything else is
# read off the event, so an unrecognized type fails cleanly rather than on a missing key.
APPLIABLE_EVENT_TYPES: frozenset[str] = frozenset(t.value for t in EventType)


def emit_event(
    db: Database,
    source: str,
    event_type: EventType,
    subject: str | None,
    valid_time: datetime,
    transaction_time: datetime,
    payload: dict[str, Any],
    supersedes: str | None = None,
    supersede_reason: str | None = None,
) -> str:
    event = Event(
        event_id=new_id(),
        source=source,
        type=event_type,
        specversion="1.0",
        subject=subject,
        time=transaction_time,
        datacontenttype="application/json",
        valid_time=valid_time,
        transaction_time=transaction_time,
        recorded_by=db.recorded_by,
        supersedes=supersedes,
        supersede_reason=supersede_reason,
        payload=json.dumps(payload),
    )
    db.execute(
        'INSERT INTO "Event" (event_id, source, type, specversion, subject, time, '
        "datacontenttype, valid_time, transaction_time, recorded_by, supersedes, "
        f"supersede_reason, payload) VALUES ({db.ph(13)})",
        (
            event.event_id,
            event.source,
            str(event.type),
            event.specversion,
            event.subject,
            event.time.isoformat(),
            event.datacontenttype,
            event.valid_time.isoformat(),
            event.transaction_time.isoformat(),
            event.recorded_by,
            event.supersedes,
            event.supersede_reason,
            event.payload,
        ),
    )
    return str(event.event_id)


def _iso(value: Any) -> str:
    """SQLite hands back the exact ISO string emit_event wrote; Postgres/pg8000 parses its
    native TIMESTAMP WITH TIME ZONE column back into an aware datetime, in the server's
    session zone. Normalize at this boundary so every client (CLI json.dumps, REST,
    GraphQL) sees one shape - a plain ISO 8601 string, in UTC when the zone is known."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(UTC)
        return str(value.isoformat())
    return str(value)


def _event_row_to_dict(r: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "event_id": r[0],
        "source": r[1],
        "type": r[2],
        "specversion": r[3],
        "subject": r[4],
        "time": _iso(r[5]),
        "datacontenttype": r[6],
        "valid_time": _iso(r[7]),
        "transaction_time": _iso(r[8]),
        "recorded_by": r[9],
        "supersedes": r[10],
        "supersede_reason": r[11],
        "payload": json.loads(r[12]),
    }


_EVENT_COLUMNS = (
    "event_id, source, type, specversion, subject, time, datacontenttype, "
    "valid_time, transaction_time, recorded_by, supersedes, supersede_reason, payload"
)


def _event_filters(
    db: Database,
    after: str | None,
    types: Sequence[str] | None,
    source: str | None,
) -> tuple[str, list[Any]]:
    """The shared WHERE fragment for following the log: a cursor plus optional type and
    source filters. An unknown event type is rejected rather than silently matching
    nothing, for the same reason an unknown cursor is - a consumer that quietly receives
    zero events cannot tell "nothing happened" from "I asked wrongly"."""
    sql, params = keyset_after(db, "Event", "event_id", after)
    if types:
        unknown = sorted(set(types) - APPLIABLE_EVENT_TYPES)
        if unknown:
            raise RepoError(
                f"unknown event type(s) {unknown} - expected some of "
                f"{sorted(APPLIABLE_EVENT_TYPES)}"
            )
        sql += f" AND type IN ({db.ph(len(types))})"
        params += list(types)
    if source is not None:
        sql += f" AND source = {db.ph(1)}"
        params.append(source)
    return sql, params


def list_events(
    db: Database,
    limit: int | None = None,
    after: str | None = None,
    types: Sequence[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Ordered by event_id, which sorts chronologically (UUIDv7) - the log's own order.

    `after` is the event_id of the last event a consumer processed, so following the log is
    a range scan over the primary key rather than a re-read from the beginning. That, plus
    the log being append-only, is what makes polling correct: an event already returned
    never moves, and a new one only ever appears after the cursor."""
    filter_sql, filter_params = _event_filters(db, after, types, source)
    sql = f'SELECT {_EVENT_COLUMNS} FROM "Event" WHERE 1=1{filter_sql} ORDER BY event_id'
    if limit is None:
        rows = db.fetchall(sql, tuple(filter_params))
    else:
        rows = db.fetchall(sql + f" LIMIT {db.ph(1)}", (*filter_params, limit))
    return [_event_row_to_dict(r) for r in rows]


def log_tip(db: Database) -> str | None:
    """The id of the newest event, or None on an empty log.

    Used as a starting cursor by a consumer that wants only what happens from now on.
    event_id is UUIDv7, so the largest id is the most recent event.
    """
    row = db.fetchone('SELECT event_id FROM "Event" ORDER BY event_id DESC LIMIT 1', ())
    return None if row is None else str(row[0])


def get_event(db: Database, event_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        f'SELECT {_EVENT_COLUMNS} FROM "Event" WHERE event_id = {db.ph(1)}', (event_id,)
    )
    return _event_row_to_dict(row) if row is not None else None


def list_events_for_subjects(
    db: Database,
    subjects: Sequence[str],
    after: str | None = None,
    types: Sequence[str] | None = None,
    source: str | None = None,
) -> list[dict[str, Any]]:
    """Every event whose CloudEvents `subject` is one of the given ids, in event_id (creation)
    order. Used by `show --events`: an entity's own entity_created event has subject ==
    its internal_id; an edge_created/same_as_edge_created event touching it has subject ==
    that edge's edge_id - so passing [internal_id, *edge_ids already fetched for display]
    gets everything the log recorded about one node in a single query."""
    if not subjects:
        return []
    filter_sql, filter_params = _event_filters(db, after, types, source)
    sql = (
        f'SELECT {_EVENT_COLUMNS} FROM "Event" WHERE subject IN ({db.ph(len(subjects))})'
        f"{filter_sql} ORDER BY event_id"
    )
    return [_event_row_to_dict(r) for r in db.fetchall(sql, (*subjects, *filter_params))]


# --- record_* : emit + apply, for the live write path -----------------------------------


def record_entity_created(
    db: Database,
    source: str,
    entity_type: str,
    name: str,
    xrefs: list[str],
    valid_time: datetime,
    transaction_time: datetime,
    internal_id: str | None = None,
) -> tuple[str, str]:
    """Returns (internal_id, event_id). Not for DataPoint - see record_datapoint_created.
    internal_id lets a caller that already generated and Pydantic-validated an id (the CLI
    does, before writing) supply it rather than getting a second one generated here."""
    internal_id = internal_id or new_id()
    payload = {
        "entity_type": entity_type,
        "internal_id": internal_id,
        "name": name,
        "xrefs": dedupe_xrefs(xrefs),
    }
    event_id = emit_event(
        db, source, EventType.entity_created, internal_id, valid_time, transaction_time, payload
    )
    insert_entity(db, entity_type, internal_id, name, xrefs, valid_time)
    return internal_id, event_id


def record_datapoint_created(
    db: Database,
    source: str,
    name: str,
    xrefs: list[str],
    datapoint_type: str,
    value_kind: str,
    value_number: float | None,
    value_text: str | None,
    value_boolean: bool | None,
    valid_time: datetime,
    transaction_time: datetime,
    internal_id: str | None = None,
) -> tuple[str, str]:
    """Returns (internal_id, event_id). DataPoint is an entity_created event too (ADR
    0013) - just with the extra value_* fields insert_entity() alone can't handle."""
    internal_id = internal_id or new_id()
    payload = {
        "entity_type": "DataPoint",
        "internal_id": internal_id,
        "name": name,
        "xrefs": dedupe_xrefs(xrefs),
        "datapoint_type": datapoint_type,
        "value_kind": value_kind,
        "value_number": value_number,
        "value_text": value_text,
        "value_boolean": value_boolean,
    }
    event_id = emit_event(
        db, source, EventType.entity_created, internal_id, valid_time, transaction_time, payload
    )
    insert_datapoint(
        db,
        internal_id,
        name,
        xrefs,
        datapoint_type,
        value_kind,
        value_number,
        value_text,
        value_boolean,
        valid_time,
    )
    return internal_id, event_id


def record_edge_created(
    db: Database,
    source: str,
    subject: str,
    predicate: EdgePredicate,
    obj: str,
    valid_time: datetime,
    transaction_time: datetime,
) -> tuple[str, str]:
    """Returns (edge_id, event_id). Refuses a self-loop and an exact duplicate of an
    existing edge (see edge_exists) - both are live-write guardrails only; replay applies
    whatever the log holds via insert_edge directly."""
    if subject == obj:
        raise RepoError(f"an entity cannot be {predicate.value} itself ({subject})")
    if edge_exists(db, subject, predicate, obj):
        raise RepoError(f"edge already exists: {subject} {predicate.value} {obj}")
    edge_id = insert_edge(db, subject, predicate, obj, valid_time)
    # predicate is a raw EdgePredicate here, not a Pydantic model attribute - str() on a
    # bare (str, Enum) member gives "EdgePredicate.derived_from" in Python 3.11+, not the
    # value, unlike edge.predicate accessed off a constructed Edge (Pydantic coerces that
    # to a plain str). Use .value explicitly.
    payload = {
        "edge_id": edge_id,
        "subject": subject,
        "predicate": predicate.value,
        "object": obj,
    }
    event_id = emit_event(
        db, source, EventType.edge_created, edge_id, valid_time, transaction_time, payload
    )
    return edge_id, event_id


def record_same_as_edge_created(
    db: Database,
    source: str,
    subject: str,
    obj: str,
    asserted_by: str,
    method: str,
    confidence: float,
    valid_time: datetime,
    transaction_time: datetime,
) -> tuple[str, str]:
    """Returns (edge_id, event_id). asserted_at is valid_time - when the assertion was
    made in the lab (invariant 2), not when OpenNGS heard about it; that's the event's
    transaction_time. A self-loop is refused: an entity is trivially itself."""
    if subject == obj:
        raise RepoError(f"an entity cannot be same_as itself ({subject})")
    asserted_at = valid_time
    edge_id = insert_same_as_edge(
        db, subject, obj, asserted_by, method, confidence, valid_time, asserted_at=asserted_at
    )
    payload = {
        "edge_id": edge_id,
        "subject": subject,
        "object": obj,
        "asserted_by": asserted_by,
        "asserted_at": asserted_at.isoformat(),
        "method": method,
        "confidence": confidence,
    }
    event_id = emit_event(
        db, source, EventType.same_as_edge_created, edge_id, valid_time, transaction_time, payload
    )
    return edge_id, event_id


def record_facet_instance_attached(
    db: Database,
    source: str,
    attached_to: str,
    producer: str,
    schema_url: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    transaction_time: datetime,
) -> tuple[str, str]:
    """Returns (facet_id, event_id). --schema-url path."""
    facet_id = insert_facet_instance(
        db, attached_to, producer, schema_url, facet_type, data, valid_time
    )
    payload = {
        "facet_id": facet_id,
        "attached_to": attached_to,
        "producer": producer,
        "facet_type": facet_type,
        "data": data,
        "schema_mode": "url",
        "schema_url": schema_url,
    }
    event_id = emit_event(
        db,
        source,
        EventType.facet_instance_attached,
        facet_id,
        valid_time,
        transaction_time,
        payload,
    )
    return facet_id, event_id


def record_facet_instance_attached_from_store(
    db: Database,
    source: str,
    attached_to: str,
    producer: str,
    schema_id: str,
    json_schema_text: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    transaction_time: datetime,
) -> tuple[str, str]:
    """Returns (facet_id, event_id). --schema-id path - the payload records only
    schema_id, not the schema text: the instance's _schemaURL pins that schema_id, and
    replay reinstates the instance without re-validating (see apply_event), so the text
    never needs duplicating into every instance event."""
    facet_id = insert_facet_instance_from_store(
        db, attached_to, producer, schema_id, json_schema_text, facet_type, data, valid_time
    )
    payload = {
        "facet_id": facet_id,
        "attached_to": attached_to,
        "producer": producer,
        "facet_type": facet_type,
        "data": data,
        "schema_mode": "store",
        "schema_id": schema_id,
    }
    event_id = emit_event(
        db,
        source,
        EventType.facet_instance_attached,
        facet_id,
        valid_time,
        transaction_time,
        payload,
    )
    return facet_id, event_id


def record_facet_schema_registered(
    db: Database,
    source: str,
    schema_name: str,
    json_schema_text: str,
    valid_time: datetime,
    transaction_time: datetime,
) -> tuple[str, str]:
    """Returns (schema_id, event_id)."""
    schema_id = register_facet_schema(db, schema_name, json_schema_text)
    payload = {
        "schema_id": schema_id,
        "schema_name": schema_name,
        "json_schema": json.loads(json_schema_text),
    }
    event_id = emit_event(
        db,
        source,
        EventType.facet_schema_registered,
        schema_id,
        valid_time,
        transaction_time,
        payload,
    )
    return schema_id, event_id


def record_entity_xref_added(
    db: Database,
    source: str,
    entity_type: str,
    internal_id: str,
    xref: str,
    valid_time: datetime,
    transaction_time: datetime,
) -> str:
    """Add one external identifier to an existing entity. Returns the event_id.

    Additive, so it carries no `supersedes`: an accession arriving weeks after submission
    does not mean anything previously recorded was wrong. Removing an xref is a different
    operation and is a correction (`correct --xref`/`--clear-xrefs`).

    An xref the entity already has is refused rather than silently ignored, the same call
    record_edge_created makes for a duplicate edge: re-asserting an existing fact adds
    nothing, and quietly accepting it would put a no-op event in the log."""
    if entity_has_xref(db, entity_type, internal_id, xref):
        raise RepoError(f"{entity_type} {internal_id} already has xref {xref!r}")
    event_id = emit_event(
        db,
        source,
        EventType.entity_xref_added,
        internal_id,
        valid_time,
        transaction_time,
        {"entity_type": entity_type, "internal_id": internal_id, "xref": xref},
    )
    insert_entity_xref(db, entity_type, internal_id, xref)
    return event_id


# --- corrections and retractions ----------------------------------------------


def latest_event_id(db: Database, subject: str) -> str:
    """The event a correction or retraction of `subject` must supersede: the most recent
    event about it that nothing has superseded yet.

    Corrections form a linear chain - superseding an already-superseded event is
    refused, so a record's history is one unambiguous line and replay never has to arbitrate
    between competing corrections. Callers never pass an event_id themselves; they pass a
    REF and this finds it."""
    row = db.fetchone(
        'SELECT event_id FROM "Event" e WHERE e.subject = ' + db.ph(1) + " "
        'AND NOT EXISTS (SELECT 1 FROM "Event" s WHERE s.supersedes = e.event_id) '
        "ORDER BY event_id DESC LIMIT 1",
        (subject,),
    )
    if row is None:
        raise RepoError(
            f"nothing in the event log concerns {subject!r}, so there is nothing to "
            "correct or retract"
        )
    return str(row[0])


def _require_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise RepoError("a correction or retraction requires a reason")
    return reason


def record_entity_corrected(
    db: Database,
    source: str,
    entity_type: str,
    internal_id: str,
    name: str,
    xrefs: list[str],
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
) -> str:
    """Replace a non-DataPoint entity's name/xrefs. Returns the correcting event_id."""
    _require_reason(reason)
    payload = {
        "entity_type": entity_type,
        "internal_id": internal_id,
        "name": name,
        "xrefs": dedupe_xrefs(xrefs),
    }
    event_id = emit_event(
        db,
        source,
        EventType.entity_corrected,
        internal_id,
        valid_time,
        transaction_time,
        payload,
        supersedes=latest_event_id(db, internal_id),
        supersede_reason=reason,
    )
    update_entity(db, entity_type, internal_id, name, xrefs, valid_time)
    return event_id


def record_datapoint_corrected(
    db: Database,
    source: str,
    internal_id: str,
    name: str,
    xrefs: list[str],
    datapoint_type: str,
    value_kind: str,
    value_number: float | None,
    value_text: str | None,
    value_boolean: bool | None,
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
) -> str:
    """A DataPoint's whole reason to exist is its value, so it corrects like every other
    entity but with the value_* fields in the payload too (the same split
    record_datapoint_created already has against record_entity_created)."""
    _require_reason(reason)
    payload = {
        "entity_type": "DataPoint",
        "internal_id": internal_id,
        "name": name,
        "xrefs": dedupe_xrefs(xrefs),
        "datapoint_type": datapoint_type,
        "value_kind": value_kind,
        "value_number": value_number,
        "value_text": value_text,
        "value_boolean": value_boolean,
    }
    event_id = emit_event(
        db,
        source,
        EventType.entity_corrected,
        internal_id,
        valid_time,
        transaction_time,
        payload,
        supersedes=latest_event_id(db, internal_id),
        supersede_reason=reason,
    )
    update_datapoint(
        db,
        internal_id,
        name,
        xrefs,
        datapoint_type,
        value_kind,
        value_number,
        value_text,
        value_boolean,
        valid_time,
    )
    return event_id


def record_edge_retracted(
    db: Database,
    source: str,
    edge_id: str,
    table: str,
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
) -> str:
    """Withdraw one edge. `table` is "Edge" or "SameAsEdge" - the two live in separate
    tables and get separate event types, mirroring their separate creation
    types."""
    _require_reason(reason)
    event_type = EventType.edge_retracted if table == "Edge" else EventType.same_as_edge_retracted
    event_id = emit_event(
        db,
        source,
        event_type,
        edge_id,
        valid_time,
        transaction_time,
        {"edge_id": edge_id},
        supersedes=latest_event_id(db, edge_id),
        supersede_reason=reason,
    )
    set_edge_retracted(db, table, edge_id, transaction_time, event_id)
    return event_id


def record_entity_retracted(
    db: Database,
    source: str,
    entity_type: str,
    internal_id: str,
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
    cascade: bool = False,
) -> tuple[str, list[str]]:
    """Withdraw an entity. Returns (event_id, retracted_edge_ids).

    An entity with live edges is refused unless `cascade`: one command silently
    removing a subtree of lineage is exactly what this project avoids elsewhere. Cascade
    retracts those edges, each as its own event so the log records every individual fact
    that stopped being believed - and only edges, never another entity, so it cannot run
    away down the graph."""
    _require_reason(reason)
    edges = live_edges_touching(db, internal_id)
    if edges and not cascade:
        raise RepoError(
            f"{internal_id} still has {len(edges)} live edge(s); retract them first, or "
            "pass --cascade to retract them with it"
        )
    retracted_edges = []
    for table, edge_id in edges:
        record_edge_retracted(db, source, edge_id, table, valid_time, transaction_time, reason)
        retracted_edges.append(edge_id)
    event_id = emit_event(
        db,
        source,
        EventType.entity_retracted,
        internal_id,
        valid_time,
        transaction_time,
        {"entity_type": entity_type, "internal_id": internal_id},
        supersedes=latest_event_id(db, internal_id),
        supersede_reason=reason,
    )
    set_entity_retracted(db, entity_type, internal_id, transaction_time, event_id)
    return event_id, retracted_edges


def record_facet_instance_corrected(
    db: Database,
    source: str,
    facet_id: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
) -> str:
    """Replace a facet instance's data, keeping its facet_id and its _schemaURL. The caller
    validates against that schema first, the same as on attach."""
    _require_reason(reason)
    event_id = emit_event(
        db,
        source,
        EventType.facet_instance_corrected,
        facet_id,
        valid_time,
        transaction_time,
        {"facet_id": facet_id, "facet_type": facet_type, "data": data},
        supersedes=latest_event_id(db, facet_id),
        supersede_reason=reason,
    )
    update_facet_instance(db, facet_id, facet_type, data, valid_time)
    return event_id


def record_facet_instance_retracted(
    db: Database,
    source: str,
    facet_id: str,
    valid_time: datetime,
    transaction_time: datetime,
    reason: str,
) -> str:
    _require_reason(reason)
    event_id = emit_event(
        db,
        source,
        EventType.facet_instance_retracted,
        facet_id,
        valid_time,
        transaction_time,
        {"facet_id": facet_id},
        supersedes=latest_event_id(db, facet_id),
        supersede_reason=reason,
    )
    set_facet_instance_retracted(db, facet_id, transaction_time, event_id)
    return event_id


# --- apply_event / replay : rebuild the projection from the log -------------------------


def apply_event(db: Database, event: dict[str, Any]) -> None:
    """Materialize one event into the graph projection. Used by replay(); never called
    without also being safe to call standalone against an already-populated projection,
    since every insert_* it delegates to takes an explicit id (idempotent id-wise, though
    not idempotent against re-application - replay always starts from an empty projection)."""
    t = event["type"]
    if t not in APPLIABLE_EVENT_TYPES:
        raise RepoError(f"replay: unknown event type {t!r}, cannot apply")
    p = event["payload"]
    # Both times come off the event, never the wall clock: replaying the same log twice has
    # to produce byte-identical projection rows.
    vt = datetime.fromisoformat(event["valid_time"])
    tt = datetime.fromisoformat(event["transaction_time"])
    if t == "entity_created":
        if p["entity_type"] == "DataPoint":
            insert_datapoint(
                db,
                p["internal_id"],
                p["name"],
                p["xrefs"],
                p["datapoint_type"],
                p["value_kind"],
                p["value_number"],
                p["value_text"],
                p["value_boolean"],
                vt,
            )
        else:
            insert_entity(db, p["entity_type"], p["internal_id"], p["name"], p["xrefs"], vt)
    elif t == "entity_corrected":
        if p["entity_type"] == "DataPoint":
            update_datapoint(
                db,
                p["internal_id"],
                p["name"],
                p["xrefs"],
                p["datapoint_type"],
                p["value_kind"],
                p["value_number"],
                p["value_text"],
                p["value_boolean"],
                vt,
            )
        else:
            update_entity(db, p["entity_type"], p["internal_id"], p["name"], p["xrefs"], vt)
    elif t == "entity_xref_added":
        insert_entity_xref(db, p["entity_type"], p["internal_id"], p["xref"])
    elif t == "entity_retracted":
        set_entity_retracted(db, p["entity_type"], p["internal_id"], tt, event["event_id"])
    elif t == "edge_created":
        insert_edge(
            db,
            p["subject"],
            EdgePredicate(p["predicate"]),
            p["object"],
            vt,
            edge_id=p["edge_id"],
        )
    elif t == "edge_retracted":
        set_edge_retracted(db, "Edge", p["edge_id"], tt, event["event_id"])
    elif t == "same_as_edge_created":
        insert_same_as_edge(
            db,
            p["subject"],
            p["object"],
            p["asserted_by"],
            p["method"],
            p["confidence"],
            vt,
            edge_id=p["edge_id"],
            asserted_at=datetime.fromisoformat(p["asserted_at"]),
        )
    elif t == "same_as_edge_retracted":
        set_edge_retracted(db, "SameAsEdge", p["edge_id"], tt, event["event_id"])
    elif t == "facet_instance_attached":
        # No re-validation on replay, in either schema mode: the data was validated when
        # the event was recorded, and the log is the source of truth. Re-validating the
        # "url" mode would make replay fail (or silently validate against something else)
        # whenever the local schema file has since moved or changed; re-validating the
        # "store" mode is merely redundant. Same _schemaURL either way as the live write.
        if p["schema_mode"] == "url":
            schema_url = p["schema_url"]
        else:
            schema_url = f"{SCHEMA_URI_PREFIX}{p['schema_id']}"
        write_facet_instance(
            db,
            p["attached_to"],
            p["producer"],
            schema_url,
            p["facet_type"],
            p["data"],
            vt,
            facet_id=p["facet_id"],
        )
    elif t == "facet_instance_corrected":
        update_facet_instance(db, p["facet_id"], p["facet_type"], p["data"], vt)
    elif t == "facet_instance_retracted":
        set_facet_instance_retracted(db, p["facet_id"], tt, event["event_id"])
    elif t == "facet_schema_registered":
        register_facet_schema(
            db, p["schema_name"], json.dumps(p["json_schema"]), schema_id=p["schema_id"]
        )


def replay(db: Database) -> int:
    """Truncate every projection table and rebuild it from the event log, in event_id
    order. Never touches the Event table itself - the log is never mutated, only the
    derived projection. Returns the number of events applied."""
    for entity_type in ENTITY_TYPES:
        db.execute(f'DELETE FROM "{entity_type}_xrefs"')
    for entity_type in ENTITY_TYPES:
        db.execute(f'DELETE FROM "{entity_type}"')
    for table in ("SameAsEdge", "Edge", "FacetInstance", "FacetSchema"):
        db.execute(f'DELETE FROM "{table}"')

    events = list_events(db)
    for event in events:
        apply_event(db, event)
    return len(events)
