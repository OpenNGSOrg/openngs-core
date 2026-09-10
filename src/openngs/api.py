"""FastAPI REST API - see docs/api-design.md. Mirrors the CLI's
command surface over HTTP instead of the terminal - entity create/list/show, `link`,
`facet`/`facet schema`, `datapoint`, and `event`.
Every write goes through the same `record_*` event-log path the CLI uses; this
is a second client of the store layer, not a reimplementation of it.

Also mounts the GraphQL schema (`graphql_schema.py`, docs/graphql-design.md) at
`/graphql` - one process, one deployment unit, same as the `Dockerfile` already treats "the
API" as a single image.

Server-side org/ns config mirrors the CLI's own env vars (`OPENNGS_ORG`/`OPENNGS_NAMESPACE`/
`OPENNGS_DB_URL`) rather than becoming a per-request parameter - a deployment serves one
lab's namespace, the same way one CLI invocation's env already does. No authentication in
this phase, matching the CLI - a real, separate hardening pass before this is ever exposed
outside a trusted network.
"""

# No `from __future__ import annotations` here, on purpose: FastAPI reads each route's
# real parameter annotations at import time to build request validation, and the
# per-entity request models below are dynamic (create_model) and referenced only by a
# local variable - under postponed evaluation that annotation is a string FastAPI can't
# resolve, and the body parameter silently becomes an unrecognized query param.

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError, create_model, model_validator

from openngs.batch import BatchOperation, BatchShapeError, apply_operations
from openngs.context import DbCtx
from openngs.entities import (
    ENTITIES,
    LINK_SOURCE_TYPES,
    LINK_TARGET_TYPES,
    EntityConfig,
    parent_field_name,
)
from openngs.graphql_schema import graphql_router
from openngs.manifest import parse_manifest
from openngs.model.generated import EdgePredicate
from openngs.store import (
    ENTITY_TYPES,
    SCHEMA_URI_PREFIX,
    NameTakenError,
    RepoError,
    build_name,
    build_schema_name,
    datapoint_value,
    edge_exists,
    entity_retraction,
    entity_state,
    entity_valid_time,
    find_by_name,
    find_edge,
    find_edge_table,
    get_datapoint,
    get_edges,
    get_event,
    get_facet_instance,
    get_facet_schema,
    list_datapoints,
    list_entities,
    list_events,
    list_events_for_subjects,
    list_facet_instances,
    list_facet_schemas,
    lookup_entity,
    new_id,
    parse_missing_edge,
    parse_value,
    record_datapoint_corrected,
    record_datapoint_created,
    record_edge_created,
    record_edge_retracted,
    record_entity_corrected,
    record_entity_created,
    record_entity_retracted,
    record_entity_xref_added,
    record_facet_instance_attached,
    record_facet_instance_attached_from_store,
    record_facet_instance_corrected,
    record_facet_instance_retracted,
    record_facet_schema_registered,
    record_same_as_edge_created,
    replay,
    resolve_attachment_ref,
    resolve_facet_schema_ref,
    resolve_ref,
    validate_facet_data,
    validate_facet_data_from_store,
)
from openngs.store.repo import NAME_RE

app = FastAPI(
    title="OpenNGS",
    description="Sample lineage in sequencing labs - REST API (docs/api-design.md).",
)

# CloudEvents' `source` distinguishes producers without changing the event shape, which is
# what lets this API identify itself separately from the CLI. The CLI's own DEFAULT_SOURCE
# ("openngs-cli") stays what it is.
API_SOURCE = "openngs-api"

# A hand-authored, query-only GraphQL schema mounted into
# this same app/process, not a separate service - GraphiQL is the interactive equivalent of
# the Swagger UI above.
app.include_router(graphql_router, prefix="/graphql")


# Module-level singletons rather than a Query(...) call in each default: ruff's B008 flags
# the inline form here, and one shared definition also keeps the OpenAPI description
# identical on every list route.
_IF_EXISTS_QUERY = Query(
    "error",
    description="What to do when the name is already taken: 'error' (409) or 'return' "
    "(reuse the existing record, so a retried write is idempotent)",
)


def _conflict(kind: str, name: str, internal_id: str, detail: str) -> HTTPException:
    """A 409 a client can act on without parsing prose (#4). The id is what a caller most
    often wants next - it is the record they collided with."""
    return HTTPException(
        status_code=409,
        detail={"detail": detail, "type": kind, "name": name, "internal_id": internal_id},
    )


_AFTER_QUERY = Query(None, description="Continue after this id: the last id of the previous page")


def _set_next_cursor(response: Response, rows: list[Any], limit: int, key: str) -> None:
    """Advertise the next page's cursor when this one came back full.

    A full page means there may be more; an empty final page is the standard cost of not
    counting the whole table on every request. The cursor is the last row's own id, which
    is already in the body, so this header is a convenience rather than the only way to
    continue."""
    if rows and len(rows) == limit:
        response.headers["X-Next-Cursor"] = str(rows[-1][key])


# A list-typed Query in a default trips ruff's B008 where a scalar one does not, so this
# one is a module-level singleton like _AFTER_QUERY above.
_WITHOUT_QUERY = Query(
    None,
    description="Only entities with no such edge: DIRECTION:PREDICATE[:TYPE], repeatable",
)

_EVENT_TYPE_QUERY = Query(None, description="Only these event types, repeatable")

_VALID_FROM_QUERY = Query(
    None, description="Only records whose valid_time is at or after this (inclusive)"
)
_VALID_TO_QUERY = Query(
    None, description="Only records whose valid_time is at or before this (inclusive)"
)


def _bound(value: datetime | None) -> datetime | None:
    """A valid_from/valid_to query parameter, normalized to UTC like every other timestamp."""
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _resolve_times(valid_time: datetime | None) -> tuple[datetime, datetime]:
    """transaction_time is always wall-clock now (it means "when OpenNGS learned
    this", never caller-supplied). valid_time defaults to the same now when not given.
    Both are UTC-aware on the way out, same as the CLI: a valid_time without an offset is
    taken as UTC, one with an offset is converted."""
    transaction_time = datetime.now(UTC)
    if valid_time is None:
        return transaction_time, transaction_time
    if valid_time.tzinfo is None:
        return valid_time.replace(tzinfo=UTC), transaction_time
    return valid_time.astimezone(UTC), transaction_time


@app.exception_handler(NameTakenError)
def _name_taken(_request: Request, exc: NameTakenError) -> JSONResponse:
    """The database's unique index refused the write.

    The routes check for a taken name first so the common case gets a helpful message, but
    that check cannot be atomic; two concurrent writers both pass it and one of them ends
    up here. Same status either way, so a client cannot tell a race from an ordinary
    collision - and does not need to."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValidationError)
def _pydantic_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
    """A Pydantic model failing *inside* a handler (the generated entity models validating
    `name`'s pattern, say) isn't a RequestValidationError, so FastAPI would return a bare
    500. Report it the way a request-body failure is reported instead. The `min_length=1`
    on every `local_id` field below keeps the one known trigger (an empty local_id) from
    getting this far; this is the safety net for anything else."""
    return JSONResponse(status_code=422, content={"detail": exc.errors(include_url=False)})


@app.get("/health", operation_id="health_check")
def health() -> dict[str, str]:
    return {"status": "ok"}


# --- shared show/list rendering, mirroring cli.py's _render_show/_render_list -----------


def _fmt_edge(e: Any, resolved: tuple[str, str] | None) -> dict[str, Any]:
    other_type, other_name = resolved if resolved is not None else (None, None)
    d: dict[str, Any] = {
        "predicate": e.predicate,
        "other_type": other_type,
        "other_id": e.other_id,
        "other_name": other_name,
    }
    if e.predicate == "same_as":
        d.update(asserted_by=e.asserted_by, method=e.method, confidence=e.confidence)
    return d


def _show_payload(
    entity_type: str,
    internal_id: str,
    name: str,
    xrefs: list[str],
    outgoing: list[tuple[Any, tuple[str, str] | None]],
    incoming: list[tuple[Any, tuple[str, str] | None]],
) -> dict[str, Any]:
    return {
        "type": entity_type,
        "internal_id": internal_id,
        "name": name,
        "xrefs": xrefs,
        "outgoing": [_fmt_edge(e, r) for e, r in outgoing],
        "incoming": [_fmt_edge(e, r) for e, r in incoming],
    }


class CorrectEntityRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Why this is being corrected")
    local_id: str | None = Field(None, min_length=1, description="Replace the local ID")
    xrefs: list[str] | None = Field(
        None, description="Replace the whole xref set; omit to keep it, [] to clear it"
    )
    valid_time: datetime | None = None


class AddXrefsRequest(BaseModel):
    xrefs: list[str] = Field(..., min_length=1, description="One or more CURIEs to add")
    valid_time: datetime | None = None


class RetractRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Why this is being retracted")
    cascade: bool = Field(False, description="Also retract every edge touching this entity")
    valid_time: datetime | None = None


# --- per-entity routes (create/list/show), one call per EntityConfig ---------------------


def _build_create_request_model(cfg: EntityConfig) -> type[BaseModel]:
    fields: dict[str, Any] = {
        "local_id": (str, Field(..., min_length=1)),
        "xrefs": (list[str], Field(default_factory=list)),
        "valid_time": (datetime | None, None),
    }
    if cfg.parent is not None:
        # Optional in the model, but exactly one of it and no_parent is required by the
        # handler: an omitted parent stays a 422 rather than a silently orphaned record.
        fields[parent_field_name(cfg.parent)] = (str | None, None)
        fields["no_parent"] = (bool, False)
    if cfg.extra_derived_from:
        fields["derived_from"] = (list[str], Field(default_factory=list))
    return create_model(f"{cfg.type_name}CreateRequest", **fields)


def _register_entity_routes(cfg: EntityConfig) -> None:
    create_request_model = _build_create_request_model(cfg)
    path = f"/{cfg.plural}"
    # {ref:path} (not the default {ref}) - a REF's "full name" form is
    # openngs://{org}/{ns}/{type}/{local_id}, which contains literal "/"s that Starlette's
    # default path-parameter converter refuses to match (it splits on "/"), 404ing before
    # resolve_ref ever runs. :path matches greedily, so a slash-free bare local_id or
    # internal_id still resolves exactly as before - found live, via Claude Desktop
    # actually trying the documented "three REF forms" against this route and getting a 404
    # on the full-name one specifically.
    item_path = f"/{cfg.plural}/{{ref:path}}"
    noun = cfg.cli_name.replace("-", "_")
    plural_noun = cfg.plural.replace("-", "_")

    @app.post(
        path,
        tags=[cfg.type_name],
        summary=f"Create a {cfg.type_name}",
        operation_id=f"create_{noun}",
    )
    def create(
        body: create_request_model,  # type: ignore[valid-type]
        db_ctx: DbCtx,
        if_exists: str = _IF_EXISTS_QUERY,
    ) -> dict[str, Any]:
        db, org, ns = db_ctx
        local_id: str = getattr(body, "local_id")  # noqa: B009
        xrefs: list[str] = getattr(body, "xrefs")  # noqa: B009
        valid_time: datetime | None = getattr(body, "valid_time")  # noqa: B009
        name = build_name(org, ns, cfg.type_name, local_id)
        vt, tt = _resolve_times(valid_time)

        if if_exists not in ("error", "return"):
            raise HTTPException(status_code=422, detail="if_exists must be 'error' or 'return'")
        existing = find_by_name(db, cfg.type_name, name)
        if existing is not None:
            if if_exists == "error":
                raise _conflict(
                    cfg.type_name,
                    name,
                    existing,
                    f"{cfg.type_name} with name {name!r} already exists. Pass "
                    "?if_exists=return to reuse it; to record a genuinely different thing, "
                    "give it its own local_id and assert same_as if they are the same",
                )
            # Reuse it, but only if it is the same record. A name collision with a
            # different parent is a real data problem - two subjects' specimens sharing a
            # local ID, say - and quietly returning the wrong one would bury it.
            if cfg.parent is not None:
                requested_parent: str | None = getattr(body, parent_field_name(cfg.parent))
                if requested_parent is not None:
                    try:
                        _, want = resolve_ref(
                            db, requested_parent, org, ns, cfg.parent.target_types
                        )
                    except RepoError as exc:
                        raise HTTPException(status_code=400, detail=str(exc)) from exc
                    if not edge_exists(db, existing, EdgePredicate(cfg.parent.predicate), want):
                        raise _conflict(
                            cfg.type_name,
                            name,
                            existing,
                            f"{cfg.type_name} {name!r} already exists but is not "
                            f"{cfg.parent.predicate} {requested_parent!r}",
                        )
            return {
                "type": cfg.type_name,
                "internal_id": existing,
                "name": name,
                "created": False,
            }
        if cfg.parent is not None:
            field = parent_field_name(cfg.parent)
            parent_ref: str | None = getattr(body, field)
            no_parent: bool = getattr(body, "no_parent")  # noqa: B009
            if no_parent and parent_ref is not None:
                raise HTTPException(
                    status_code=422, detail=f"send either {field!r} or no_parent, not both"
                )
            if not no_parent and parent_ref is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"{field!r} is required; send no_parent=true for a control or a "
                    "record of unknown provenance",
                )
        try:
            parent_id: str | None = None
            if cfg.parent is not None and parent_ref is not None:
                _, parent_id = resolve_ref(db, parent_ref, org, ns, cfg.parent.target_types)
            derived_from_ids = []
            if cfg.extra_derived_from:
                derived_from_refs: list[str] = getattr(body, "derived_from")  # noqa: B009
                derived_from_ids = list(
                    dict.fromkeys(
                        resolve_ref(db, ref, org, ns, ENTITY_TYPES)[1] for ref in derived_from_refs
                    )
                )  # same REF twice is not a duplicate-edge error, see cli.py
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        internal_id = new_id()
        obj = cfg.model(internal_id=internal_id, name=name, xrefs=list(xrefs), valid_time=vt)
        record_entity_created(
            db, API_SOURCE, cfg.type_name, obj.name, obj.xrefs, vt, tt, internal_id=internal_id
        )
        if parent_id is not None:
            assert cfg.parent is not None
            record_edge_created(
                db,
                API_SOURCE,
                internal_id,
                EdgePredicate(cfg.parent.predicate),
                parent_id,
                vt,
                tt,
            )
        for other_id in derived_from_ids:
            record_edge_created(
                db, API_SOURCE, internal_id, EdgePredicate.derived_from, other_id, vt, tt
            )
        return {
            "type": cfg.type_name,
            "internal_id": internal_id,
            "name": name,
            "created": True,
        }

    list_route: Any
    if cfg.parent is not None:
        parent_alias = parent_field_name(cfg.parent)

        def list_with_parent(
            response: Response,
            db_ctx: DbCtx,
            parent_ref: str | None = Query(None, alias=parent_alias),
            limit: int = Query(50, ge=1),
            after: str | None = _AFTER_QUERY,
            without: list[str] | None = _WITHOUT_QUERY,
            valid_from: datetime | None = _VALID_FROM_QUERY,
            valid_to: datetime | None = _VALID_TO_QUERY,
            include_retracted: bool = Query(False),
        ) -> list[dict[str, Any]]:
            db, org, ns = db_ctx
            parent: tuple[str, str] | None = None
            if parent_ref is not None:
                assert cfg.parent is not None
                try:
                    _, parent_id = resolve_ref(db, parent_ref, org, ns, cfg.parent.target_types)
                except RepoError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                parent = (cfg.parent.predicate, parent_id)
            try:
                rows = list_entities(
                    db,
                    cfg.type_name,
                    limit,
                    parent,
                    include_retracted,
                    _bound(valid_from),
                    _bound(valid_to),
                    after,
                    [parse_missing_edge(w) for w in without or []],
                )
            except RepoError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            items = [{"internal_id": i, "name": n, "valid_time": v} for i, n, v in rows]
            _set_next_cursor(response, items, limit, "internal_id")
            return items

        list_route = list_with_parent
    else:

        def list_without_parent(
            response: Response,
            db_ctx: DbCtx,
            limit: int = Query(50, ge=1),
            after: str | None = _AFTER_QUERY,
            without: list[str] | None = _WITHOUT_QUERY,
            valid_from: datetime | None = _VALID_FROM_QUERY,
            valid_to: datetime | None = _VALID_TO_QUERY,
            include_retracted: bool = Query(False),
        ) -> list[dict[str, Any]]:
            db, _, _ = db_ctx
            try:
                rows = list_entities(
                    db,
                    cfg.type_name,
                    limit,
                    None,
                    include_retracted,
                    _bound(valid_from),
                    _bound(valid_to),
                    after,
                    [parse_missing_edge(w) for w in without or []],
                )
            except RepoError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            items = [{"internal_id": i, "name": n, "valid_time": v} for i, n, v in rows]
            _set_next_cursor(response, items, limit, "internal_id")
            return items

        list_route = list_without_parent

    app.get(
        path,
        tags=[cfg.type_name],
        summary=f"List {cfg.type_name} entities",
        operation_id=f"list_{plural_noun}",
    )(list_route)

    @app.get(
        item_path,
        tags=[cfg.type_name],
        summary=f"Show one {cfg.type_name}",
        operation_id=f"show_{noun}",
    )
    def show(
        ref: str,
        db_ctx: DbCtx,
        edge_limit: int = Query(20, ge=1),
        events: bool = Query(False, description="Also include events related to this entity"),
        include_retracted: bool = Query(False),
    ) -> dict[str, Any]:
        db, org, ns = db_ctx
        try:
            entity_type, internal_id = resolve_ref(
                db, ref, org, ns, (cfg.type_name,), include_retracted
            )
        except RepoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        row = db.fetchone(
            f'SELECT name FROM "{entity_type}" WHERE internal_id = {db.ph(1)}', (internal_id,)
        )
        assert row is not None
        name = row[0]
        xrefs = [
            r[0]
            for r in db.fetchall(
                f'SELECT xrefs FROM "{entity_type}_xrefs" '
                f'WHERE "{entity_type}_internal_id" = {db.ph(1)}',
                (internal_id,),
            )
        ]
        outgoing_edges, incoming_edges = get_edges(db, internal_id, edge_limit, include_retracted)
        outgoing = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in outgoing_edges]
        incoming = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in incoming_edges]
        result = _show_payload(entity_type, internal_id, name, xrefs, outgoing, incoming)
        result["valid_time"] = entity_valid_time(db, entity_type, internal_id)
        retracted_by = entity_retraction(db, entity_type, internal_id)
        if retracted_by is not None:
            result["retracted_by_event"] = retracted_by
        if events:
            edge_ids = [e.edge_id for e in outgoing_edges] + [e.edge_id for e in incoming_edges]
            result["events"] = list_events_for_subjects(db, [internal_id, *edge_ids])
        return result

    @app.post(
        f"/{cfg.plural}/{{ref:path}}/correct",
        tags=[cfg.type_name],
        summary=f"Correct a {cfg.type_name}",
        operation_id=f"correct_{noun}",
    )
    def correct(ref: str, body: CorrectEntityRequest, db_ctx: DbCtx) -> dict[str, Any]:
        db, org, ns = db_ctx
        vt, tt = _resolve_times(body.valid_time)
        try:
            entity_type, internal_id = resolve_ref(db, ref, org, ns, (cfg.type_name,))
        except RepoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        current_name, current_xrefs = entity_state(db, entity_type, internal_id)
        name = (
            build_name(org, ns, cfg.type_name, body.local_id)
            if body.local_id is not None
            else current_name
        )
        # A correction carries full state: xrefs given replace the set, omitted keeps it.
        xrefs = current_xrefs if body.xrefs is None else body.xrefs
        if name == current_name and xrefs == current_xrefs:
            raise HTTPException(
                status_code=400, detail="nothing to correct - supply local_id and/or xrefs"
            )
        try:
            record_entity_corrected(
                db, API_SOURCE, entity_type, internal_id, name, xrefs, vt, tt, body.reason
            )
        except NameTakenError as exc:
            # A collision with an existing record, exactly as on create - so the same 409,
            # not the 400 every other bad-reference RepoError gets.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"type": cfg.type_name, "internal_id": internal_id, "name": name}

    @app.post(
        f"/{cfg.plural}/{{ref:path}}/xrefs",
        tags=[cfg.type_name],
        summary=f"Add external identifiers to a {cfg.type_name}",
        operation_id=f"add_{noun}_xrefs",
    )
    def add_xrefs(ref: str, body: AddXrefsRequest, db_ctx: DbCtx) -> dict[str, Any]:
        """Additive, not a correction: the record was right, it now has one more name.
        Removing or replacing an xref is `POST .../correct` instead."""
        db, org, ns = db_ctx
        vt, tt = _resolve_times(body.valid_time)
        try:
            entity_type, internal_id = resolve_ref(db, ref, org, ns, (cfg.type_name,))
        except RepoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            # One event per xref, all in one transaction.
            for xref in dict.fromkeys(body.xrefs):
                record_entity_xref_added(db, API_SOURCE, entity_type, internal_id, xref, vt, tt)
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        _, xrefs = entity_state(db, entity_type, internal_id)
        return {"type": cfg.type_name, "internal_id": internal_id, "xrefs": xrefs}

    @app.post(
        f"/{cfg.plural}/{{ref:path}}/retract",
        tags=[cfg.type_name],
        summary=f"Retract a {cfg.type_name}",
        operation_id=f"retract_{noun}",
    )
    def retract(ref: str, body: RetractRequest, db_ctx: DbCtx) -> dict[str, Any]:
        db, org, ns = db_ctx
        vt, tt = _resolve_times(body.valid_time)
        try:
            entity_type, internal_id = resolve_ref(db, ref, org, ns, (cfg.type_name,))
        except RepoError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        try:
            event_id, edges = record_entity_retracted(
                db, API_SOURCE, entity_type, internal_id, vt, tt, body.reason, body.cascade
            )
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "type": cfg.type_name,
            "internal_id": internal_id,
            "retracted_by_event": event_id,
            "retracted_edges": edges,
        }


for _cfg in ENTITIES:
    _register_entity_routes(_cfg)


# --- `link` routes, mirroring `openngs link <predicate>` --------------------------------


class LinkRequest(BaseModel):
    from_: str = Field(..., alias="from", description="REF this edge originates from")
    to: str = Field(..., description="REF this edge points to")
    valid_time: datetime | None = None


class SameAsLinkRequest(LinkRequest):
    asserted_by: str = Field(..., description="REF to the Actor asserting this")
    method: str = Field(..., description="e.g. barcode_scan, operator_claim")
    confidence: float = Field(..., ge=0.0, le=1.0)


# URL slug per predicate - same kebab-case the CLI's `link <predicate>` subcommands use
# (docs/cli-design.md). same_as isn't here: its own route below, extra fields and all.
_LINK_URL_SLUGS: dict[str, str] = {
    "derived_from": "derived-from",
    "part_of": "part-of",
    "used": "used",
    "produced_by": "produced-by",
    "characterizes": "characterizes",
}


def _register_link_route(predicate: str, slug: str) -> None:
    source_types = LINK_SOURCE_TYPES[predicate]
    target_types = LINK_TARGET_TYPES[predicate]

    @app.post(
        f"/links/{slug}",
        tags=["link"],
        summary=f"Create a {predicate} edge",
        operation_id=f"link_{predicate}",
    )
    def link(body: LinkRequest, db_ctx: DbCtx, if_exists: str = _IF_EXISTS_QUERY) -> dict[str, Any]:
        db, org, ns = db_ctx
        vt, tt = _resolve_times(body.valid_time)
        try:
            _, from_id = resolve_ref(db, body.from_, org, ns, source_types)
            _, to_id = resolve_ref(db, body.to, org, ns, target_types)
            # An edge is its triple, so a repeat is unambiguous: the same fact, already
            # believed. Retrying a batch of links needs this as much as retrying creates.
            if if_exists == "return":
                found = find_edge(db, from_id, EdgePredicate(predicate), to_id)
                if found is not None:
                    return {
                        "edge_id": found,
                        "predicate": predicate,
                        "from": from_id,
                        "to": to_id,
                        "created": False,
                    }
            edge_id, _ = record_edge_created(
                db, API_SOURCE, from_id, EdgePredicate(predicate), to_id, vt, tt
            )
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "edge_id": edge_id,
            "predicate": predicate,
            "from": from_id,
            "to": to_id,
            "created": True,
        }


for _predicate, _slug in _LINK_URL_SLUGS.items():
    _register_link_route(_predicate, _slug)


@app.post(
    "/links/same-as", tags=["link"], summary="Assert same_as identity", operation_id="link_same_as"
)
def link_same_as(body: SameAsLinkRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    try:
        _, from_id = resolve_ref(db, body.from_, org, ns, ENTITY_TYPES)
        _, to_id = resolve_ref(db, body.to, org, ns, ENTITY_TYPES)
        _, asserted_by_id = resolve_ref(db, body.asserted_by, org, ns, ("Actor",))
        edge_id, _ = record_same_as_edge_created(
            db, API_SOURCE, from_id, to_id, asserted_by_id, body.method, body.confidence, vt, tt
        )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "edge_id": edge_id,
        "predicate": "same_as",
        "from": from_id,
        "to": to_id,
        "asserted_by": asserted_by_id,
        "method": body.method,
        "confidence": body.confidence,
    }


class RetractEdgeRequest(BaseModel):
    reason: str = Field(..., min_length=1, description="Why this edge is being retracted")
    valid_time: datetime | None = None


@app.post(
    "/links/{edge_id}/retract",
    tags=["link"],
    summary="Retract one edge",
    operation_id="retract_link",
)
def link_retract(edge_id: str, body: RetractEdgeRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, _, _ = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    table = find_edge_table(db, edge_id)
    if table is None:
        raise HTTPException(status_code=404, detail=f"no live edge with edge_id {edge_id!r}")
    try:
        event_id = record_edge_retracted(db, API_SOURCE, edge_id, table, vt, tt, body.reason)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"edge_id": edge_id, "retracted_by_event": event_id}


# --- `facet` routes -----------------------------------


class FacetAttachRequest(BaseModel):
    to: str = Field(..., description="REF to the Entity, or a bare edge_id")
    schema_url: str | None = Field(None, description="Local path to this facet's JSON Schema")
    schema_id: str | None = Field(None, description="REF to a schema registered via /facet-schemas")
    type_: str = Field(..., alias="type", description="Class name within the schema")
    producer: str = Field(..., description="e.g. a tool name and version")
    data: dict[str, Any]
    valid_time: datetime | None = None

    @model_validator(mode="after")
    def _exactly_one_schema_ref(self) -> FacetAttachRequest:
        if (self.schema_url is None) == (self.schema_id is None):
            raise ValueError("exactly one of schema_url or schema_id is required")
        return self


@app.post("/facets", tags=["facet"], summary="Attach a facet instance", operation_id="attach_facet")
def facet_attach(body: FacetAttachRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    try:
        attached_to = resolve_attachment_ref(db, body.to, org, ns)
        if body.schema_url is not None:
            facet_id, _ = record_facet_instance_attached(
                db,
                API_SOURCE,
                attached_to,
                body.producer,
                body.schema_url,
                body.type_,
                body.data,
                vt,
                tt,
            )
        else:
            assert body.schema_id is not None
            resolved_schema_id, json_schema_text = resolve_facet_schema_ref(
                db, body.schema_id, org, ns
            )
            facet_id, _ = record_facet_instance_attached_from_store(
                db,
                API_SOURCE,
                attached_to,
                body.producer,
                resolved_schema_id,
                json_schema_text,
                body.type_,
                body.data,
                vt,
                tt,
            )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"facet_id": facet_id, "attached_to": attached_to}


@app.get("/facets", tags=["facet"], summary="List facet instances", operation_id="list_facets")
def facet_list(
    response: Response,
    db_ctx: DbCtx,
    to: str | None = Query(None, description="Filter to facets attached to this REF"),
    limit: int = Query(50, ge=1),
    after: str | None = _AFTER_QUERY,
    valid_from: datetime | None = _VALID_FROM_QUERY,
    valid_to: datetime | None = _VALID_TO_QUERY,
    include_retracted: bool = Query(False),
) -> list[dict[str, Any]]:
    db, org, ns = db_ctx
    attached_to: str | None = None
    if to is not None:
        try:
            attached_to = resolve_attachment_ref(db, to, org, ns)
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        rows = list_facet_instances(
            db, attached_to, limit, include_retracted, _bound(valid_from), _bound(valid_to), after
        )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = [
        {
            "facet_id": r[0],
            "facet_type": r[1],
            "_producer": r[2],
            "_schemaURL": r[3],
            "valid_time": r[4],
        }
        for r in rows
    ]
    _set_next_cursor(response, items, limit, "facet_id")
    return items


@app.get(
    "/facets/{facet_id}",
    tags=["facet"],
    summary="Show one facet instance",
    operation_id="show_facet",
)
def facet_show(
    facet_id: str,
    db_ctx: DbCtx,
    events: bool = Query(False),
    include_retracted: bool = Query(False),
) -> dict[str, Any]:
    db, _, _ = db_ctx
    instance = get_facet_instance(db, facet_id, include_retracted)
    if instance is None:
        raise HTTPException(
            status_code=404, detail=f"no facet instance found with facet_id {facet_id!r}"
        )
    result = dict(instance)
    if events:
        result["events"] = list_events_for_subjects(db, [facet_id])
    return result


class CorrectFacetRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    data: dict[str, Any]
    type_: str | None = Field(None, alias="type", description="Class name, if it also changes")
    valid_time: datetime | None = None


@app.post(
    "/facets/{facet_id}/correct",
    tags=["facet"],
    summary="Correct a facet instance's data",
    operation_id="correct_facet",
)
def facet_correct(facet_id: str, body: CorrectFacetRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, _, _ = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    instance = get_facet_instance(db, facet_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"no facet instance {facet_id!r}")
    facet_type = body.type_ or str(instance["facet_type"])
    schema_url = str(instance["_schemaURL"])
    try:
        # Validated against whatever this instance was pinned to, exactly as attach did.
        if schema_url.startswith(SCHEMA_URI_PREFIX):
            stored_id = schema_url[len(SCHEMA_URI_PREFIX) :]
            stored = get_facet_schema(db, stored_id)
            if stored is None:
                raise HTTPException(status_code=400, detail=f"schema {stored_id!r} is missing")
            validate_facet_data_from_store(
                stored_id, json.dumps(stored["json_schema"]), facet_type, body.data
            )
        else:
            validate_facet_data(schema_url, facet_type, body.data)
        event_id = record_facet_instance_corrected(
            db, API_SOURCE, facet_id, facet_type, body.data, vt, tt, body.reason
        )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"facet_id": facet_id, "corrected_by_event": event_id}


@app.post(
    "/facets/{facet_id}/retract",
    tags=["facet"],
    summary="Retract a facet instance",
    operation_id="retract_facet",
)
def facet_retract(facet_id: str, body: RetractEdgeRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, _, _ = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    if get_facet_instance(db, facet_id) is None:
        raise HTTPException(status_code=404, detail=f"no facet instance {facet_id!r}")
    try:
        event_id = record_facet_instance_retracted(db, API_SOURCE, facet_id, vt, tt, body.reason)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"facet_id": facet_id, "retracted_by_event": event_id}


# --- `facet schema` routes ----------------------------


class FacetSchemaRegisterRequest(BaseModel):
    local_id: str = Field(..., min_length=1, description="Local ID, e.g. qc-metrics")
    json_schema: dict[str, Any] = Field(..., description="An already-generated JSON Schema")
    valid_time: datetime | None = None


@app.post(
    "/facet-schemas",
    tags=["facet schema"],
    summary="Register a facet JSON Schema",
    operation_id="register_facet_schema",
)
def facet_schema_register(
    body: FacetSchemaRegisterRequest,
    db_ctx: DbCtx,
    if_exists: str = _IF_EXISTS_QUERY,
) -> dict[str, Any]:
    """Registering the same name always adds a new immutable version. With
    `?if_exists=return`, registering *identical* content returns the version that already
    holds it instead, so a client that re-registers its schema on every startup does not
    accumulate a version per restart. Different content still registers a new version:
    that is a genuine change, not a repeat."""
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    schema_name = build_schema_name(org, ns, body.local_id)
    if if_exists == "return":
        try:
            existing_id, existing_text = resolve_facet_schema_ref(db, schema_name, org, ns)
        except RepoError:
            existing_id, existing_text = "", ""
        if existing_id and json.loads(existing_text) == body.json_schema:
            return {
                "schema_id": existing_id,
                "schema_name": schema_name,
                "created": False,
            }
    schema_id, _ = record_facet_schema_registered(
        db, API_SOURCE, schema_name, json.dumps(body.json_schema), vt, tt
    )
    return {"schema_id": schema_id, "schema_name": schema_name, "created": True}


@app.get(
    "/facet-schemas",
    tags=["facet schema"],
    summary="List registered facet schemas",
    operation_id="list_facet_schemas",
)
def facet_schema_list(
    response: Response,
    db_ctx: DbCtx,
    name: str | None = Query(None, description="Filter to versions of this schema"),
    limit: int = Query(50, ge=1),
    after: str | None = _AFTER_QUERY,
) -> list[dict[str, str]]:
    db, org, ns = db_ctx
    name_filter = None
    if name is not None:
        name_filter = name if NAME_RE.match(name) else build_schema_name(org, ns, name)
    try:
        rows = list_facet_schemas(db, name_filter, limit, after)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    items = [{"schema_id": r[0], "schema_name": r[1]} for r in rows]
    _set_next_cursor(response, items, limit, "schema_id")
    return items


@app.get(
    "/facet-schemas/{ref:path}",  # see item_path's comment above - same fix, same reason
    tags=["facet schema"],
    summary="Show one registered facet schema",
    operation_id="show_facet_schema",
)
def facet_schema_show(ref: str, db_ctx: DbCtx, events: bool = Query(False)) -> dict[str, Any]:
    db, org, ns = db_ctx
    try:
        schema_id, _ = resolve_facet_schema_ref(db, ref, org, ns)
    except RepoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    schema = get_facet_schema(db, schema_id)
    assert schema is not None
    result = dict(schema)
    if events:
        result["events"] = list_events_for_subjects(db, [schema_id])
    return result


# --- `datapoint` routes --------------------------------


class DataPointCreateRequest(BaseModel):
    local_id: str = Field(
        ..., min_length=1, description="Local ID, e.g. RUN-001-R1-percent-duplication"
    )
    for_: str = Field(..., alias="for", description="REF to the Entity this characterizes")
    type_: str = Field(..., alias="type", description="CURIE, e.g. openngs-dp:percent_duplication")
    kind: str = Field(..., description="number | text | boolean")
    value: str
    xrefs: list[str] = Field(default_factory=list)
    valid_time: datetime | None = None


@app.post(
    "/datapoints",
    tags=["datapoint"],
    summary="Create a DataPoint",
    operation_id="create_datapoint",
)
def datapoint_create(
    body: DataPointCreateRequest,
    db_ctx: DbCtx,
    if_exists: str = _IF_EXISTS_QUERY,
) -> dict[str, Any]:
    db, org, ns = db_ctx
    name = build_name(org, ns, "DataPoint", body.local_id)
    try:
        value_number, value_text, value_boolean = parse_value(body.kind, body.value)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    vt, tt = _resolve_times(body.valid_time)

    existing = find_by_name(db, "DataPoint", name)
    if existing is not None:
        if if_exists != "return":
            raise _conflict(
                "DataPoint",
                name,
                existing,
                f"DataPoint with name {name!r} already exists. Pass ?if_exists=return to "
                "reuse it, or give this measurement its own local_id",
            )
        # A DataPoint *is* its value, so "the same record" means the same measurement of
        # the same thing. A retry sending a different value is not an idempotent repeat;
        # it is a correction, and saying so is more useful than silently keeping either.
        row = get_datapoint(db, existing)
        assert row is not None
        try:
            _, want_target = resolve_ref(db, body.for_, org, ns, ENTITY_TYPES)
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        same = (
            row["datapoint_type"] == body.type_
            and row["value_kind"] == body.kind
            and (row["value_number"], row["value_text"], row["value_boolean"])
            == (value_number, value_text, value_boolean)
            and edge_exists(db, existing, EdgePredicate.characterizes, want_target)
        )
        if not same:
            raise _conflict(
                "DataPoint",
                name,
                existing,
                f"DataPoint {name!r} already exists with a different value or subject; "
                "POST .../correct to change it",
            )
        return {"type": "DataPoint", "internal_id": existing, "name": name, "created": False}
    try:
        _, target_id = resolve_ref(db, body.for_, org, ns, ENTITY_TYPES)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    internal_id, _ = record_datapoint_created(
        db,
        API_SOURCE,
        name,
        body.xrefs,
        body.type_,
        body.kind,
        value_number,
        value_text,
        value_boolean,
        vt,
        tt,
    )
    record_edge_created(db, API_SOURCE, internal_id, EdgePredicate.characterizes, target_id, vt, tt)
    return {"type": "DataPoint", "internal_id": internal_id, "name": name, "created": True}


@app.get(
    "/datapoints", tags=["datapoint"], summary="List DataPoints", operation_id="list_datapoints"
)
def datapoint_list(
    response: Response,
    db_ctx: DbCtx,
    for_ref: str | None = Query(
        None, alias="for", description="Filter to DataPoints characterizing this REF"
    ),
    limit: int = Query(50, ge=1),
    after: str | None = _AFTER_QUERY,
    valid_from: datetime | None = _VALID_FROM_QUERY,
    valid_to: datetime | None = _VALID_TO_QUERY,
    include_retracted: bool = Query(False),
) -> list[dict[str, Any]]:
    db, org, ns = db_ctx
    target_id: str | None = None
    if for_ref is not None:
        try:
            _, target_id = resolve_ref(db, for_ref, org, ns, ENTITY_TYPES)
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        items = list_datapoints(
            db, target_id, limit, include_retracted, _bound(valid_from), _bound(valid_to), after
        )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_next_cursor(response, items, limit, "internal_id")
    return items


@app.get(
    "/datapoints/{ref:path}",  # see item_path's comment above - same fix, same reason
    tags=["datapoint"],
    summary="Show one DataPoint",
    operation_id="show_datapoint",
)
def datapoint_show(
    ref: str,
    db_ctx: DbCtx,
    edge_limit: int = Query(20, ge=1),
    events: bool = Query(False, description="Also include events related to this entity"),
    include_retracted: bool = Query(False),
) -> dict[str, Any]:
    """Unlike the CLI's own `datapoint show --output json` (which omits edges entirely -
    an inconsistency with entity show's JSON shape, not a deliberate design choice), this
    includes outgoing/incoming - a richer, more consistent REST resource, computed from the
    same get_edges() call the table-mode CLI output already makes."""
    db, org, ns = db_ctx
    try:
        _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",), include_retracted)
    except RepoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = get_datapoint(db, internal_id, include_retracted)
    assert row is not None
    outgoing_edges, incoming_edges = get_edges(db, internal_id, edge_limit, include_retracted)
    outgoing = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in outgoing_edges]
    incoming = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in incoming_edges]
    result: dict[str, Any] = {
        **row,
        "value": datapoint_value(row),
        "outgoing": [_fmt_edge(e, r) for e, r in outgoing],
        "incoming": [_fmt_edge(e, r) for e, r in incoming],
    }
    if events:
        edge_ids = [e.edge_id for e in outgoing_edges] + [e.edge_id for e in incoming_edges]
        result["events"] = list_events_for_subjects(db, [internal_id, *edge_ids])
    return result


class CorrectDataPointRequest(BaseModel):
    reason: str = Field(..., min_length=1)
    value: str | None = None
    kind: str | None = Field(None, description="number | text | boolean; needs value with it")
    type_: str | None = Field(None, alias="type")
    local_id: str | None = Field(None, min_length=1)
    xrefs: list[str] | None = None
    valid_time: datetime | None = None


@app.post(
    "/datapoints/{ref:path}/correct",
    tags=["datapoint"],
    summary="Correct a DataPoint",
    operation_id="correct_datapoint",
)
def datapoint_correct(ref: str, body: CorrectDataPointRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    try:
        _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",))
    except RepoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    row = get_datapoint(db, internal_id)
    assert row is not None
    _, current_xrefs = entity_state(db, "DataPoint", internal_id)
    kind = body.kind or str(row["value_kind"])
    if body.value is not None:
        try:
            numeric, text, boolean = parse_value(kind, body.value)
        except RepoError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif body.kind is not None:
        raise HTTPException(
            status_code=400, detail="kind changes how value parses, so send value with it"
        )
    else:
        numeric, text, boolean = row["value_number"], row["value_text"], row["value_boolean"]
    name = (
        build_name(org, ns, "DataPoint", body.local_id)
        if body.local_id is not None
        else str(row["name"])
    )
    try:
        event_id = record_datapoint_corrected(
            db,
            API_SOURCE,
            internal_id,
            name,
            current_xrefs if body.xrefs is None else body.xrefs,
            body.type_ or str(row["datapoint_type"]),
            kind,
            numeric,
            text,
            boolean,
            vt,
            tt,
            body.reason,
        )
    except NameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"internal_id": internal_id, "name": name, "corrected_by_event": event_id}


@app.post(
    "/datapoints/{ref:path}/xrefs",
    tags=["datapoint"],
    summary="Add external identifiers to a DataPoint",
    operation_id="add_datapoint_xrefs",
)
def datapoint_add_xrefs(ref: str, body: AddXrefsRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    try:
        _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",))
    except RepoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        for xref in dict.fromkeys(body.xrefs):
            record_entity_xref_added(db, API_SOURCE, "DataPoint", internal_id, xref, vt, tt)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _, xrefs = entity_state(db, "DataPoint", internal_id)
    return {"type": "DataPoint", "internal_id": internal_id, "xrefs": xrefs}


@app.post(
    "/datapoints/{ref:path}/retract",
    tags=["datapoint"],
    summary="Retract a DataPoint",
    operation_id="retract_datapoint",
)
def datapoint_retract(ref: str, body: RetractRequest, db_ctx: DbCtx) -> dict[str, Any]:
    db, org, ns = db_ctx
    vt, tt = _resolve_times(body.valid_time)
    try:
        _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",))
    except RepoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        event_id, edges = record_entity_retracted(
            db, API_SOURCE, "DataPoint", internal_id, vt, tt, body.reason, body.cascade
        )
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "internal_id": internal_id,
        "retracted_by_event": event_id,
        "retracted_edges": edges,
    }


# --- `POST /batch`: several operations, one transaction ---------------------------------


class BatchRequest(BaseModel):
    operations: list[BatchOperation] = Field(..., min_length=1)


@app.post("/batch", tags=["batch"], summary="Apply several operations", operation_id="batch")
def batch(
    body: BatchRequest,
    db_ctx: DbCtx,
    dry_run: bool = Query(False, description="Validate everything, write nothing"),
) -> dict[str, Any]:
    """Apply an ordered list of operations in one transaction: all of them commit, or none.

    Registering one real-world fact is usually several writes - a sequencing run is the
    run, its raw output set, a derived_from to the pool and a used to the instrument - and
    over four separate calls a client that fails after the second leaves a half-registered
    run behind.

    Later operations may name entities created earlier in the same batch by local ID: they
    are already visible inside the transaction, so ordinary REF resolution finds them.

    Any failure aborts the whole batch and names the operation that failed by index.
    """
    db, org, ns = db_ctx
    try:
        results = apply_operations(db, org, ns, API_SOURCE, body.operations)
    except BatchShapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if dry_run:
        # Everything above was resolved and written; undo it before the dependency commits.
        db.rollback()
    return {"applied": 0 if dry_run else len(results), "dry_run": dry_run, "results": results}


# --- `POST /ingest/manifest`: a sample sheet, applied as one batch -----------------------


class ManifestRequest(BaseModel):
    manifest: str = Field(..., description="The CSV or TSV manifest text; see docs/manifest.md")
    delimiter: str | None = Field(
        None, description="Override the delimiter otherwise read from the header line"
    )
    if_exists: str = Field(
        "error",
        description="'error', or 'skip' to reuse rows that already exist, making a resend safe",
    )


@app.post(
    "/ingest/manifest",
    tags=["batch"],
    summary="Load a CSV/TSV manifest",
    operation_id="ingest_manifest",
)
def ingest_manifest(
    body: ManifestRequest,
    db_ctx: DbCtx,
    dry_run: bool = Query(False, description="Validate everything, write nothing"),
) -> dict[str, Any]:
    """Parse a manifest and apply its rows in file order, in one transaction.

    The same operations `POST /batch` takes, written as a spreadsheet instead of JSON,
    which is the form a LIMS export or a sequencing sample sheet already arrives in. A row
    may name something an earlier row created, and any failure aborts the whole file,
    naming the line that failed.

    `@file` references in a `data` cell are refused here: they would name a file on the
    server rather than one the sender can see. Send the manifest to the CLI for those, or
    inline the JSON.
    """
    db, org, ns = db_ctx
    if body.if_exists not in ("error", "skip"):
        raise HTTPException(status_code=422, detail="if_exists must be 'error' or 'skip'")
    try:
        parsed = parse_manifest(body.manifest, delimiter=body.delimiter, allow_files=False)
    except BatchShapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.if_exists == "skip":
        for op in parsed.operations:
            if op.if_exists == "error":
                op.if_exists = "return"
    try:
        results = apply_operations(db, org, ns, API_SOURCE, parsed.operations, "line", parsed.lines)
    except BatchShapeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except NameTakenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if dry_run:
        db.rollback()
    return {"applied": 0 if dry_run else len(results), "dry_run": dry_run, "results": results}


# --- `event` routes ------------------------------------


@app.get("/events", tags=["event"], summary="List events", operation_id="list_events")
def event_list(
    response: Response,
    db_ctx: DbCtx,
    limit: int = Query(50, ge=1),
    after: str | None = Query(
        None, description="Continue after this event_id: the last one you processed"
    ),
    type: list[str] | None = _EVENT_TYPE_QUERY,
    source: str | None = Query(None, description="Only events from this producer"),
) -> list[dict[str, Any]]:
    """The log, oldest first. `after` makes following it a resumable poll: the log is
    append-only, so an event already returned never moves and a new one only ever appears
    after the cursor. `X-Next-Cursor` carries the id to pass next when a page comes back
    full."""
    db, _, _ = db_ctx
    try:
        events = list_events(db, limit, after, type, source)
    except RepoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _set_next_cursor(response, events, limit, "event_id")
    return events


@app.get("/events/{event_id}", tags=["event"], summary="Show one event", operation_id="show_event")
def event_show(event_id: str, db_ctx: DbCtx) -> dict[str, Any]:
    db, _, _ = db_ctx
    event = get_event(db, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"no event found with event_id {event_id!r}")
    return event


@app.post(
    "/events/replay",
    tags=["event"],
    summary="Rebuild the projection from the event log",
    operation_id="replay_events",
)
def event_replay(
    db_ctx: DbCtx,
    yes: bool = Query(
        False, description="Required: confirms you understand this truncates the projection"
    ),
) -> dict[str, int]:
    """Truncate the graph projection and rebuild it from the event log. Never touches the
    event log itself for why this isn't a violation of invariant 1."""
    db, _, _ = db_ctx
    if not yes:
        raise HTTPException(
            status_code=400,
            detail="this truncates every projection table and rebuilds it from the event "
            "log - pass ?yes=true to confirm",
        )
    count = replay(db)
    return {"replayed": count}
