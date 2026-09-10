"""Typer CLI - see docs/cli-design.md for the full design. Writes go through the event log
Every create/link/attach/register command emits a CloudEvents-shaped Event, then
applies it to the graph projection in the same transaction - see openngs event list/show/replay."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

import typer

from openngs.auth import cli_principal
from openngs.batch import BatchShapeError, apply_operations
from openngs.entities import ENTITIES, LINK_SOURCE_TYPES, LINK_TARGET_TYPES, EntityConfig
from openngs.manifest import parse_manifest
from openngs.model.generated import EdgePredicate
from openngs.relay import RelayState, initial_cursor, run_relay
from openngs.sinks import DeliveryError, FileSink, Sink, WebhookSink
from openngs.store import (
    DEFAULT_SOURCE,
    ENTITY_TYPES,
    SCHEMA_URI_PREFIX,
    Database,
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
from openngs.store.db import DEFAULT_DB_URL
from openngs.store.repo import NAME_RE

app = typer.Typer(no_args_is_help=True)
ingest_app = typer.Typer(no_args_is_help=True)
link_app = typer.Typer(no_args_is_help=True)
facet_app = typer.Typer(no_args_is_help=True)
facet_schema_app = typer.Typer(no_args_is_help=True)
datapoint_app = typer.Typer(no_args_is_help=True)
event_app = typer.Typer(no_args_is_help=True)
facet_app.add_typer(facet_schema_app, name="schema")
app.add_typer(ingest_app, name="ingest")
app.add_typer(link_app, name="link")
app.add_typer(facet_app, name="facet")
app.add_typer(datapoint_app, name="datapoint")
app.add_typer(event_app, name="event")


class OutputFormat(StrEnum):
    table = "table"
    id = "id"
    json = "json"


@dataclass
class Settings:
    org: str | None
    ns: str | None
    db_url: str


@app.callback()
def main(
    ctx: typer.Context,
    org: str | None = typer.Option(
        None, "--org", envvar="OPENNGS_ORG", help="Org segment of names, e.g. acme-genomics."
    ),
    ns: str | None = typer.Option(
        None, "--ns", envvar="OPENNGS_NAMESPACE", help="Namespace segment of names, e.g. core-lab."
    ),
    db_url: str = typer.Option(
        DEFAULT_DB_URL,
        "--db-url",
        envvar="OPENNGS_DB_URL",
        help="sqlite:///path/to/file.db or postgresql://user:pass@host:port/db",
    ),
) -> None:
    ctx.obj = Settings(org=org, ns=ns, db_url=db_url)


def _fail(message: str) -> NoReturn:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=1)


def _settings(ctx: typer.Context) -> tuple[str, str, str]:
    settings = ctx.obj
    assert isinstance(settings, Settings)
    if not settings.org or not settings.ns:
        _fail("--org/OPENNGS_ORG and --ns/OPENNGS_NAMESPACE must both be set")
    return settings.db_url, settings.org, settings.ns


def _resolve_times(valid_time: str | None) -> tuple[datetime, datetime]:
    """transaction_time is always wall-clock now (it means "when OpenNGS learned
    this", never a CLI input). valid_time defaults to the same now when not given - the
    common case, recording a fact as it happens. Either way both are UTC-aware: a
    --valid-time without an offset is taken as UTC, one with an offset is converted, so
    every stored timestamp has one shape and sorts/compares correctly (SQLite stores them
    as strings)."""
    transaction_time = datetime.now(UTC)
    if valid_time is None:
        return transaction_time, transaction_time
    try:
        parsed = datetime.fromisoformat(valid_time)
    except ValueError as exc:
        _fail(f"--valid-time {valid_time!r} is not a valid ISO 8601 datetime: {exc}")
    return _to_utc(parsed), transaction_time


def _to_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


_VALID_TIME_OPTION = typer.Option(
    None,
    "--valid-time",
    help="ISO 8601, e.g. 2026-01-15T09:00:00 (taken as UTC if no offset given). Default: now.",
)


def _parse_bound(flag: str, value: str | None) -> datetime | None:
    """--valid-from/--valid-to accept a date or a full ISO 8601 datetime; a bare date means
    midnight. No offset is taken as UTC, matching --valid-time."""
    if value is None:
        return None
    try:
        return _to_utc(datetime.fromisoformat(value))
    except ValueError as exc:
        _fail(f"{flag} {value!r} is not a valid ISO 8601 date or datetime: {exc}")


_IF_EXISTS_OPTION = typer.Option(
    "error",
    "--if-exists",
    help="When the name is taken: 'error', or 'return' to reuse it so reruns are safe",
)
_NO_PARENT_OPTION = typer.Option(
    False,
    "--no-parent",
    help="Create with no parent edge: a control, or a record of unknown provenance",
)


def _check_parent_choice(parent_ref: str | None, no_parent: bool, flag: str) -> None:
    """Exactly one of the parent option and --no-parent. Requiring the opt-out explicitly
    is what keeps a forgotten flag an error rather than a silently orphaned record."""
    if no_parent and parent_ref is not None:
        _fail(f"pass either {flag} or --no-parent, not both")
    if not no_parent and parent_ref is None:
        _fail(f"{flag} is required; pass --no-parent for a control or unknown provenance")


_WITHOUT_OPTION = typer.Option(
    [],
    "--without",
    help="Only entities with no such edge: DIRECTION:PREDICATE[:TYPE], repeatable, "
    'e.g. "incoming:derived_from:Extract"',
)
_AFTER_OPTION = typer.Option(
    None, "--after", help="Continue after this id: the last id of the previous page"
)
_VALID_FROM_OPTION = typer.Option(
    None, "--valid-from", help="Only records whose valid_time is at or after this (inclusive)"
)
_VALID_TO_OPTION = typer.Option(
    None, "--valid-to", help="Only records whose valid_time is at or before this (inclusive)"
)
_REASON_OPTION = typer.Option(
    ..., "--reason", help="Why this is being corrected or retracted. Required."
)
_INCLUDE_RETRACTED_OPTION = typer.Option(
    False, "--include-retracted", help="Also show records that have been retracted"
)


def _do_xref_add(
    ctx: typer.Context,
    entity_type: str,
    ref: str,
    xrefs: list[str],
    valid_time: str | None,
) -> None:
    db_url, org, ns = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, internal_id = resolve_ref(db, ref, org, ns, (entity_type,))
            # One event per xref, all in one transaction: each is an independent fact, and
            # a half-applied batch would leave the log disagreeing with the projection.
            for xref in dict.fromkeys(xrefs):
                record_entity_xref_added(db, DEFAULT_SOURCE, entity_type, internal_id, xref, vt, tt)
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(f"added {len(dict.fromkeys(xrefs))} xref(s) to {entity_type} {internal_id}")


def _do_retract(
    ctx: typer.Context,
    entity_type: str,
    ref: str,
    reason: str,
    cascade: bool,
    valid_time: str | None,
) -> None:
    db_url, org, ns = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, internal_id = resolve_ref(db, ref, org, ns, (entity_type,))
            _, edges = record_entity_retracted(
                db, DEFAULT_SOURCE, entity_type, internal_id, vt, tt, reason, cascade
            )
        except RepoError as exc:
            _fail(str(exc))
    suffix = f", {len(edges)} edge(s)" if edges else ""
    typer.echo(f"retracted {entity_type} {internal_id}{suffix}")


def _require_local_id(local_id: str) -> None:
    """The name pattern (openngs://{org}/{ns}/{type}/{local_id}) needs a non-empty last
    segment; catch it here with a plain error rather than letting Pydantic's model
    validation raise a traceback mid-transaction."""
    if not local_id:
        _fail("LOCAL_ID must not be empty")


# --- shared implementations ---------------------------------------------------------------


def _render_created(type_name: str, internal_id: str, name: str, output: OutputFormat) -> None:
    if output is OutputFormat.id:
        typer.echo(internal_id)
    elif output is OutputFormat.json:
        typer.echo(json.dumps({"type": type_name, "internal_id": internal_id, "name": name}))
    else:
        typer.echo(f"{type_name}  {name}")
        typer.echo(f"internal_id: {internal_id}")


def _do_create(
    ctx: typer.Context,
    cfg: EntityConfig,
    local_id: str,
    parent_ref: str | None,
    derived_from_refs: list[str],
    xrefs: list[str],
    output: OutputFormat,
    dry_run: bool = False,
    valid_time: str | None = None,
    if_exists: str = "error",
) -> None:
    db_url, org, ns = _settings(ctx)
    _require_local_id(local_id)
    if if_exists not in ("error", "return"):
        _fail("--if-exists must be 'error' or 'return'")
    name = build_name(org, ns, cfg.type_name, local_id)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        existing = find_by_name(db, cfg.type_name, name)
        if existing is not None:
            if if_exists == "error":
                _fail(
                    f"{cfg.type_name} with name {name!r} already exists "
                    f"(internal_id={existing}); pass --if-exists return to reuse it, or "
                    "give this one its own LOCAL_ID"
                )
            # Reuse it only if it is the same record; a name collision with a different
            # parent is a data problem worth surfacing, not a rerun.
            if cfg.parent is not None and parent_ref is not None:
                try:
                    _, want = resolve_ref(db, parent_ref, org, ns, cfg.parent.target_types)
                except RepoError as exc:
                    _fail(str(exc))
                if not edge_exists(db, existing, EdgePredicate(cfg.parent.predicate), want):
                    _fail(
                        f"{cfg.type_name} {name!r} already exists but is not "
                        f"{cfg.parent.predicate} {parent_ref!r}"
                    )
            _render_created(cfg.type_name, existing, name, output)
            return
        try:
            parent_id: str | None = None
            if cfg.parent is not None and parent_ref is not None:
                _, parent_id = resolve_ref(db, parent_ref, org, ns, cfg.parent.target_types)
            # dict.fromkeys: the same REF given twice would otherwise be a duplicate-edge
            # error from record_edge_created halfway through the create.
            derived_from_ids = list(
                dict.fromkeys(
                    resolve_ref(db, ref, org, ns, ENTITY_TYPES)[1] for ref in derived_from_refs
                )
            )
        except RepoError as exc:
            _fail(str(exc))

        internal_id = new_id()
        if dry_run:
            typer.echo(f"(dry run) would create {cfg.type_name} {name!r} ({internal_id})")
            if parent_id is not None:
                assert cfg.parent is not None
                typer.echo(f"(dry run) would link {cfg.parent.predicate} -> {parent_id}")
            for other_id in derived_from_ids:
                typer.echo(f"(dry run) would link derived_from -> {other_id}")
            return

        obj = cfg.model(internal_id=internal_id, name=name, xrefs=list(xrefs), valid_time=vt)
        record_entity_created(
            db,
            DEFAULT_SOURCE,
            cfg.type_name,
            obj.name,
            obj.xrefs,
            vt,
            tt,
            internal_id=obj.internal_id,
        )
        if parent_id is not None:
            assert cfg.parent is not None
            record_edge_created(
                db,
                DEFAULT_SOURCE,
                obj.internal_id,
                EdgePredicate(cfg.parent.predicate),
                parent_id,
                vt,
                tt,
            )
        for other_id in derived_from_ids:
            record_edge_created(
                db, DEFAULT_SOURCE, obj.internal_id, EdgePredicate.derived_from, other_id, vt, tt
            )
    _render_created(cfg.type_name, obj.internal_id, obj.name, output)


def _render_list(type_name: str, rows: list[tuple[str, str, Any]], output: OutputFormat) -> None:
    if output is OutputFormat.id:
        for internal_id, _, _ in rows:
            typer.echo(internal_id)
    elif output is OutputFormat.json:
        typer.echo(
            json.dumps([{"internal_id": i, "name": n, "valid_time": _iso(v)} for i, n, v in rows])
        )
    else:
        if not rows:
            typer.echo(f"(no {type_name} entries)")
        for internal_id, name, valid_time in rows:
            typer.echo(f"{internal_id}  {name}  valid_time={_iso(valid_time)}")


def _do_list(
    ctx: typer.Context,
    cfg: EntityConfig,
    parent_ref: str | None,
    limit: int,
    output: OutputFormat,
    include_retracted: bool = False,
    valid_from: str | None = None,
    valid_to: str | None = None,
    after: str | None = None,
    without: list[str] | None = None,
) -> None:
    db_url, org, ns = _settings(ctx)
    try:
        missing = [parse_missing_edge(spec) for spec in without or []]
    except RepoError as exc:
        _fail(str(exc))
    vfrom = _parse_bound("--valid-from", valid_from)
    vto = _parse_bound("--valid-to", valid_to)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        parent: tuple[str, str] | None = None
        if parent_ref is not None:
            assert cfg.parent is not None
            try:
                _, parent_id = resolve_ref(db, parent_ref, org, ns, cfg.parent.target_types)
            except RepoError as exc:
                _fail(str(exc))
            parent = (cfg.parent.predicate, parent_id)
        try:
            rows = list_entities(
                db, cfg.type_name, limit, parent, include_retracted, vfrom, vto, after, missing
            )
        except RepoError as exc:
            _fail(str(exc))
    _render_list(cfg.type_name, rows, output)


def _iso(value: Any) -> str:
    """Projection timestamps come back as an ISO string from SQLite and a datetime from
    Postgres; render one shape either way."""
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _fmt_other(resolved: tuple[str, str] | None) -> str:
    if resolved is None:
        return "(unknown entity)"
    other_type, other_name = resolved
    return f"{other_type}  {other_name}"


def _render_events(events: list[dict[str, Any]]) -> None:
    typer.echo("")
    typer.echo("Events:")
    if not events:
        typer.echo("  (none)")
    for event in events:
        typer.echo(f"  {event['event_id']}  {event['type']}  valid_time={event['valid_time']}")


def _render_show(
    entity_type: str,
    internal_id: str,
    name: str,
    xrefs: list[str],
    outgoing: list[tuple[Any, tuple[str, str] | None]],
    incoming: list[tuple[Any, tuple[str, str] | None]],
    output: OutputFormat,
    events: list[dict[str, Any]] | None = None,
    retracted_by: str | None = None,
    valid_time: Any = None,
) -> None:
    if output is OutputFormat.id:
        typer.echo(internal_id)
        return

    def edge_dict(e: Any, resolved: tuple[str, str] | None) -> dict[str, Any]:
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

    if output is OutputFormat.json:
        payload: dict[str, Any] = {
            "type": entity_type,
            "internal_id": internal_id,
            "name": name,
            "valid_time": None if valid_time is None else _iso(valid_time),
            "xrefs": xrefs,
            "outgoing": [edge_dict(e, r) for e, r in outgoing],
            "incoming": [edge_dict(e, r) for e, r in incoming],
        }
        if retracted_by is not None:
            payload["retracted_by_event"] = retracted_by
        if events is not None:
            payload["events"] = events
        typer.echo(json.dumps(payload))
        return

    banner = "  [RETRACTED]" if retracted_by is not None else ""
    typer.echo(f"{entity_type}  {name}{banner}")
    typer.echo(f"internal_id: {internal_id}")
    if valid_time is not None:
        typer.echo(f"valid_time: {_iso(valid_time)}")
    if retracted_by is not None:
        typer.echo(f"retracted_by_event: {retracted_by}")
    typer.echo(f"xrefs: {', '.join(xrefs) if xrefs else '(none)'}")
    typer.echo("")
    typer.echo("Outgoing:")
    if not outgoing:
        typer.echo("  (none)")
    for e, r in outgoing:
        suffix = (
            f"  [asserted_by={e.asserted_by} method={e.method} confidence={e.confidence}]"
            if e.predicate == "same_as"
            else ""
        )
        typer.echo(f"  {e.predicate} → {_fmt_other(r)}{suffix}")
    typer.echo("")
    typer.echo("Incoming:")
    if not incoming:
        typer.echo("  (none)")
    for e, r in incoming:
        suffix = (
            f"  [asserted_by={e.asserted_by} method={e.method} confidence={e.confidence}]"
            if e.predicate == "same_as"
            else ""
        )
        typer.echo(f"  {e.predicate} ← {_fmt_other(r)}{suffix}")
    if events is not None:
        _render_events(events)


def _do_show(
    ctx: typer.Context,
    cfg: EntityConfig,
    ref: str,
    edge_limit: int,
    output: OutputFormat,
    show_events: bool = False,
    include_retracted: bool = False,
) -> None:
    db_url, org, ns = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            entity_type, internal_id = resolve_ref(
                db, ref, org, ns, (cfg.type_name,), include_retracted
            )
        except RepoError as exc:
            _fail(str(exc))
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
        retracted_by = entity_retraction(db, entity_type, internal_id)
        valid_time = entity_valid_time(db, entity_type, internal_id)
        events = None
        if show_events:
            edge_ids = [e.edge_id for e in outgoing_edges] + [e.edge_id for e in incoming_edges]
            events = list_events_for_subjects(db, [internal_id, *edge_ids])
    _render_show(
        entity_type,
        internal_id,
        name,
        xrefs,
        outgoing,
        incoming,
        output,
        events,
        retracted_by,
        valid_time,
    )


# --- per-entity Typer sub-apps --------------------------------------------------------


def _build_entity_app(cfg: EntityConfig) -> typer.Typer:
    sub = typer.Typer(no_args_is_help=True)
    parent = cfg.parent

    create: Any
    if parent is None:

        def create_no_parent(
            ctx: typer.Context,
            local_id: str = typer.Argument(..., help="Local ID, e.g. SPEC-001"),
            xref: list[str] = typer.Option([], "--xref", help="CURIE, repeatable"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Validate, don't write"),
            valid_time: str | None = _VALID_TIME_OPTION,
            if_exists: str = _IF_EXISTS_OPTION,
            output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
        ) -> None:
            _do_create(ctx, cfg, local_id, None, [], xref, output, dry_run, valid_time, if_exists)

        create = create_no_parent

    elif not cfg.extra_derived_from:

        def create_with_parent(
            ctx: typer.Context,
            local_id: str = typer.Argument(..., help="Local ID, e.g. SPEC-001"),
            parent_ref: str | None = typer.Option(
                None,
                parent.flag,
                help=f"REF to the {'/'.join(parent.target_types)} this is {parent.predicate} of",
            ),
            no_parent: bool = _NO_PARENT_OPTION,
            xref: list[str] = typer.Option([], "--xref", help="CURIE, repeatable"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Validate, don't write"),
            valid_time: str | None = _VALID_TIME_OPTION,
            if_exists: str = _IF_EXISTS_OPTION,
            output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
        ) -> None:
            _check_parent_choice(parent_ref, no_parent, parent.flag)
            _do_create(
                ctx,
                cfg,
                local_id,
                parent_ref,
                [],
                xref,
                output,
                dry_run,
                valid_time,
                if_exists,
            )

        create = create_with_parent

    else:

        def create_data_file(
            ctx: typer.Context,
            local_id: str = typer.Argument(..., help="Local ID, e.g. RUN-001-R1.fastq.gz"),
            parent_ref: str | None = typer.Option(
                None,
                parent.flag,
                help=f"REF to the {'/'.join(parent.target_types)} this was produced_by",
            ),
            no_parent: bool = _NO_PARENT_OPTION,
            derived_from: list[str] = typer.Option(
                [], "--derived-from", help="REF(s) this is derived_from, repeatable"
            ),
            xref: list[str] = typer.Option([], "--xref", help="CURIE, repeatable"),
            dry_run: bool = typer.Option(False, "--dry-run", help="Validate, don't write"),
            valid_time: str | None = _VALID_TIME_OPTION,
            if_exists: str = _IF_EXISTS_OPTION,
            output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
        ) -> None:
            _check_parent_choice(parent_ref, no_parent, parent.flag)
            _do_create(
                ctx,
                cfg,
                local_id,
                parent_ref,
                derived_from,
                xref,
                output,
                dry_run,
                valid_time,
                if_exists,
            )

        create = create_data_file

    sub.command("create")(create)

    list_cmd: Any
    if parent is None:

        def list_no_parent(
            ctx: typer.Context,
            limit: int = typer.Option(50, "--limit"),
            after: str | None = _AFTER_OPTION,
            without: list[str] = _WITHOUT_OPTION,
            valid_from: str | None = _VALID_FROM_OPTION,
            valid_to: str | None = _VALID_TO_OPTION,
            include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
            output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
        ) -> None:
            _do_list(
                ctx,
                cfg,
                None,
                limit,
                output,
                include_retracted,
                valid_from,
                valid_to,
                after,
                without,
            )

        list_cmd = list_no_parent

    else:

        def list_with_parent(
            ctx: typer.Context,
            parent_ref: str | None = typer.Option(
                None, parent.flag, help="Filter to children of this REF"
            ),
            limit: int = typer.Option(50, "--limit"),
            after: str | None = _AFTER_OPTION,
            without: list[str] = _WITHOUT_OPTION,
            valid_from: str | None = _VALID_FROM_OPTION,
            valid_to: str | None = _VALID_TO_OPTION,
            include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
            output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
        ) -> None:
            _do_list(
                ctx,
                cfg,
                parent_ref,
                limit,
                output,
                include_retracted,
                valid_from,
                valid_to,
                after,
                without,
            )

        list_cmd = list_with_parent

    sub.command("list")(list_cmd)

    def correct(
        ctx: typer.Context,
        ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
        reason: str = _REASON_OPTION,
        local_id: str | None = typer.Option(
            None, "--local-id", help="Replace the local ID (and so the name)"
        ),
        xref: list[str] = typer.Option(
            [], "--xref", help="Replace the whole xref set with these, repeatable"
        ),
        clear_xrefs: bool = typer.Option(False, "--clear-xrefs", help="Remove every xref"),
        valid_time: str | None = _VALID_TIME_OPTION,
        output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
    ) -> None:
        """Replace this entity's name and/or xrefs. The record stays believed."""
        db_url, org, ns = _settings(ctx)
        vt, tt = _resolve_times(valid_time)
        with Database.connect(db_url, recorded_by=cli_principal()) as db:
            try:
                entity_type, internal_id = resolve_ref(db, ref, org, ns, (cfg.type_name,))
            except RepoError as exc:
                _fail(str(exc))
            current_name, current_xrefs = entity_state(db, entity_type, internal_id)
            if local_id is not None:
                _require_local_id(local_id)
                name = build_name(org, ns, cfg.type_name, local_id)
            else:
                name = current_name
            # A correction carries full state: xrefs given replace the set, none given keep
            # it, --clear-xrefs empties it.
            new_xrefs = [] if clear_xrefs else (list(xref) if xref else current_xrefs)
            if name == current_name and new_xrefs == current_xrefs:
                _fail("nothing to correct - pass --local-id, --xref, or --clear-xrefs")
            try:
                record_entity_corrected(
                    db, DEFAULT_SOURCE, entity_type, internal_id, name, new_xrefs, vt, tt, reason
                )
            except RepoError as exc:
                _fail(str(exc))
        _render_created(cfg.type_name, internal_id, name, output)

    sub.command("correct")(correct)

    xref_app = typer.Typer(no_args_is_help=True)

    @xref_app.command("add")
    def xref_add(
        ctx: typer.Context,
        ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
        xrefs: list[str] = typer.Argument(..., help="One or more CURIEs to add"),
        valid_time: str | None = _VALID_TIME_OPTION,
    ) -> None:
        """Record one or more further external identifiers for an existing record.

        Additive, not a correction: an accession arriving weeks after submission does not
        mean anything already recorded was wrong. To remove or replace an xref, use
        `correct --xref`/`--clear-xrefs` instead.
        """
        _do_xref_add(ctx, cfg.type_name, ref, xrefs, valid_time)

    sub.add_typer(xref_app, name="xref")

    def retract(
        ctx: typer.Context,
        ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
        reason: str = _REASON_OPTION,
        cascade: bool = typer.Option(
            False, "--cascade", help="Also retract every edge touching this entity"
        ),
        valid_time: str | None = _VALID_TIME_OPTION,
    ) -> None:
        """Withdraw this entity: it stops appearing in reads, and the log records why."""
        _do_retract(ctx, cfg.type_name, ref, reason, cascade, valid_time)

    sub.command("retract")(retract)

    def show(
        ctx: typer.Context,
        ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
        edge_limit: int = typer.Option(20, "--edge-limit"),
        events: bool = typer.Option(
            False, "--events", help="Also list events related to this entity"
        ),
        include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
        output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
    ) -> None:
        _do_show(ctx, cfg, ref, edge_limit, output, events, include_retracted)

    sub.command("show")(show)

    return sub


for _cfg in ENTITIES:
    app.add_typer(_build_entity_app(_cfg), name=_cfg.cli_name)


# --- generic `link` command ------------------------------------------------------------


def _do_link(
    ctx: typer.Context,
    predicate: str,
    from_ref: str,
    to_ref: str,
    valid_time: str | None,
    if_exists: str = "error",
) -> None:
    db_url, org, ns = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, from_id = resolve_ref(db, from_ref, org, ns, LINK_SOURCE_TYPES[predicate])
            _, to_id = resolve_ref(db, to_ref, org, ns, LINK_TARGET_TYPES[predicate])
            if if_exists == "return":
                found = find_edge(db, from_id, EdgePredicate(predicate), to_id)
                if found is not None:
                    typer.echo(found)
                    return
            edge_id, _ = record_edge_created(
                db, DEFAULT_SOURCE, from_id, EdgePredicate(predicate), to_id, vt, tt
            )
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(edge_id)


@link_app.command("derived-from")
def link_derived_from(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    valid_time: str | None = _VALID_TIME_OPTION,
    if_exists: str = _IF_EXISTS_OPTION,
) -> None:
    _do_link(ctx, "derived_from", from_, to, valid_time, if_exists)


@link_app.command("part-of")
def link_part_of(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    valid_time: str | None = _VALID_TIME_OPTION,
    if_exists: str = _IF_EXISTS_OPTION,
) -> None:
    _do_link(ctx, "part_of", from_, to, valid_time, if_exists)


@link_app.command("used")
def link_used(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    valid_time: str | None = _VALID_TIME_OPTION,
    if_exists: str = _IF_EXISTS_OPTION,
) -> None:
    _do_link(ctx, "used", from_, to, valid_time, if_exists)


@link_app.command("produced-by")
def link_produced_by(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    valid_time: str | None = _VALID_TIME_OPTION,
    if_exists: str = _IF_EXISTS_OPTION,
) -> None:
    _do_link(ctx, "produced_by", from_, to, valid_time, if_exists)


@link_app.command("characterizes")
def link_characterizes(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from", help="REF to the DataPoint"),
    to: str = typer.Option(..., "--to", help="REF to the Entity it characterizes"),
    valid_time: str | None = _VALID_TIME_OPTION,
    if_exists: str = _IF_EXISTS_OPTION,
) -> None:
    _do_link(ctx, "characterizes", from_, to, valid_time, if_exists)


@link_app.command("same-as")
def link_same_as(
    ctx: typer.Context,
    from_: str = typer.Option(..., "--from"),
    to: str = typer.Option(..., "--to"),
    asserted_by: str = typer.Option(..., "--asserted-by", help="REF to the Actor asserting this"),
    method: str = typer.Option(..., "--method", help="e.g. barcode_scan, operator_claim"),
    confidence: float = typer.Option(..., "--confidence", min=0.0, max=1.0),
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    db_url, org, ns = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, from_id = resolve_ref(db, from_, org, ns, ENTITY_TYPES)
            _, to_id = resolve_ref(db, to, org, ns, ENTITY_TYPES)
            _, asserted_by_id = resolve_ref(db, asserted_by, org, ns, ("Actor",))
            edge_id, _ = record_same_as_edge_created(
                db, DEFAULT_SOURCE, from_id, to_id, asserted_by_id, method, confidence, vt, tt
            )
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(edge_id)


@link_app.command("retract")
def link_retract(
    ctx: typer.Context,
    edge_id: str = typer.Argument(..., help="The edge_id printed when the link was created"),
    reason: str = _REASON_OPTION,
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    """Withdraw one edge. The relationship stops being believed; both entities stay."""
    db_url, _, _ = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        table = find_edge_table(db, edge_id)
        if table is None:
            _fail(f"no live edge found with edge_id {edge_id!r}")
        try:
            record_edge_retracted(db, DEFAULT_SOURCE, edge_id, table, vt, tt, reason)
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(f"retracted edge {edge_id}")


# --- generic `facet` command -------------------------------------------------


def _parse_data(data: str) -> dict[str, Any]:
    if data.startswith("@"):
        try:
            raw = Path(data[1:]).read_text()
        except OSError as exc:
            _fail(f"--data {data!r}: cannot read file: {exc}")
    else:
        raw = data
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"--data is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        _fail("--data must be a JSON object")
    return parsed


@facet_app.command("attach")
def facet_attach(
    ctx: typer.Context,
    to: str = typer.Option(..., "--to", help="REF to the Entity, or a bare edge_id"),
    schema_url: str | None = typer.Option(
        None, "--schema-url", help="Local path to this facet's JSON Schema"
    ),
    schema_id: str | None = typer.Option(
        None,
        "--schema-id",
        help="REF to a schema registered via `facet schema register`",
    ),
    facet_type: str = typer.Option(..., "--type", help="Class name within the schema"),
    producer: str = typer.Option(..., "--producer", help="e.g. a tool name and version"),
    data: str = typer.Option(..., "--data", help="Inline JSON, or @path/to/file.json"),
    valid_time: str | None = _VALID_TIME_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    if (schema_url is None) == (schema_id is None):
        _fail("exactly one of --schema-url or --schema-id is required")
    db_url, org, ns = _settings(ctx)
    parsed_data = _parse_data(data)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            attached_to = resolve_attachment_ref(db, to, org, ns)
            if schema_url is not None:
                facet_id, _ = record_facet_instance_attached(
                    db,
                    DEFAULT_SOURCE,
                    attached_to,
                    producer,
                    schema_url,
                    facet_type,
                    parsed_data,
                    vt,
                    tt,
                )
            else:
                assert schema_id is not None
                resolved_schema_id, json_schema_text = resolve_facet_schema_ref(
                    db, schema_id, org, ns
                )
                facet_id, _ = record_facet_instance_attached_from_store(
                    db,
                    DEFAULT_SOURCE,
                    attached_to,
                    producer,
                    resolved_schema_id,
                    json_schema_text,
                    facet_type,
                    parsed_data,
                    vt,
                    tt,
                )
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.json:
        typer.echo(json.dumps({"facet_id": facet_id, "attached_to": attached_to}))
    else:
        typer.echo(facet_id)


@facet_app.command("list")
def facet_list(
    ctx: typer.Context,
    to: str | None = typer.Option(None, "--to", help="Filter to facets attached to this REF"),
    limit: int = typer.Option(50, "--limit"),
    after: str | None = _AFTER_OPTION,
    valid_from: str | None = _VALID_FROM_OPTION,
    valid_to: str | None = _VALID_TO_OPTION,
    include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    vfrom = _parse_bound("--valid-from", valid_from)
    vto = _parse_bound("--valid-to", valid_to)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        attached_to: str | None = None
        if to is not None:
            try:
                attached_to = resolve_attachment_ref(db, to, org, ns)
            except RepoError as exc:
                _fail(str(exc))
        try:
            rows = list_facet_instances(
                db, attached_to, limit, include_retracted, vfrom, vto, after
            )
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.id:
        for facet_id, *_ in rows:
            typer.echo(facet_id)
    elif output is OutputFormat.json:
        typer.echo(
            json.dumps(
                [
                    {
                        "facet_id": r[0],
                        "facet_type": r[1],
                        "_producer": r[2],
                        "_schemaURL": r[3],
                        "valid_time": _iso(r[4]),
                    }
                    for r in rows
                ]
            )
        )
    else:
        if not rows:
            typer.echo("(no facet instances)")
        for facet_id, facet_type, producer_, schema_url, _vt in rows:
            typer.echo(f"{facet_id}  {facet_type}  producer={producer_}  schema={schema_url}")


@facet_app.command("show")
def facet_show(
    ctx: typer.Context,
    facet_id: str = typer.Argument(..., help="The facet instance's facet_id"),
    events: bool = typer.Option(
        False, "--events", help="Also list events related to this facet instance"
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, _, _ = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        instance = get_facet_instance(db, facet_id)
        if instance is None:
            _fail(f"no facet instance found with facet_id {facet_id!r}")
        attached = lookup_entity(db, instance["attached_to"])
        event_rows = list_events_for_subjects(db, [facet_id]) if events else None
    if output is OutputFormat.id:
        typer.echo(instance["facet_id"])
        return
    if output is OutputFormat.json:
        payload = dict(instance)
        if event_rows is not None:
            payload["events"] = event_rows
        typer.echo(json.dumps(payload))
        return
    attached_desc = (
        f"{attached[0]}  {attached[1]}" if attached is not None else "(edge or unknown entity)"
    )
    typer.echo(f"Facet  {instance['facet_type']}")
    typer.echo(f"facet_id: {instance['facet_id']}")
    typer.echo(f"attached_to: {instance['attached_to']}  ({attached_desc})")
    typer.echo(f"_producer: {instance['_producer']}")
    typer.echo(f"_schemaURL: {instance['_schemaURL']}")
    typer.echo(f"data: {json.dumps(instance['data'], indent=2)}")
    if event_rows is not None:
        _render_events(event_rows)


@facet_app.command("correct")
def facet_correct(
    ctx: typer.Context,
    facet_id: str = typer.Argument(..., help="The facet instance's facet_id"),
    data: str = typer.Option(..., "--data", help="The corrected data: inline JSON or @file"),
    reason: str = _REASON_OPTION,
    facet_type: str | None = typer.Option(
        None, "--type", help="Class name within the schema, if it also changes"
    ),
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    """Replace a facet instance's data, keeping its facet_id and its schema. A facet on the
    wrong entity, or against the wrong schema, is retracted and re-attached instead."""
    db_url, _, _ = _settings(ctx)
    parsed_data = _parse_data(data)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        instance = get_facet_instance(db, facet_id)
        if instance is None:
            _fail(f"no facet instance found with facet_id {facet_id!r}")
        new_type = facet_type or str(instance["facet_type"])
        schema_url = str(instance["_schemaURL"])
        try:
            # Validate against the schema this instance was pinned to, exactly as attach did.
            if schema_url.startswith(SCHEMA_URI_PREFIX):
                stored_id = schema_url[len(SCHEMA_URI_PREFIX) :]
                stored = get_facet_schema(db, stored_id)
                if stored is None:
                    _fail(f"registered schema {stored_id!r} is missing")
                validate_facet_data_from_store(
                    stored_id, json.dumps(stored["json_schema"]), new_type, parsed_data
                )
            else:
                validate_facet_data(schema_url, new_type, parsed_data)
            record_facet_instance_corrected(
                db, DEFAULT_SOURCE, facet_id, new_type, parsed_data, vt, tt, reason
            )
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(facet_id)


@facet_app.command("retract")
def facet_retract(
    ctx: typer.Context,
    facet_id: str = typer.Argument(..., help="The facet instance's facet_id"),
    reason: str = _REASON_OPTION,
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    """Withdraw a facet instance."""
    db_url, _, _ = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        if get_facet_instance(db, facet_id) is None:
            _fail(f"no facet instance found with facet_id {facet_id!r}")
        try:
            record_facet_instance_retracted(db, DEFAULT_SOURCE, facet_id, vt, tt, reason)
        except RepoError as exc:
            _fail(str(exc))
    typer.echo(f"retracted facet {facet_id}")


# --- `facet schema` store ----------------------------------------------------


@facet_schema_app.command("register")
def facet_schema_register(
    ctx: typer.Context,
    local_id: str = typer.Argument(..., help="Local ID, e.g. qc-metrics"),
    file: Path = typer.Option(..., "--file", help="Path to an already-generated JSON Schema"),
    valid_time: str | None = _VALID_TIME_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    _require_local_id(local_id)
    if not file.is_file():
        _fail(f"--file {str(file)!r} does not exist")
    json_schema_text = file.read_text()
    schema_name = build_schema_name(org, ns, local_id)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            schema_id, _ = record_facet_schema_registered(
                db, DEFAULT_SOURCE, schema_name, json_schema_text, vt, tt
            )
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.json:
        typer.echo(json.dumps({"schema_id": schema_id, "schema_name": schema_name}))
    else:
        typer.echo(schema_id)


@facet_schema_app.command("list")
def facet_schema_list(
    ctx: typer.Context,
    name: str | None = typer.Option(
        None, "--name", help="Filter to versions of this schema (REF: local_id or full name)"
    ),
    limit: int = typer.Option(50, "--limit"),
    after: str | None = _AFTER_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    name_filter = None
    if name is not None:
        name_filter = name if NAME_RE.match(name) else build_schema_name(org, ns, name)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            rows = list_facet_schemas(db, name_filter, limit, after)
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.id:
        for schema_id, _ in rows:
            typer.echo(schema_id)
    elif output is OutputFormat.json:
        typer.echo(json.dumps([{"schema_id": r[0], "schema_name": r[1]} for r in rows]))
    else:
        if not rows:
            typer.echo("(no registered schemas)")
        for schema_id, schema_name in rows:
            typer.echo(f"{schema_id}  {schema_name}")


@facet_schema_app.command("show")
def facet_schema_show(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="schema_id, full schema_name, or bare local_id"),
    events: bool = typer.Option(
        False, "--events", help="Also list events related to this schema registration"
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            schema_id, _ = resolve_facet_schema_ref(db, ref, org, ns)
        except RepoError as exc:
            _fail(str(exc))
        schema = get_facet_schema(db, schema_id)
        event_rows = list_events_for_subjects(db, [schema_id]) if events else None
    assert schema is not None
    if output is OutputFormat.id:
        typer.echo(schema["schema_id"])
        return
    if output is OutputFormat.json:
        payload = dict(schema)
        if event_rows is not None:
            payload["events"] = event_rows
        typer.echo(json.dumps(payload))
        return
    typer.echo(f"FacetSchema  {schema['schema_name']}")
    typer.echo(f"schema_id: {schema['schema_id']}")
    typer.echo(f"json_schema: {json.dumps(schema['json_schema'], indent=2)}")
    if event_rows is not None:
        _render_events(event_rows)


# --- `datapoint` --------------------------------------------------------------


@datapoint_app.command("create")
def datapoint_create(
    ctx: typer.Context,
    local_id: str = typer.Argument(..., help="Local ID, e.g. RUN-001-R1-percent-duplication"),
    for_: str = typer.Option(..., "--for", help="REF to the Entity this characterizes"),
    datapoint_type: str = typer.Option(
        ..., "--type", help="CURIE, e.g. openngs-dp:percent_duplication"
    ),
    kind: str = typer.Option(..., "--kind", help="number | text | boolean"),
    value: str = typer.Option(..., "--value"),
    xref: list[str] = typer.Option([], "--xref", help="CURIE, repeatable"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate, don't write"),
    valid_time: str | None = _VALID_TIME_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    _require_local_id(local_id)
    name = build_name(org, ns, "DataPoint", local_id)
    try:
        value_number, value_text, value_boolean = parse_value(kind, value)
    except RepoError as exc:
        _fail(str(exc))
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        existing = find_by_name(db, "DataPoint", name)
        if existing is not None:
            _fail(
                f"DataPoint with name {name!r} already exists "
                f"(internal_id={existing}); give this measurement its own LOCAL_ID"
            )
        try:
            _, target_id = resolve_ref(db, for_, org, ns, ENTITY_TYPES)
        except RepoError as exc:
            _fail(str(exc))

        internal_id = new_id()
        if dry_run:
            typer.echo(f"(dry run) would create DataPoint {name!r} ({internal_id})")
            typer.echo(f"(dry run) would link characterizes -> {target_id}")
            return

        internal_id, _ = record_datapoint_created(
            db,
            DEFAULT_SOURCE,
            name,
            xref,
            datapoint_type,
            kind,
            value_number,
            value_text,
            value_boolean,
            vt,
            tt,
            internal_id=internal_id,
        )
        record_edge_created(
            db, DEFAULT_SOURCE, internal_id, EdgePredicate.characterizes, target_id, vt, tt
        )
    _render_created("DataPoint", internal_id, name, output)


@datapoint_app.command("list")
def datapoint_list(
    ctx: typer.Context,
    for_: str | None = typer.Option(
        None, "--for", help="Filter to DataPoints characterizing this REF"
    ),
    limit: int = typer.Option(50, "--limit"),
    after: str | None = _AFTER_OPTION,
    valid_from: str | None = _VALID_FROM_OPTION,
    valid_to: str | None = _VALID_TO_OPTION,
    include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    vfrom = _parse_bound("--valid-from", valid_from)
    vto = _parse_bound("--valid-to", valid_to)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        target_id: str | None = None
        if for_ is not None:
            try:
                _, target_id = resolve_ref(db, for_, org, ns, ENTITY_TYPES)
            except RepoError as exc:
                _fail(str(exc))
        try:
            rows = list_datapoints(db, target_id, limit, include_retracted, vfrom, vto, after)
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.id:
        for row in rows:
            typer.echo(row["internal_id"])
    elif output is OutputFormat.json:
        typer.echo(json.dumps(rows))
    else:
        if not rows:
            typer.echo("(no DataPoint entries)")
        for row in rows:
            typer.echo(
                f"{row['internal_id']}  {row['name']}  "
                f"{row['datapoint_type']}={datapoint_value(row)}"
            )


@datapoint_app.command("show")
def datapoint_show(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
    edge_limit: int = typer.Option(20, "--edge-limit"),
    events: bool = typer.Option(False, "--events", help="Also list events related to this entity"),
    include_retracted: bool = _INCLUDE_RETRACTED_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, org, ns = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",), include_retracted)
        except RepoError as exc:
            _fail(str(exc))
        row = get_datapoint(db, internal_id, include_retracted)
        assert row is not None
        outgoing_edges, incoming_edges = get_edges(db, internal_id, edge_limit, include_retracted)
        outgoing = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in outgoing_edges]
        incoming = [(e, lookup_entity(db, e.other_id, include_retracted)) for e in incoming_edges]
        event_rows = None
        if events:
            edge_ids = [e.edge_id for e in outgoing_edges] + [e.edge_id for e in incoming_edges]
            event_rows = list_events_for_subjects(db, [internal_id, *edge_ids])
    if output is OutputFormat.id:
        typer.echo(row["internal_id"])
        return
    if output is OutputFormat.json:
        payload = {**row, "value": datapoint_value(row)}
        if event_rows is not None:
            payload["events"] = event_rows
        typer.echo(json.dumps(payload))
        return
    typer.echo(f"DataPoint  {row['name']}")
    typer.echo(f"internal_id: {row['internal_id']}")
    typer.echo(f"valid_time: {_iso(row['valid_time'])}")
    typer.echo(f"datapoint_type: {row['datapoint_type']}")
    typer.echo(f"value ({row['value_kind']}): {datapoint_value(row)}")
    typer.echo("")
    typer.echo("Outgoing:")
    if not outgoing:
        typer.echo("  (none)")
    for e, r in outgoing:
        typer.echo(f"  {e.predicate} → {_fmt_other(r)}")
    typer.echo("")
    typer.echo("Incoming:")
    if not incoming:
        typer.echo("  (none)")
    for e, r in incoming:
        typer.echo(f"  {e.predicate} ← {_fmt_other(r)}")
    if event_rows is not None:
        _render_events(event_rows)


datapoint_xref_app = typer.Typer(no_args_is_help=True)
datapoint_app.add_typer(datapoint_xref_app, name="xref")


@datapoint_xref_app.command("add")
def datapoint_xref_add(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
    xrefs: list[str] = typer.Argument(..., help="One or more CURIEs to add"),
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    """Record one or more further external identifiers for an existing DataPoint."""
    _do_xref_add(ctx, "DataPoint", ref, xrefs, valid_time)


@datapoint_app.command("correct")
def datapoint_correct(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
    reason: str = _REASON_OPTION,
    value: str | None = typer.Option(None, "--value", help="The corrected value"),
    kind: str | None = typer.Option(None, "--kind", help="number | text | boolean"),
    datapoint_type: str | None = typer.Option(None, "--type", help="Corrected CURIE"),
    local_id: str | None = typer.Option(None, "--local-id", help="Replace the local ID"),
    xref: list[str] = typer.Option([], "--xref", help="Replace the whole xref set"),
    clear_xrefs: bool = typer.Option(False, "--clear-xrefs", help="Remove every xref"),
    valid_time: str | None = _VALID_TIME_OPTION,
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    """Correct a DataPoint - most often its value, the archetypal correctable fact."""
    db_url, org, ns = _settings(ctx)
    vt, tt = _resolve_times(valid_time)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            _, internal_id = resolve_ref(db, ref, org, ns, ("DataPoint",))
        except RepoError as exc:
            _fail(str(exc))
        row = get_datapoint(db, internal_id)
        assert row is not None
        _, current_xrefs = entity_state(db, "DataPoint", internal_id)
        new_kind = kind or str(row["value_kind"])
        if value is not None:
            try:
                numeric, text, boolean = parse_value(new_kind, value)
            except RepoError as exc:
                _fail(str(exc))
        elif kind is not None:
            _fail("--kind changes how --value is parsed, so pass --value with it")
        else:
            numeric, text, boolean = row["value_number"], row["value_text"], row["value_boolean"]
        if local_id is not None:
            _require_local_id(local_id)
            name = build_name(org, ns, "DataPoint", local_id)
        else:
            name = str(row["name"])
        new_xrefs = [] if clear_xrefs else (list(xref) if xref else current_xrefs)
        try:
            record_datapoint_corrected(
                db,
                DEFAULT_SOURCE,
                internal_id,
                name,
                new_xrefs,
                datapoint_type or str(row["datapoint_type"]),
                new_kind,
                numeric,
                text,
                boolean,
                vt,
                tt,
                reason,
            )
        except RepoError as exc:
            _fail(str(exc))
    _render_created("DataPoint", internal_id, name, output)


@datapoint_app.command("retract")
def datapoint_retract(
    ctx: typer.Context,
    ref: str = typer.Argument(..., help="internal_id, full name, or bare local_id"),
    reason: str = _REASON_OPTION,
    cascade: bool = typer.Option(
        False, "--cascade", help="Also retract the characterizes edge and any other edge"
    ),
    valid_time: str | None = _VALID_TIME_OPTION,
) -> None:
    """Withdraw a DataPoint. Its characterizes edge is an edge like any other, so a
    DataPoint that still has one needs --cascade."""
    _do_retract(ctx, "DataPoint", ref, reason, cascade, valid_time)


# --- `event` -------------------------------------------------------------------


@event_app.command("list")
def event_list(
    ctx: typer.Context,
    limit: int = typer.Option(50, "--limit"),
    after: str | None = typer.Option(
        None, "--after", help="Continue after this event_id: the last one you processed"
    ),
    event_type: list[str] = typer.Option([], "--type", help="Only these event types, repeatable"),
    source: str | None = typer.Option(
        None, "--source", help="Only events from this producer, e.g. openngs-api"
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    """The log, oldest first. --after makes following it a resumable poll: pass the
    event_id of the last event you handled and you get only what happened since."""
    db_url, _, _ = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            events = list_events(db, limit, after, event_type or None, source)
        except RepoError as exc:
            _fail(str(exc))
    if output is OutputFormat.id:
        for event in events:
            typer.echo(event["event_id"])
    elif output is OutputFormat.json:
        typer.echo(json.dumps(events))
    else:
        if not events:
            typer.echo("(no events)")
        for event in events:
            typer.echo(
                f"{event['event_id']}  {event['type']}  "
                f"valid_time={event['valid_time']}  subject={event['subject']}"
            )


@event_app.command("show")
def event_show(
    ctx: typer.Context,
    event_id: str = typer.Argument(..., help="The event's event_id"),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    db_url, _, _ = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        event = get_event(db, event_id)
    if event is None:
        _fail(f"no event found with event_id {event_id!r}")
    if output is OutputFormat.id:
        typer.echo(event["event_id"])
        return
    if output is OutputFormat.json:
        typer.echo(json.dumps(event))
        return
    typer.echo(f"Event  {event['type']}")
    typer.echo(f"event_id: {event['event_id']}")
    typer.echo(f"source: {event['source']}")
    typer.echo(f"subject: {event['subject']}")
    typer.echo(f"valid_time: {event['valid_time']}")
    typer.echo(f"transaction_time: {event['transaction_time']}")
    typer.echo(f"supersedes: {event['supersedes']}")
    typer.echo(f"supersede_reason: {event['supersede_reason']}")
    typer.echo(f"payload: {json.dumps(event['payload'], indent=2)}")


_HEADER_OPTION = typer.Option(
    [], "--header", help="Extra HTTP header, 'Name: value', repeatable - e.g. an auth token"
)
_TYPE_RELAY_OPTION = typer.Option([], "--type", help="Only these event types, repeatable")


@event_app.command("relay")
def event_relay(
    ctx: typer.Context,
    sink: str = typer.Option("webhook", "--sink", help="'webhook' or 'file'"),
    url: str | None = typer.Option(None, "--url", help="Webhook endpoint, for --sink webhook"),
    path: Path | None = typer.Option(None, "--path", help="JSONL file, for --sink file"),
    state: Path = typer.Option(
        Path("openngs-relay.json"), "--state", help="Where this subscriber's cursor is kept"
    ),
    start: str = typer.Option(
        "now",
        "--start",
        help="On first run only: 'now', 'beginning', or an event_id to resume after",
    ),
    poll_interval: float = typer.Option(5.0, "--poll-interval", help="Seconds between polls"),
    batch_size: int = typer.Option(100, "--batch-size"),
    max_retries: int = typer.Option(5, "--max-retries", help="Retries per event before failing"),
    dead_letter: Path | None = typer.Option(
        None,
        "--dead-letter",
        help="Record undeliverable events here and keep going; without it the relay stops",
    ),
    event_type: list[str] = _TYPE_RELAY_OPTION,
    source: str | None = typer.Option(None, "--source", help="Only events from this producer"),
    once: bool = typer.Option(False, "--once", help="Deliver what is waiting, then exit"),
    header: list[str] = _HEADER_OPTION,
) -> None:
    """Follow the event log and publish each event to a sink.

    The cursor advances only after a sink reports success, so delivery is at-least-once:
    a crash or a failed send re-delivers rather than drops. Consumers deduplicate on the
    CloudEvents `id`, which is the event_id.

    This is a reader. It never writes to the log, and it sees exactly what `event list`
    returns - a sink is never privileged.
    """
    db_url, _, _ = _settings(ctx)
    built: Sink
    if sink == "webhook":
        if url is None:
            _fail("--sink webhook needs --url")
        headers = {}
        for item in header:
            if ":" not in item:
                _fail(f"--header must be 'Name: value', got {item!r}")
            key, _, value = item.partition(":")
            headers[key.strip()] = value.strip()
        built = WebhookSink(url, headers=headers)
    elif sink == "file":
        if path is None:
            _fail("--sink file needs --path")
        built = FileSink(path)
    else:
        _fail(f"unknown sink {sink!r} - expected 'webhook' or 'file'")

    relay_state = RelayState.load(state)
    if not state.exists():
        relay_state.cursor = initial_cursor(db_url, start)
        relay_state.save()
        where = "the beginning of the log" if relay_state.cursor is None else relay_state.cursor
        typer.echo(f"starting from {where}", err=True)

    typer.echo(f"relaying to {built.name}", err=True)
    try:
        delivered = run_relay(
            db_url,
            built,
            relay_state,
            poll_interval=poll_interval,
            batch_size=batch_size,
            max_retries=max_retries,
            dead_letter=dead_letter,
            types=event_type or None,
            source=source,
            once=once,
        )
    except DeliveryError as exc:
        _fail(f"delivery failed and no --dead-letter is set, so nothing was skipped: {exc}")
    except KeyboardInterrupt:
        typer.echo("stopped", err=True)
        return
    finally:
        built.close()
    typer.echo(f"delivered {delivered} events")


@event_app.command("replay")
def event_replay(
    ctx: typer.Context,
    yes: bool = typer.Option(
        False, "--yes", help="Required: confirms you understand this truncates the projection"
    ),
) -> None:
    """Truncate the graph projection and rebuild it from the event log. Never touches the
    event log itself for why this isn't a violation of invariant 1."""
    if not yes:
        _fail(
            "this truncates every projection table and rebuilds it from the event log - "
            "pass --yes to confirm"
        )
    db_url, _, _ = _settings(ctx)
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        count = replay(db)
    typer.echo(f"replayed {count} events")


# --- `ingest manifest`: a sample sheet, applied as one batch -----------------------------


@ingest_app.command("manifest")
def ingest_manifest(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="CSV or TSV manifest; see docs/manifest.md"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Resolve and validate every row, then write nothing"
    ),
    if_exists: str = typer.Option(
        "error",
        "--if-exists",
        help="'error', or 'skip' to reuse rows that already exist, making a rerun safe",
    ),
    delimiter: str | None = typer.Option(
        None, "--delimiter", help="Override the delimiter read from the header line"
    ),
    output: OutputFormat = typer.Option(OutputFormat.table, "--output"),
) -> None:
    """Load a CSV/TSV manifest: one row per entity, edge, datapoint, facet or schema.

    Rows are applied in file order inside a single transaction, so a bad row anywhere
    leaves nothing behind. A row may name something an earlier row created, by local ID.

    Each row carries its own `valid_time`, which is how a sheet exported from a LIMS
    records when things actually happened rather than when the file was loaded.
    """
    if if_exists not in ("error", "skip"):
        _fail(f"--if-exists must be 'error' or 'skip', not {if_exists!r}")
    db_url, org, ns = _settings(ctx)
    try:
        text = path.read_text()
    except OSError as exc:
        _fail(str(exc))
    try:
        parsed = parse_manifest(text, base=path.parent, delimiter=delimiter)
    except BatchShapeError as exc:
        _fail(str(exc))
    if if_exists == "skip":
        # One flag for the whole file, rather than a column per row: a rerun is a property
        # of the invocation, not of any one line. A row asking for it explicitly still wins.
        for op in parsed.operations:
            if op.if_exists == "error":
                op.if_exists = "return"
    with Database.connect(db_url, recorded_by=cli_principal()) as db:
        try:
            results = apply_operations(
                db, org, ns, DEFAULT_SOURCE, parsed.operations, "line", parsed.lines
            )
        except RepoError as exc:
            _fail(str(exc))
        if dry_run:
            # Every row was resolved and written above; take it all back before committing.
            db.rollback()
    if output is OutputFormat.json:
        typer.echo(json.dumps({"applied": 0 if dry_run else len(results), "results": results}))
        return
    verb = "would apply" if dry_run else "applied"
    typer.echo(f"{verb} {len(results)} rows from {path}")


# --- ingest adapter stubs ---------------------------------------------------------------


@ingest_app.command("multiqc")
def ingest_multiqc(path: Path) -> None:
    """Parse a multiqc_data.json into a qc_metrics-shaped facet, once one exists."""
    raise NotImplementedError("multiqc adapter is not yet implemented")


@ingest_app.command("rocrate")
def ingest_rocrate(path: Path) -> None:
    """Consume a Workflow Run RO-Crate into the analysis half of the graph."""
    raise NotImplementedError("rocrate adapter is not yet implemented")


if __name__ == "__main__":
    app()
