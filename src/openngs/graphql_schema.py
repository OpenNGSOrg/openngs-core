"""Strawberry GraphQL schema - query-only. Hand-authored
against the store layer, the same relationship `api.py` has to it - not generated from
`schema/openngs.yaml` (`linkml generate graphql` is broken for this schema, and wouldn't
give us the traversal-resolver logic below even if it worked). See
docs/graphql-design.md.

This covers the 14 `EntityConfig`-registered entity types (`entities.py`): a `Node`
interface every one implements, `outgoing`/`incoming` edge traversal, and per-entity
`node`/list/show-shaped `Query` fields - plus `DataPoint` (a
15th `Node` implementor, hand-added since it isn't `EntityConfig`-registered), and
read-only `FacetInstance`/`FacetSchema`/`Event` types matching what's already readable via
REST. `DataPoint` is a `Node`; `FacetInstance`/`FacetSchema`/`Event` are plain types (no
`Node` interface - an event has no `xrefs` or lineage edges of its own, and a facet
instance's identity is a `facet_id`, not part of the closed entity set).

**No `from __future__ import annotations` here, same reason as `api.py`.** The per-entity
`Query` fields are attached via a loop (`_register_entity_query_fields`), and their
resolvers' return-type annotations reference `node_cls` - a loop-local variable, not a
module global. Under postponed evaluation those annotations would be plain strings Strawberry
can't resolve from the function's `__globals__` (it isn't there - it's a closure variable),
the exact failure mode `docs/api-design.md` already documents for `api.py`'s dynamic
per-entity request models. The 14 concrete `Node` subclasses below don't have this problem
(they're real module-level classes, resolvable by name), but the file is simplest kept
consistent throughout rather than mixing conventions within one module.

**`Node.outgoing`/`incoming` return `list["Edge"]` with the quotes kept on purpose** (`#
noqa: UP037` - ruff's "these quotes are unnecessary under this project's Python target"
check is wrong here specifically): `Node` and `Edge` are mutually referential
(`Node.outgoing -> Edge`, `Edge.other -> Node`) and `Edge` is defined textually after `Node`,
so one direction is necessarily a forward reference to a name that doesn't exist yet at
class-body-execution time. Confirmed by running it: Strawberry's resolver introspection
(`inspect.signature(..., eval_str=...)`) evaluates annotations eagerly while building the
field at class-decoration time, not lazily via Python 3.14's PEP 649 default - so even on
3.14, an unquoted `list[Edge]` here raises `NameError: name 'Edge' is not defined` the
moment this module is imported. The quoted form defers resolution to when Strawberry
actually needs it, by which point the whole module has finished loading and `Edge` exists.

**Every resolver opens its own `Database` connection - none of them share one from the
GraphQL context, unlike `api.py`'s REST routes.** Found by hand, not by inspection: an
early version put one `Database` (opened via the same `get_db_ctx` REST already uses) in
`info.context` for the whole request, and a real query against a live server failed with
`sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same
thread`. A REST request handler runs its whole body as one blocking call on one thread; a
GraphQL query does not - Strawberry dispatches each sync resolver to a thread pool
per-field, so sibling/nested fields in one query can land on different threads than
whichever one opened the connection. `context["settings"]` therefore carries just
`(db_url, org, ns)` (`ValidatedSettings`, from `context.py` - validated, no connection
opened), and each resolver does its own `with Database.connect(db_url) as db:` around
whatever it needs - safe under any thread the executor happens to pick, at the cost of one
extra connection open/close per field instead of one per query. Acceptable at the lab scale
the stack rule already accepts recursive-CTE traversal for.
"""

from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.utils.str_converters import to_camel_case

from openngs.context import ReadPrincipal, ValidatedSettings
from openngs.entities import ENTITIES, EntityConfig, parent_field_name
from openngs.store import (
    ENTITY_TYPES,
    Database,
    EdgeRow,
    RepoError,
    build_schema_name,
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
    parse_missing_edge,
    resolve_attachment_ref,
    resolve_facet_schema_ref,
    resolve_ref,
)
from openngs.store.repo import NAME_RE


def _bound(value: str | None) -> datetime | None:
    """A validFrom/validTo argument: an ISO 8601 date or datetime, no offset meaning UTC.
    A String rather than a DateTime scalar, matching how this schema types every other
    timestamp."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _iso(value: Any) -> str:
    """Projection timestamp columns come back as an ISO string from SQLite and a datetime
    from Postgres; GraphQL's String scalar coerces neither on its own."""
    return value.isoformat() if isinstance(value, datetime) else str(value)


@strawberry.interface(
    description="The three-layer identity every OpenNGS entity shares (invariant 4)."
)
class Node:
    internal_id: strawberry.ID
    name: str
    _entity_type: ClassVar[str] = ""  # set by each concrete subclass below

    # strawberry.field(description=...), unlike bare @strawberry.field, isn't typed
    # precisely enough for mypy --strict to see these as anything but untyped decorators -
    # a real gap in strawberry's stubs (verified: bare @strawberry.field passes strict
    # cleanly; adding description= is what triggers it), not something a plugin fixes
    # (tried strawberry.ext.mypy_plugin - no difference). type: ignore is the pragmatic
    # choice: descriptions are genuinely useful in GraphiQL, this exploratory query API's
    # whole reason for existing.
    @strawberry.field(description="CURIEs identifying this entity in external systems")  # type: ignore[untyped-decorator]
    def xrefs(self, info: strawberry.Info) -> list[str]:
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            rows = db.fetchall(
                f'SELECT xrefs FROM "{self._entity_type}_xrefs" '
                f'WHERE "{self._entity_type}_internal_id" = {db.ph(1)}',
                (self.internal_id,),
            )
            return [r[0] for r in rows]

    def _row(self, info: strawberry.Info, column: str) -> Any:
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            row = db.fetchone(
                f'SELECT {column} FROM "{self._entity_type}" WHERE internal_id = {db.ph(1)}',
                (self.internal_id,),
            )
            return None if row is None else row[0]

    @strawberry.field(description="Lab time of the event that last set this row's content")  # type: ignore[untyped-decorator]
    def valid_time(self, info: strawberry.Info) -> str | None:
        value = self._row(info, "valid_time")
        return None if value is None else _iso(value)

    @strawberry.field(description="Transaction time this stopped being believed")  # type: ignore[untyped-decorator]
    def retracted_at(self, info: strawberry.Info) -> str | None:
        value = self._row(info, "retracted_at")
        return None if value is None else _iso(value)

    @strawberry.field(description="event_id of the retraction, if this was retracted")  # type: ignore[untyped-decorator]
    def retracted_by_event(self, info: strawberry.Info) -> str | None:
        value = self._row(info, "retracted_by_event")
        return None if value is None else str(value)

    @strawberry.field(description="Edges where this entity is the subject")  # type: ignore[untyped-decorator]
    def outgoing(
        self, info: strawberry.Info, limit: int = 20, include_retracted: bool = False
    ) -> list["Edge"]:  # noqa: UP037
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            out, _incoming = get_edges(db, self.internal_id, limit, include_retracted)
            return [_to_edge(db, e, include_retracted) for e in out]

    @strawberry.field(description="Edges where this entity is the object")  # type: ignore[untyped-decorator]
    def incoming(
        self, info: strawberry.Info, limit: int = 20, include_retracted: bool = False
    ) -> list["Edge"]:  # noqa: UP037
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            _outgoing, inc = get_edges(db, self.internal_id, limit, include_retracted)
            return [_to_edge(db, e, include_retracted) for e in inc]


@strawberry.type(description="A lineage relationship or identity assertion between two entities.")
class Edge:
    predicate: str
    # Nullable: an edge whose far end has no row in any entity table (a dangling edge -
    # Edge.edge_subject/object carry no FK) resolves to null here, the same way
    # REST's show renders it with other_type/other_name null, rather than erroring out and
    # nulling the whole parent entity along with it.
    other: Node | None
    asserted_by: str | None = strawberry.field(default=None, description="same_as only")
    method: str | None = strawberry.field(default=None, description="same_as only")
    confidence: float | None = strawberry.field(default=None, description="same_as only")


# --- the 14 EntityConfig-registered concrete Node types -----------------------------------


@strawberry.type(name="Subject")
class SubjectNode(Node):
    _entity_type: ClassVar[str] = "Subject"


@strawberry.type(name="Specimen")
class SpecimenNode(Node):
    _entity_type: ClassVar[str] = "Specimen"


@strawberry.type(name="Extract")
class ExtractNode(Node):
    _entity_type: ClassVar[str] = "Extract"


@strawberry.type(name="Library")
class LibraryNode(Node):
    _entity_type: ClassVar[str] = "Library"


@strawberry.type(name="Pool")
class PoolNode(Node):
    _entity_type: ClassVar[str] = "Pool"


@strawberry.type(name="SequencingRun")
class SequencingRunNode(Node):
    _entity_type: ClassVar[str] = "SequencingRun"


@strawberry.type(name="DataFile")
class DataFileNode(Node):
    _entity_type: ClassVar[str] = "DataFile"


@strawberry.type(name="AnalysisRun")
class AnalysisRunNode(Node):
    _entity_type: ClassVar[str] = "AnalysisRun"


@strawberry.type(name="DataFileSet")
class DataFileSetNode(Node):
    _entity_type: ClassVar[str] = "DataFileSet"


@strawberry.type(name="Protocol")
class ProtocolNode(Node):
    _entity_type: ClassVar[str] = "Protocol"


@strawberry.type(name="Reagent")
class ReagentNode(Node):
    _entity_type: ClassVar[str] = "Reagent"


@strawberry.type(name="Actor")
class ActorNode(Node):
    _entity_type: ClassVar[str] = "Actor"


@strawberry.type(name="Project")
class ProjectNode(Node):
    _entity_type: ClassVar[str] = "Project"


@strawberry.type(name="Context")
class ContextNode(Node):
    _entity_type: ClassVar[str] = "Context"


@strawberry.type(name="DataPoint", description="An atomic, independently-correctable fact")
class DataPointNode(Node):
    """Not `EntityConfig`-registered (it needs `datapoint_type`/`value_kind`/one of
    `value_number`/`value_text`/`value_boolean`, which don't fit the generic create/list/show
    shape the other 14 types share - the same reason it keeps its own hand-written CLI/REST
    routes), so unlike those 14 it's added here by hand rather than by the loop below. Still
    a `Node`: `xrefs`/`outgoing`/`incoming` come free from the interface, reading the same
    `DataPoint_xrefs`/`Edge` tables every other entity's do."""

    _entity_type: ClassVar[str] = "DataPoint"
    datapoint_type: str = ""
    value_kind: str = ""
    value_number: float | None = None
    value_text: str | None = None
    value_boolean: bool | None = None

    @strawberry.field(description="The one populated value_number/value_text/value_boolean field")  # type: ignore[untyped-decorator]
    def value(self) -> JSON:
        # JSON is a NewType (a runtime no-op) - wrapping is only to satisfy mypy, which
        # otherwise sees the dict-lookup's plain `float | str | bool | None` union.
        return JSON(
            {
                "number": self.value_number,
                "text": self.value_text,
                "boolean": self.value_boolean,
            }[self.value_kind]
        )


def _datapoint_node_from_row(row: dict[str, Any]) -> DataPointNode:
    return DataPointNode(
        internal_id=strawberry.ID(row["internal_id"]),
        name=row["name"],
        datapoint_type=row["datapoint_type"],
        value_kind=row["value_kind"],
        value_number=row["value_number"],
        value_text=row["value_text"],
        value_boolean=row["value_boolean"],
    )


_NODE_CLASSES: dict[str, type[Node]] = {
    "Subject": SubjectNode,
    "Specimen": SpecimenNode,
    "Extract": ExtractNode,
    "Library": LibraryNode,
    "Pool": PoolNode,
    "SequencingRun": SequencingRunNode,
    "DataFile": DataFileNode,
    "AnalysisRun": AnalysisRunNode,
    "DataFileSet": DataFileSetNode,
    "Protocol": ProtocolNode,
    "Reagent": ReagentNode,
    "Actor": ActorNode,
    "Project": ProjectNode,
    "Context": ContextNode,
}
# The generic top-level `node(ref)` field's candidate set - the store layer's full
# ENTITY_TYPES, i.e. the 14 EntityConfig types plus DataPoint (item 4's addition).
_NODE_ENTITY_TYPES: tuple[str, ...] = (*_NODE_CLASSES.keys(), "DataPoint")


def _node_from_id(db: Database, internal_id: str, include_retracted: bool = False) -> Node | None:
    """None when no entity table holds internal_id - see Edge.other."""
    found = lookup_entity(db, internal_id, include_retracted)
    if found is None:
        return None
    entity_type, name = found
    if entity_type == "DataPoint":
        row = get_datapoint(db, internal_id, include_retracted)
        assert row is not None
        return _datapoint_node_from_row(row)
    cls = _NODE_CLASSES[entity_type]
    return cls(internal_id=strawberry.ID(internal_id), name=name)


def _to_edge(db: Database, e: EdgeRow, include_retracted: bool = False) -> Edge:
    return Edge(
        predicate=e.predicate,
        other=_node_from_id(db, e.other_id, include_retracted),
        asserted_by=e.asserted_by,
        method=e.method,
        confidence=e.confidence,
    )


# --- FacetInstance/FacetSchema/Event (item 4) - not Node implementors: a facet instance's
# identity is a facet_id (not part of the closed entity set), and an event has no xrefs or
# lineage edges of its own -----------------------------------------------------------------


@strawberry.type(name="FacetInstance", description="A non-core facet instance's data")
class FacetInstanceNode:
    facet_id: strawberry.ID
    facet_type: str
    # Names kept exactly as invariant 7 spells them (a single leading underscore is a
    # legal GraphQL Name, just not a *double*-underscore one - those are reserved for
    # introspection) - the same fields REST's own /facets responses use verbatim.
    producer: str = strawberry.field(name="_producer", description="Mandatory per invariant 7")
    schema_url: str = strawberry.field(name="_schemaURL", description="Mandatory per invariant 7")

    # attached_to/data aren't in list_facet_instances' cheap SELECT (mirroring REST's own
    # GET /facets list shape, which omits them too) - lazy fields, fetched only if a caller
    # actually asks, the same "don't pay for what nobody requested" precedent Node.xrefs
    # already set. One redundant extra get_facet_instance call versus REST's single-fetch
    # `show` when both are requested off a facet(facetId) lookup - a fine trade for reusing
    # one row-to-node path across both list and show instead of two.
    @strawberry.field(
        description="internal_id of the Entity, or edge_id of the Edge, this is attached to"
    )  # type: ignore[untyped-decorator]
    def attached_to(self, info: strawberry.Info) -> str:
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            row = get_facet_instance(db, str(self.facet_id))
            assert row is not None
            return str(row["attached_to"])

    @strawberry.field(
        description="This facet's data, already validated against its schema at write time"
    )  # type: ignore[untyped-decorator]
    def data(self, info: strawberry.Info) -> JSON:
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            row = get_facet_instance(db, str(self.facet_id))
            assert row is not None
            return JSON(dict(row["data"]))


def _facet_instance_node_from_list_row(r: tuple[str, str, str, str, Any]) -> FacetInstanceNode:
    return FacetInstanceNode(
        facet_id=strawberry.ID(r[0]), facet_type=r[1], producer=r[2], schema_url=r[3]
    )


def _facet_instance_node_from_full_row(row: dict[str, Any]) -> FacetInstanceNode:
    return FacetInstanceNode(
        facet_id=strawberry.ID(row["facet_id"]),
        facet_type=row["facet_type"],
        producer=row["_producer"],
        schema_url=row["_schemaURL"],
    )


@strawberry.type(
    name="FacetSchema",
    description="A versioned, immutable JSON Schema registered for validation",
)
class FacetSchemaNode:
    schema_id: strawberry.ID
    schema_name: str

    @strawberry.field(description="The registered JSON Schema document")  # type: ignore[untyped-decorator]
    def json_schema(self, info: strawberry.Info) -> JSON:
        db_url, _, _ = info.context["settings"]
        with Database.connect(db_url) as db:
            row = get_facet_schema(db, str(self.schema_id))
            assert row is not None
            return JSON(dict(row["json_schema"]))


@strawberry.type(name="Event", description="One append-only CloudEvents occurrence in the log")
class EventNode:
    event_id: strawberry.ID
    source: str
    type: str
    specversion: str
    subject: str | None
    time: str
    datacontenttype: str | None
    valid_time: str
    transaction_time: str
    supersedes: str | None
    supersede_reason: str | None
    payload: JSON


def _event_node_from_row(row: dict[str, Any]) -> EventNode:
    return EventNode(
        event_id=strawberry.ID(row["event_id"]),
        source=row["source"],
        type=row["type"],
        specversion=row["specversion"],
        subject=row["subject"],
        time=row["time"],
        datacontenttype=row["datacontenttype"],
        valid_time=row["valid_time"],
        transaction_time=row["transaction_time"],
        supersedes=row["supersedes"],
        supersede_reason=row["supersede_reason"],
        payload=JSON(dict(row["payload"])),
    )


# --- top-level Query, one node/list/show trio per entity, plus the generic `node` field --


def _make_query_base() -> type:
    class Query:
        @strawberry.field(description="Look up any entity by REF, regardless of type")  # type: ignore[untyped-decorator]
        def node(
            self, info: strawberry.Info, ref: str, include_retracted: bool = False
        ) -> Node | None:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                try:
                    _, internal_id = resolve_ref(
                        db, ref, org, ns, _NODE_ENTITY_TYPES, include_retracted
                    )
                except RepoError:
                    return None
                return _node_from_id(db, internal_id, include_retracted)

        # --- DataPoint: a Node, but not EntityConfig-registered, so hand-written
        # rather than looped like the 14 below ---------------------------------------------

        @strawberry.field(description="Look up one DataPoint by REF")  # type: ignore[untyped-decorator]
        def datapoint(
            self, info: strawberry.Info, ref: str, include_retracted: bool = False
        ) -> DataPointNode | None:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                try:
                    _, internal_id = resolve_ref(
                        db, ref, org, ns, ("DataPoint",), include_retracted
                    )
                except RepoError:
                    return None
                row = get_datapoint(db, internal_id, include_retracted)
                assert row is not None
                return _datapoint_node_from_row(row)

        @strawberry.field(
            description="List DataPoints, optionally filtered to what they characterize"
        )  # type: ignore[untyped-decorator]
        def datapoints(
            self,
            info: strawberry.Info,
            characterizes: Annotated[
                str | None,
                strawberry.argument(
                    name="for", description="Filter to DataPoints characterizing this REF"
                ),
            ] = None,
            limit: int = 50,
            after: str | None = None,
            include_retracted: bool = False,
            valid_from: str | None = None,
            valid_to: str | None = None,
        ) -> list[DataPointNode]:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                target_id: str | None = None
                if characterizes is not None:
                    try:
                        _, target_id = resolve_ref(db, characterizes, org, ns, ENTITY_TYPES)
                    except RepoError:
                        return []
                rows = list_datapoints(
                    db,
                    target_id,
                    limit,
                    include_retracted,
                    _bound(valid_from),
                    _bound(valid_to),
                    after,
                )
                return [_datapoint_node_from_row(r) for r in rows]

        # --- facet / facet schema -------------------------------------------

        @strawberry.field(description="Show one facet instance by facet_id")  # type: ignore[untyped-decorator]
        def facet(
            self,
            info: strawberry.Info,
            facet_id: strawberry.ID,
            include_retracted: bool = False,
        ) -> FacetInstanceNode | None:
            db_url, _, _ = info.context["settings"]
            with Database.connect(db_url) as db:
                row = get_facet_instance(db, str(facet_id), include_retracted)
                return _facet_instance_node_from_full_row(row) if row is not None else None

        @strawberry.field(
            description="List facet instances, optionally filtered by what they're attached to"
        )  # type: ignore[untyped-decorator]
        def facets(
            self,
            info: strawberry.Info,
            to: str | None = None,
            limit: int = 50,
            after: str | None = None,
            include_retracted: bool = False,
            valid_from: str | None = None,
            valid_to: str | None = None,
        ) -> list[FacetInstanceNode]:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                attached_to: str | None = None
                if to is not None:
                    try:
                        attached_to = resolve_attachment_ref(db, to, org, ns)
                    except RepoError:
                        return []
                rows = list_facet_instances(
                    db,
                    attached_to,
                    limit,
                    include_retracted,
                    _bound(valid_from),
                    _bound(valid_to),
                    after,
                )
                return [_facet_instance_node_from_list_row(r) for r in rows]

        @strawberry.field(description="Look up one registered facet schema by REF")  # type: ignore[untyped-decorator]
        def facet_schema(self, info: strawberry.Info, ref: str) -> FacetSchemaNode | None:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                try:
                    schema_id, _ = resolve_facet_schema_ref(db, ref, org, ns)
                except RepoError:
                    return None
                row = get_facet_schema(db, schema_id)
                assert row is not None
                return FacetSchemaNode(
                    schema_id=strawberry.ID(row["schema_id"]), schema_name=row["schema_name"]
                )

        @strawberry.field(description="List registered facet schemas, optionally filtered by name")  # type: ignore[untyped-decorator]
        def facet_schemas(
            self,
            info: strawberry.Info,
            name: str | None = None,
            limit: int = 50,
            after: str | None = None,
        ) -> list[FacetSchemaNode]:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                name_filter = None
                if name is not None:
                    name_filter = name if NAME_RE.match(name) else build_schema_name(org, ns, name)
                rows = list_facet_schemas(db, name_filter, limit, after)
                return [
                    FacetSchemaNode(schema_id=strawberry.ID(r[0]), schema_name=r[1]) for r in rows
                ]

        # --- event - read-only, no `replay` here: that's a write, and Phase 4 is
        # query-only -------------------------------------------------------------

        @strawberry.field(description="Look up one event by event_id")  # type: ignore[untyped-decorator]
        def event(self, info: strawberry.Info, event_id: strawberry.ID) -> EventNode | None:
            db_url, _, _ = info.context["settings"]
            with Database.connect(db_url) as db:
                row = get_event(db, str(event_id))
                return _event_node_from_row(row) if row is not None else None

        @strawberry.field(
            description="List events, oldest first - optionally filtered to what they concern"
        )  # type: ignore[untyped-decorator]
        def events(
            self,
            info: strawberry.Info,
            ref: Annotated[
                str | None,
                strawberry.argument(
                    description="Filter to events concerning this REF - an entity's own "
                    "events plus any edge touching it (within edgeLimit), or a bare "
                    "edge_id. Unfiltered (the default) walks the whole log; pass `after` "
                    "to resume from the last event you processed."
                ),
            ] = None,
            edge_limit: int = 20,
            limit: int = 50,
            after: str | None = None,
            types: list[str] | None = None,
            source: str | None = None,
        ) -> list[EventNode]:
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                if ref is None:
                    return [
                        _event_node_from_row(r)
                        for r in list_events(db, limit, after, types, source)
                    ]
                try:
                    attached_to = resolve_attachment_ref(db, ref, org, ns)
                except RepoError:
                    return []
                # An entity's related events also include every edge_created/same_as_edge_
                # created event for an edge touching it (that event's own `subject` is the
                # edge_id, not the entity's internal_id) - the same expansion REST's own
                # show(events=true) does via get_edges before calling
                # list_events_for_subjects. A bare edge_id (resolve_attachment_ref's other
                # valid form) has no edges of its own to expand.
                subjects = [attached_to]
                if lookup_entity(db, attached_to) is not None:
                    outgoing, incoming = get_edges(db, attached_to, edge_limit)
                    subjects += [e.edge_id for e in outgoing] + [e.edge_id for e in incoming]
                rows = list_events_for_subjects(db, subjects, after, types, source)
                return [_event_node_from_row(r) for r in rows[:limit]]

    return Query


def _register_entity_query_fields(query_cls: type, cfg: EntityConfig, node_cls: type[Node]) -> None:
    noun = cfg.cli_name.replace("-", "_")
    plural_noun = cfg.plural.replace("-", "_")
    candidate_types = (cfg.type_name,)
    parent = cfg.parent

    def show_resolver(
        self: Any, info: strawberry.Info, ref: str, include_retracted: bool = False
    ) -> node_cls | None:  # type: ignore[valid-type]
        db_url, org, ns = info.context["settings"]
        with Database.connect(db_url) as db:
            try:
                _, internal_id = resolve_ref(db, ref, org, ns, candidate_types, include_retracted)
            except RepoError:
                return None
            row = db.fetchone(
                f'SELECT name FROM "{cfg.type_name}" WHERE internal_id = {db.ph(1)}',
                (internal_id,),
            )
            assert row is not None
            return node_cls(internal_id=strawberry.ID(internal_id), name=row[0])

    # Two differently-named functions assigned to one Any-typed variable, not one name
    # redefined in an if/else - mypy treats same-named conditional defs as overload
    # variants requiring identical signatures, which these deliberately aren't (same
    # pattern cli.py's _build_entity_app already uses for create_no_parent/
    # create_with_parent).
    list_resolver: Any
    if parent is not None:
        # The argument's GraphQL-facing name matches the CLI flag/REST body field for this
        # entity's one parent edge ("subject", "producedBy", ...) - not a generic
        # "parentRef" on every entity, same reasoning api.py's own parent_field_name use
        # documents. camelCased explicitly (to_camel_case, the same conversion Strawberry
        # applies automatically to every *other* name here) since passing an explicit
        # `name=` to strawberry.argument bypasses that automatic conversion - confirmed by
        # querying the live schema and getting `produced_by` back, not `producedBy`.
        parent_arg_name = to_camel_case(parent_field_name(parent))
        ParentRefArg = Annotated[
            str | None,
            strawberry.argument(
                name=parent_arg_name,
                description=f"Filter to entities {parent.predicate} this REF",
            ),
        ]

        def list_resolver_with_parent(
            self: Any,
            info: strawberry.Info,
            parent_ref: ParentRefArg = None,
            limit: int = 50,
            after: str | None = None,
            without: list[str] | None = None,
            include_retracted: bool = False,
            valid_from: str | None = None,
            valid_to: str | None = None,
        ) -> list[node_cls]:  # type: ignore[valid-type]
            db_url, org, ns = info.context["settings"]
            with Database.connect(db_url) as db:
                parent_filter: tuple[str, str] | None = None
                if parent_ref is not None:
                    try:
                        _, parent_id = resolve_ref(db, parent_ref, org, ns, parent.target_types)
                    except RepoError:
                        return []
                    parent_filter = (parent.predicate, parent_id)
                rows = list_entities(
                    db,
                    cfg.type_name,
                    limit,
                    parent_filter,
                    include_retracted,
                    _bound(valid_from),
                    _bound(valid_to),
                    after,
                    [parse_missing_edge(w) for w in without or []],
                )
                return [node_cls(internal_id=strawberry.ID(i), name=n) for i, n, _ in rows]

        list_resolver = list_resolver_with_parent
        list_description = f"List {cfg.type_name} entities, optionally filtered by parent REF"
    else:

        def list_resolver_without_parent(
            self: Any,
            info: strawberry.Info,
            limit: int = 50,
            after: str | None = None,
            without: list[str] | None = None,
            include_retracted: bool = False,
            valid_from: str | None = None,
            valid_to: str | None = None,
        ) -> list[node_cls]:  # type: ignore[valid-type]
            db_url, _, _ = info.context["settings"]
            with Database.connect(db_url) as db:
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
                return [node_cls(internal_id=strawberry.ID(i), name=n) for i, n, _ in rows]

        list_resolver = list_resolver_without_parent
        list_description = f"List {cfg.type_name} entities"

    setattr(
        query_cls,
        noun,
        strawberry.field(show_resolver, description=f"Look up one {cfg.type_name} by REF"),
    )
    setattr(query_cls, plural_noun, strawberry.field(list_resolver, description=list_description))


_QueryBase = _make_query_base()
for _cfg in ENTITIES:
    _register_entity_query_fields(_QueryBase, _cfg, _NODE_CLASSES[_cfg.type_name])
Query = strawberry.type(_QueryBase)


schema = strawberry.Schema(query=Query, types=[*_NODE_CLASSES.values(), DataPointNode])


def get_graphql_context(settings: ValidatedSettings, principal: ReadPrincipal) -> dict[str, Any]:
    """Reading the whole graph in one query is still access, so the context authenticates
    before any resolver runs. It asks for *read* access specifically: this schema has no
    mutations, so a read-only principal is entitled to all of it even though
    every GraphQL query arrives as a POST."""
    return {"settings": settings, "principal": principal}


graphql_router = GraphQLRouter(schema, context_getter=get_graphql_context, graphql_ide="graphiql")
