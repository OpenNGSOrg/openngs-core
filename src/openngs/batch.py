"""Applying several write operations as one unit.

Shared by `POST /batch` (docs/api-design.md) and `openngs ingest manifest`
(docs/manifest.md): a manifest is parsed into these operations and applied by the same
code, so the loader is a client of the existing write path rather than a second one.

Nothing here opens a transaction or commits. The caller supplies a `Database` and owns its
lifecycle, which is what makes "all of them or none" true: an exception propagates out to
the caller's `with` block and rolls everything back.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from openngs.entities import (
    ENTITIES_BY_CLI_NAME,
    ENTITIES_BY_TYPE,
    LINK_SOURCE_TYPES,
    LINK_TARGET_TYPES,
)
from openngs.model.generated import EdgePredicate
from openngs.store import (
    ENTITY_TYPES,
    Database,
    NameTakenError,
    RepoError,
    build_name,
    build_schema_name,
    edge_exists,
    find_by_name,
    find_edge,
    get_datapoint,
    new_id,
    parse_value,
    record_datapoint_created,
    record_edge_created,
    record_entity_created,
    record_facet_instance_attached,
    record_facet_instance_attached_from_store,
    record_facet_schema_registered,
    record_same_as_edge_created,
    resolve_attachment_ref,
    resolve_facet_schema_ref,
    resolve_ref,
)


class BatchShapeError(RepoError):
    """An operation is malformed - a missing or contradictory field, not a bad reference.

    Separate from a plain RepoError so HTTP can answer 422 rather than 400: the request
    could not be understood, as opposed to naming something that does not exist.
    """


def _resolve_times(valid_time: datetime | None) -> tuple[datetime, datetime]:
    transaction_time = datetime.now(UTC)
    if valid_time is None:
        return transaction_time, transaction_time
    if valid_time.tzinfo is None:
        return valid_time.replace(tzinfo=UTC), transaction_time
    return valid_time.astimezone(UTC), transaction_time


class BatchOperation(BaseModel):
    """One operation in a batch. The fields are named after the individual routes' own
    bodies, except that `type` is spelled out per operation (`entity_type`, `facet_type`,
    `datapoint_type`) because the three mean different things."""

    op: Literal["create", "link", "attach_facet", "create_datapoint", "register_schema"]

    # create
    entity_type: str | None = Field(None, description="Entity noun, e.g. 'specimen'")
    parent: str | None = Field(None, description="REF for this entity's required parent")
    no_parent: bool = False
    derived_from: list[str] = Field(default_factory=list)

    # create / create_datapoint / register_schema
    local_id: str | None = None
    xrefs: list[str] = Field(default_factory=list)

    # link
    predicate: str | None = None
    from_: str | None = Field(None, alias="from")
    to: str | None = None
    asserted_by: str | None = None
    method: str | None = None
    confidence: float | None = None

    # attach_facet
    schema_url: str | None = None
    schema_id: str | None = None
    facet_type: str | None = None
    producer: str | None = None
    data: dict[str, Any] | None = None

    # create_datapoint
    for_: str | None = Field(None, alias="for")
    datapoint_type: str | None = None
    kind: str | None = None
    value: str | None = None

    # register_schema
    json_schema: dict[str, Any] | None = None

    if_exists: str = Field(
        "error",
        description="'error' or 'return'. On 'return' a create or link that already exists "
        "is reused instead of failing, which is what makes a retried batch safe.",
    )
    valid_time: datetime | None = None


def _require(op: BatchOperation, *fields: str) -> None:
    missing = [f for f in fields if getattr(op, f, None) in (None, "")]
    if missing:
        raise BatchShapeError(f"missing {', '.join(sorted(missing))}")


def apply_operation(
    db: Database, org: str, ns: str, source: str, op: BatchOperation
) -> dict[str, Any]:
    vt, tt = _resolve_times(op.valid_time)
    if op.op == "create":
        _require(op, "entity_type", "local_id")
        assert op.entity_type is not None and op.local_id is not None
        cfg = ENTITIES_BY_CLI_NAME.get(op.entity_type) or ENTITIES_BY_TYPE.get(op.entity_type)
        if cfg is None:
            raise BatchShapeError(f"unknown entity type {op.entity_type!r}")
        if cfg.parent is not None and not op.no_parent and op.parent is None:
            raise BatchShapeError(f"{cfg.cli_name} needs 'parent' or no_parent=true")
        name = build_name(org, ns, cfg.type_name, op.local_id)
        parent_id = None
        if cfg.parent is not None and op.parent is not None:
            _, parent_id = resolve_ref(db, op.parent, org, ns, cfg.parent.target_types)
        if op.if_exists == "return":
            existing = find_by_name(db, cfg.type_name, name)
            if existing is not None:
                # A name collision with a different parent is a data problem, not a repeat.
                if (
                    cfg.parent is not None
                    and parent_id is not None
                    and not edge_exists(
                        db, existing, EdgePredicate(cfg.parent.predicate), parent_id
                    )
                ):
                    raise NameTakenError(f"{name!r} already exists with a different parent")
                return {
                    "op": op.op,
                    "type": cfg.type_name,
                    "internal_id": existing,
                    "name": name,
                    "created": False,
                }
        derived = [resolve_ref(db, r, org, ns, ENTITY_TYPES)[1] for r in op.derived_from]
        internal_id = new_id()
        cfg.model(internal_id=internal_id, name=name, xrefs=list(op.xrefs), valid_time=vt)
        record_entity_created(
            db, source, cfg.type_name, name, list(op.xrefs), vt, tt, internal_id=internal_id
        )
        if parent_id is not None:
            assert cfg.parent is not None
            record_edge_created(
                db, source, internal_id, EdgePredicate(cfg.parent.predicate), parent_id, vt, tt
            )
        for other in dict.fromkeys(derived):
            record_edge_created(db, source, internal_id, EdgePredicate.derived_from, other, vt, tt)
        return {
            "op": op.op,
            "type": cfg.type_name,
            "internal_id": internal_id,
            "name": name,
            "created": True,
        }

    if op.op == "link":
        _require(op, "predicate", "from_", "to")
        assert op.predicate is not None and op.from_ is not None and op.to is not None
        if op.predicate not in LINK_TARGET_TYPES and op.predicate != "same_as":
            raise BatchShapeError(f"unknown predicate {op.predicate!r}")
        if op.predicate == "same_as":
            _require(op, "asserted_by", "method", "confidence")
            assert op.asserted_by is not None and op.method is not None
            assert op.confidence is not None
            _, from_id = resolve_ref(db, op.from_, org, ns, ENTITY_TYPES)
            _, to_id = resolve_ref(db, op.to, org, ns, ENTITY_TYPES)
            _, actor_id = resolve_ref(db, op.asserted_by, org, ns, ("Actor",))
            edge_id, _ = record_same_as_edge_created(
                db, source, from_id, to_id, actor_id, op.method, op.confidence, vt, tt
            )
        else:
            _, from_id = resolve_ref(db, op.from_, org, ns, LINK_SOURCE_TYPES[op.predicate])
            _, to_id = resolve_ref(db, op.to, org, ns, LINK_TARGET_TYPES[op.predicate])
            found = (
                find_edge(db, from_id, EdgePredicate(op.predicate), to_id)
                if op.if_exists == "return"
                else None
            )
            if found is not None:
                return {
                    "op": op.op,
                    "edge_id": found,
                    "predicate": op.predicate,
                    "created": False,
                }
            edge_id, _ = record_edge_created(
                db, source, from_id, EdgePredicate(op.predicate), to_id, vt, tt
            )
        return {"op": op.op, "edge_id": edge_id, "predicate": op.predicate, "created": True}

    if op.op == "attach_facet":
        _require(op, "to", "facet_type", "producer")
        assert op.to is not None and op.facet_type is not None and op.producer is not None
        if op.data is None or (op.schema_url is None) == (op.schema_id is None):
            raise BatchShapeError("needs 'data' and exactly one of 'schema_url'/'schema_id'")
        attached_to = resolve_attachment_ref(db, op.to, org, ns)
        if op.schema_url is not None:
            facet_id, _ = record_facet_instance_attached(
                db,
                source,
                attached_to,
                op.producer,
                op.schema_url,
                op.facet_type,
                op.data,
                vt,
                tt,
            )
        else:
            assert op.schema_id is not None
            resolved, text = resolve_facet_schema_ref(db, op.schema_id, org, ns)
            facet_id, _ = record_facet_instance_attached_from_store(
                db,
                source,
                attached_to,
                op.producer,
                resolved,
                text,
                op.facet_type,
                op.data,
                vt,
                tt,
            )
        return {"op": op.op, "facet_id": facet_id, "attached_to": attached_to}

    if op.op == "create_datapoint":
        _require(op, "local_id", "for_", "datapoint_type", "kind", "value")
        assert op.local_id is not None and op.for_ is not None
        assert op.datapoint_type is not None and op.kind is not None and op.value is not None
        name = build_name(org, ns, "DataPoint", op.local_id)
        numeric, text_value, boolean = parse_value(op.kind, op.value)
        _, target_id = resolve_ref(db, op.for_, org, ns, ENTITY_TYPES)
        if op.if_exists == "return":
            existing = find_by_name(db, "DataPoint", name)
            if existing is not None:
                # A repeat is the same measurement recorded twice. The same name carrying a
                # different value or describing something else is a different claim, and
                # answering it with the old row would hide that - it wants a correction.
                row = get_datapoint(db, existing)
                same = row is not None and (
                    row["datapoint_type"] == op.datapoint_type
                    and row["value_kind"] == op.kind
                    and row["value_number"] == numeric
                    and row["value_text"] == text_value
                    and row["value_boolean"] == boolean
                )
                if not same or not edge_exists(
                    db, existing, EdgePredicate.characterizes, target_id
                ):
                    raise NameTakenError(
                        f"{name!r} already exists with a different value or subject; "
                        "correct it rather than creating it again"
                    )
                return {"op": op.op, "internal_id": existing, "name": name, "created": False}
        internal_id, _ = record_datapoint_created(
            db,
            source,
            name,
            list(op.xrefs),
            op.datapoint_type,
            op.kind,
            numeric,
            text_value,
            boolean,
            vt,
            tt,
        )
        record_edge_created(db, source, internal_id, EdgePredicate.characterizes, target_id, vt, tt)
        return {"op": op.op, "internal_id": internal_id, "name": name, "created": True}

    _require(op, "local_id", "json_schema")
    assert op.local_id is not None and op.json_schema is not None
    schema_name = build_schema_name(org, ns, op.local_id)
    if op.if_exists == "return":
        # Registering a name again is how a new version is made, so only
        # *identical* content counts as a repeat. Different content is a real new version.
        try:
            existing_id, existing_text = resolve_facet_schema_ref(db, schema_name, org, ns)
        except RepoError:
            existing_id, existing_text = "", ""
        if existing_id and json.loads(existing_text) == op.json_schema:
            return {
                "op": op.op,
                "schema_id": existing_id,
                "schema_name": schema_name,
                "created": False,
            }
    schema_id, _ = record_facet_schema_registered(
        db, source, schema_name, json.dumps(op.json_schema), vt, tt
    )
    return {"op": op.op, "schema_id": schema_id, "schema_name": schema_name, "created": True}


def apply_operations(
    db: Database,
    org: str,
    ns: str,
    source: str,
    operations: Sequence[BatchOperation],
    label: str = "operation",
    positions: Sequence[int] | None = None,
) -> list[dict[str, Any]]:
    """Apply every operation in order, returning one result each.

    Later operations may name entities created by earlier ones by local ID: the earlier
    insert is already visible inside the caller's transaction, so ordinary REF resolution
    finds it. Any failure propagates, and the caller's transaction takes the whole batch
    back with it.

    `label` and `positions` only shape the error message. A batch request says "operation
    3", counting from the list the caller sent. A manifest says "line 7", counting lines in
    the file the author is looking at, which is not the same number once blank and comment
    rows have been skipped.
    """
    results = []
    for index, op in enumerate(operations):
        try:
            results.append(apply_operation(db, org, ns, source, op))
        except RepoError as exc:
            # Say which one failed, keeping the class so HTTP still answers 422 for a
            # malformed operation and 400 for one that names something missing.
            where = positions[index] if positions is not None else index
            raise type(exc)(f"{label} {where} ({op.op}): {exc}") from exc
    return results
