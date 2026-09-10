"""Reference resolution, and reads/writes against the graph projection tables
(docs/cli-design.md).

The insert_*/update_*/set_*_retracted functions here write the projection only. Live writes
never call them directly: every client goes through a `record_*` wrapper in events.py (ADR
0013), which emits the event first and then applies it here in the same transaction; replay
applies the log through the same functions.

Every read takes `include_retracted` and defaults to False: a row whose `retracted_at` is
set is no longer believed and is filtered out.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from openngs.model import Edge, EdgePredicate, SameAsEdge
from openngs.store.db import Database

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
NAME_RE = re.compile(r"^openngs://([^/]+)/([^/]+)/([^/]+)/(.+)$")

# CLI noun (also the entity-type segment of `name`) <-> table/Pydantic-class name.
CLI_NAME_TO_TYPE: dict[str, str] = {
    "subject": "Subject",
    "specimen": "Specimen",
    "extract": "Extract",
    "library": "Library",
    "pool": "Pool",
    "sequencing-run": "SequencingRun",
    "data-file": "DataFile",
    "analysis-run": "AnalysisRun",
    "data-file-set": "DataFileSet",
    "protocol": "Protocol",
    "reagent": "Reagent",
    "actor": "Actor",
    "project": "Project",
    "context": "Context",
    "datapoint": "DataPoint",
}
TYPE_TO_CLI_NAME: dict[str, str] = {v: k for k, v in CLI_NAME_TO_TYPE.items()}
ENTITY_TYPES: tuple[str, ...] = tuple(CLI_NAME_TO_TYPE.values())


class RepoError(Exception):
    """A resolution or validation failure meant to be shown to the CLI user."""


class NameTakenError(RepoError):
    """Another believed entity of this type already holds the name.

    Raised by the database's own unique index, not by a check the caller made first
    so it is also what two concurrent writers see when they race.
    """


def iso_timestamp(value: Any) -> Any:
    """Normalize a projection timestamp column for a caller. SQLite returns the exact ISO
    string that was written; Postgres/pg8000 returns a datetime. Every client sees a string,
    the same normalization `events.py` already does for Event rows - otherwise the same
    record serializes differently depending on the backend."""
    return value.isoformat() if isinstance(value, datetime) else value


def valid_time_range(
    db: Database,
    valid_from: datetime | None,
    valid_to: datetime | None,
    column: str = "valid_time",
) -> tuple[str, list[Any]]:
    """A SQL fragment and its parameters restricting rows to a valid_time range.

    Both bounds are inclusive, matching what "--valid-from"/"--valid-to" read as. valid_time
    is the lab time of the event that last set the row's content, so a corrected record
    filters on when the correction says the fact was true, not on when it was first
    recorded."""
    clauses: list[str] = []
    params: list[Any] = []
    if valid_from is not None:
        clauses.append(f" AND {column} >= {db.ph(1)}")
        params.append(db.timestamp(valid_from))
    if valid_to is not None:
        clauses.append(f" AND {column} <= {db.ph(1)}")
        params.append(db.timestamp(valid_to))
    return "".join(clauses), params


@dataclass(frozen=True)
class MissingEdge:
    """ "this entity has no such edge" - the shape every orchestrator sensor is built on.

    OpenNGS stores no status field and no next_step edge on purpose, so process
    state is derived. "Which specimens have no extract yet" is exactly this: a Specimen with
    no incoming derived_from from an Extract. It stays a question the caller asks and
    answers for itself, never a readiness signal OpenNGS emits.
    """

    direction: str  # "incoming" | "outgoing"
    predicate: str
    other_type: str | None = None


def parse_missing_edge(spec: str) -> MissingEdge:
    """Parse "incoming:derived_from" or "incoming:derived_from:Extract".

    The third part matters more than it looks. "A specimen with no incoming derived_from"
    is not the same question as "a specimen with no extract": an aliquot is a Specimen
    derived from a Specimen, so it would answer the first and not the second.
    """
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise RepoError(
            f"--without {spec!r} should be DIRECTION:PREDICATE or DIRECTION:PREDICATE:TYPE, "
            'e.g. "incoming:derived_from:Extract"'
        )
    direction, predicate = parts[0], parts[1]
    other_type = parts[2] if len(parts) == 3 else None
    if direction not in ("incoming", "outgoing"):
        raise RepoError(f"direction {direction!r} should be 'incoming' or 'outgoing'")
    valid = {p.value for p in EdgePredicate}
    if predicate not in valid:
        raise RepoError(f"unknown predicate {predicate!r} - expected one of {sorted(valid)}")
    if other_type is not None and other_type not in ENTITY_TYPES:
        raise RepoError(f"unknown entity type {other_type!r}")
    return MissingEdge(direction, predicate, other_type)


def missing_edge_clauses(
    db: Database, specs: Sequence[MissingEdge], alias: str
) -> tuple[str, list[Any]]:
    """NOT EXISTS per spec, all of which must hold. Retracted edges never count, and a
    retracted far-end entity never satisfies the type constraint: a relationship that is no
    longer believed cannot be what keeps an entity off the backlog."""
    sql = ""
    params: list[Any] = []
    for spec in specs:
        table = "SameAsEdge" if spec.predicate == "same_as" else "Edge"
        near, far = (
            ("object", "edge_subject")
            if spec.direction == "incoming"
            else ("edge_subject", "object")
        )
        join = ""
        if spec.other_type is not None:
            join = (
                f' JOIN "{spec.other_type}" o ON o.internal_id = e2.{far} '
                "AND o.retracted_at IS NULL"
            )
        # same_as rows carry no predicate worth filtering on - the table is the predicate.
        predicate_sql = "" if table == "SameAsEdge" else f" AND e2.predicate = {db.ph(1)}"
        sql += (
            f' AND NOT EXISTS (SELECT 1 FROM "{table}" e2{join} '
            f"WHERE e2.{near} = {alias}.internal_id AND e2.retracted_at IS NULL"
            f"{predicate_sql})"
        )
        if table != "SameAsEdge":
            params.append(spec.predicate)
    return sql, params


def keyset_after(
    db: Database,
    table: str,
    id_column: str,
    after_id: str | None,
    sort_column: str | None = None,
    id_desc: bool = False,
    alias: str = "",
) -> tuple[str, list[Any]]:
    """A SQL fragment continuing a list after the row identified by `after_id`.

    Keyset, not OFFSET: a page stays consistent while rows are being inserted, which OFFSET
    cannot promise. The cursor is simply the last row's own id, so no client ever has to
    decode a token - every list already returns that id on every row.

    The comparison has to match the list's own ORDER BY exactly. Where rows are ordered by
    a non-unique column (entity and DataPoint lists order by `name`, and names are not
    unique - nothing enforces that yet), the id breaks the tie, so the fragment compares
    the pair. The sort value is fetched with a scalar subquery rather than being carried in
    the cursor, which keeps the cursor a plain id. `id_desc` flips the tie-break for lists
    whose id ordering is descending (registered facet schemas, newest version first).
    """
    if after_id is None:
        return "", []
    if db.fetchone(f'SELECT 1 FROM "{table}" WHERE {id_column} = {db.ph(1)}', (after_id,)) is None:
        raise RepoError(
            f"cursor {after_id!r} does not name a {table} row - pass the id of the last row "
            "of the previous page"
        )
    prefix = f"{alias}." if alias else ""
    cmp_id = "<" if id_desc else ">"
    if sort_column is None:
        return f" AND {prefix}{id_column} {cmp_id} {db.ph(1)}", [after_id]
    sub = f'(SELECT {sort_column} FROM "{table}" WHERE {id_column} = {db.ph(1)})'
    return (
        f" AND ({prefix}{sort_column} > {sub} OR ({prefix}{sort_column} = {sub} "
        f"AND {prefix}{id_column} {cmp_id} {db.ph(1)}))",
        [after_id, after_id, after_id],
    )


def believed(include_retracted: bool, joiner: str = "AND", alias: str = "") -> str:
    """SQL fragment restricting a query to rows still believed. `joiner` is
    "AND" when the query already has a WHERE clause, "WHERE" when it doesn't."""
    prefix = f"{alias}." if alias else ""
    return "" if include_retracted else f" {joiner} {prefix}retracted_at IS NULL"


def new_id() -> str:
    return str(uuid.uuid7())


def dedupe_xrefs(xrefs: Sequence[str]) -> list[str]:
    """xrefs are a set in spirit ("many-to-many, additive") but a list in transit - the
    same CURIE given twice (`--xref a:1 --xref a:1`) is harmless intent, not an error, and
    the projection's xrefs table has a (entity, xref) primary key that would otherwise turn
    it into an IntegrityError traceback. First occurrence wins, order preserved."""
    return list(dict.fromkeys(xrefs))


def build_name(org: str, ns: str, entity_type: str, local_id: str) -> str:
    return f"openngs://{org}/{ns}/{TYPE_TO_CLI_NAME[entity_type]}/{local_id}"


def resolve_ref(
    db: Database,
    ref: str,
    org: str,
    ns: str,
    candidate_types: Sequence[str],
    include_retracted: bool = False,
) -> tuple[str, str]:
    """Resolve REF (internal_id, full name, or bare local_id) to (entity_type, internal_id).

    candidate_types is the closed set of entity types this REF is allowed to resolve to -
    a single type for most options (e.g. Specimen's --subject only accepts Subject), or all
    of ENTITY_TYPES for link predicates with no enforced target type.

    A retracted entity does not resolve unless include_retracted is set, so a correction or
    a new record can reuse a retracted name freely.
    """
    filt = believed(include_retracted)
    if UUID_RE.match(ref):
        matches = [
            t
            for t in candidate_types
            if db.fetchone(f'SELECT 1 FROM "{t}" WHERE internal_id = {db.ph(1)}{filt}', (ref,))
        ]
        if not matches:
            raise RepoError(f"no entity found with internal_id {ref!r} among {candidate_types}")
        if len(matches) > 1:
            raise RepoError(
                f"internal_id {ref!r} exists in multiple entity tables {matches} "
                "- this indicates a data integrity problem"
            )
        return matches[0], ref

    name_match = NAME_RE.match(ref)
    if name_match:
        cli_name = name_match.group(3)
        entity_type = CLI_NAME_TO_TYPE.get(cli_name)
        if entity_type is None:
            raise RepoError(f"name {ref!r} has an unrecognized entity-type segment {cli_name!r}")
        if entity_type not in candidate_types:
            raise RepoError(f"{ref!r} is a {entity_type}, expected one of {candidate_types}")
        sql = f'SELECT internal_id FROM "{entity_type}" WHERE name = {db.ph(1)}{filt}'
        row = db.fetchone(sql, (ref,))
        if row is None:
            raise RepoError(f"no {entity_type} found with name {ref!r}")
        return entity_type, row[0]

    matches2: list[tuple[str, str]] = []
    for entity_type in candidate_types:
        name = build_name(org, ns, entity_type, ref)
        sql = f'SELECT internal_id FROM "{entity_type}" WHERE name = {db.ph(1)}{filt}'
        row = db.fetchone(sql, (name,))
        if row is not None:
            matches2.append((entity_type, row[0]))
    if not matches2:
        raise RepoError(
            f"no entity found for local_id {ref!r} among {candidate_types} "
            f"under org={org!r} ns={ns!r}"
        )
    if len(matches2) > 1:
        found_types = [t for t, _ in matches2]
        raise RepoError(
            f"local_id {ref!r} is ambiguous across {found_types} - use the full name or internal_id"
        )
    return matches2[0]


def find_by_name(
    db: Database, entity_type: str, name: str, include_retracted: bool = False
) -> str | None:
    """A retracted entity does not count as holding its name, so the name is free to reuse."""
    sql = f'SELECT internal_id FROM "{entity_type}" WHERE name = {db.ph(1)}'
    sql += believed(include_retracted)
    row = db.fetchone(sql, (name,))
    return row[0] if row is not None else None


def lookup_entity(
    db: Database, internal_id: str, include_retracted: bool = False
) -> tuple[str, str] | None:
    """Probe every entity table for internal_id (Edge.edge_subject/object carry no type column,
    carry no foreign key). Returns (entity_type, name) or None."""
    filt = believed(include_retracted)
    for entity_type in ENTITY_TYPES:
        sql = f'SELECT name FROM "{entity_type}" WHERE internal_id = {db.ph(1)}{filt}'
        row = db.fetchone(sql, (internal_id,))
        if row is not None:
            return entity_type, row[0]
    return None


def entity_retraction(db: Database, entity_type: str, internal_id: str) -> str | None:
    """The retracting event_id if this entity has been retracted, else None."""
    row = db.fetchone(
        f'SELECT retracted_by_event FROM "{entity_type}" WHERE internal_id = {db.ph(1)}',
        (internal_id,),
    )
    return None if row is None else (row[0] or None)


def resolve_attachment_ref(
    db: Database, ref: str, org: str, ns: str, include_retracted: bool = False
) -> str:
    """Resolve a facet's --to REF, which unlike every other REF may name an Edge as well as
    an Entity (a facet's attached_to is "internal_id of the Entity, or edge_id of the Edge",
    per invariant 7). Edges have no name/local_id, only an opaque edge_id, so only the
    internal_id form applies to them. Returns the bare internal_id/edge_id."""
    filt = believed(include_retracted)
    if UUID_RE.match(ref):
        for table in ("Edge", "SameAsEdge"):
            if db.fetchone(f'SELECT 1 FROM "{table}" WHERE edge_id = {db.ph(1)}{filt}', (ref,)):
                return ref
    _, internal_id = resolve_ref(db, ref, org, ns, ENTITY_TYPES, include_retracted)
    return internal_id


def _write_xrefs(db: Database, entity_type: str, internal_id: str, xrefs: Sequence[str]) -> None:
    for xref in dedupe_xrefs(xrefs):
        db.execute(
            f'INSERT INTO "{entity_type}_xrefs" ("{entity_type}_internal_id", xrefs) '
            f"VALUES ({db.ph(2)})",
            (internal_id, xref),
        )


def insert_entity(
    db: Database,
    entity_type: str,
    internal_id: str,
    name: str,
    xrefs: Sequence[str],
    valid_time: datetime,
) -> None:
    try:
        db.execute(
            f'INSERT INTO "{entity_type}" (internal_id, name, valid_time) VALUES ({db.ph(3)})',
            (internal_id, name, valid_time.isoformat()),
        )
    except Exception as exc:
        if not db.is_unique_violation(exc):
            raise
        raise NameTakenError(f"a {entity_type} named {name!r} already exists") from exc
    _write_xrefs(db, entity_type, internal_id, xrefs)


def entity_has_xref(db: Database, entity_type: str, internal_id: str, xref: str) -> bool:
    row = db.fetchone(
        f'SELECT 1 FROM "{entity_type}_xrefs" '
        f'WHERE "{entity_type}_internal_id" = {db.ph(1)} AND xrefs = {db.ph(1)}',
        (internal_id, xref),
    )
    return row is not None


def insert_entity_xref(db: Database, entity_type: str, internal_id: str, xref: str) -> None:
    """Add one external identifier to an entity that already exists. Additive: it does not
    touch the entity's other content, and it is not a correction - the entity
    was right, it now has one more name."""
    db.execute(
        f'INSERT INTO "{entity_type}_xrefs" ("{entity_type}_internal_id", xrefs) '
        f"VALUES ({db.ph(2)})",
        (internal_id, xref),
    )


def update_entity(
    db: Database,
    entity_type: str,
    internal_id: str,
    name: str,
    xrefs: Sequence[str],
    valid_time: datetime,
) -> None:
    """Replace an entity's correctable content in place. The row stays believed;
    the previous content lives in the log. xrefs are replaced wholesale, not merged - the
    correcting event carries the full intended set."""
    try:
        db.execute(
            f'UPDATE "{entity_type}" SET name = {db.ph(1)}, valid_time = {db.ph(1)} '
            f"WHERE internal_id = {db.ph(1)}",
            (name, valid_time.isoformat(), internal_id),
        )
    except Exception as exc:
        if not db.is_unique_violation(exc):
            raise
        raise NameTakenError(
            f"cannot correct to {name!r}: a {entity_type} already has that name"
        ) from exc
    db.execute(
        f'DELETE FROM "{entity_type}_xrefs" WHERE "{entity_type}_internal_id" = {db.ph(1)}',
        (internal_id,),
    )
    _write_xrefs(db, entity_type, internal_id, xrefs)


def set_entity_retracted(
    db: Database, entity_type: str, internal_id: str, retracted_at: datetime, event_id: str
) -> None:
    db.execute(
        f'UPDATE "{entity_type}" SET retracted_at = {db.ph(1)}, retracted_by_event = {db.ph(1)} '
        f"WHERE internal_id = {db.ph(1)}",
        (retracted_at.isoformat(), event_id, internal_id),
    )


def set_edge_retracted(
    db: Database, table: str, edge_id: str, retracted_at: datetime, event_id: str
) -> None:
    """table is "Edge" or "SameAsEdge" - the two are separate tables."""
    db.execute(
        f'UPDATE "{table}" SET retracted_at = {db.ph(1)}, retracted_by_event = {db.ph(1)} '
        f"WHERE edge_id = {db.ph(1)}",
        (retracted_at.isoformat(), event_id, edge_id),
    )


def entity_valid_time(db: Database, entity_type: str, internal_id: str) -> Any:
    row = db.fetchone(
        f'SELECT valid_time FROM "{entity_type}" WHERE internal_id = {db.ph(1)}', (internal_id,)
    )
    return None if row is None else iso_timestamp(row[0])


def entity_state(db: Database, entity_type: str, internal_id: str) -> tuple[str, list[str]]:
    """An entity's current name and xrefs. A correction event carries the entity's full new
    state, so whatever the caller didn't change has to be read back first."""
    row = db.fetchone(
        f'SELECT name FROM "{entity_type}" WHERE internal_id = {db.ph(1)}', (internal_id,)
    )
    if row is None:
        raise RepoError(f"no {entity_type} found with internal_id {internal_id!r}")
    xrefs = [
        r[0]
        for r in db.fetchall(
            f'SELECT xrefs FROM "{entity_type}_xrefs" '
            f'WHERE "{entity_type}_internal_id" = {db.ph(1)}',
            (internal_id,),
        )
    ]
    return str(row[0]), xrefs


def find_edge_table(db: Database, edge_id: str, include_retracted: bool = False) -> str | None:
    """Which of the two edge tables holds this edge_id, or None. Edge and SameAsEdge are
    separate tables, and a caller retracting an edge by id doesn't know which."""
    filt = believed(include_retracted)
    for table in ("Edge", "SameAsEdge"):
        if db.fetchone(f'SELECT 1 FROM "{table}" WHERE edge_id = {db.ph(1)}{filt}', (edge_id,)):
            return table
    return None


def live_edges_touching(db: Database, internal_id: str) -> list[tuple[str, str]]:
    """Every believed edge with this entity at either end, as (table, edge_id). What the
    cascade check on entity retraction counts, and what --cascade retracts."""
    found: list[tuple[str, str]] = []
    for table in ("Edge", "SameAsEdge"):
        for column in ("edge_subject", "object"):
            found += [
                (table, r[0])
                for r in db.fetchall(
                    f'SELECT edge_id FROM "{table}" WHERE {column} = {db.ph(1)} '
                    "AND retracted_at IS NULL ORDER BY edge_id",
                    (internal_id,),
                )
            ]
    return found


def edge_exists(db: Database, subject: str, predicate: EdgePredicate, obj: str) -> bool:
    """Whether an identical (subject, predicate, object) row already exists in "Edge" - the
    same fact stated twice adds nothing to the graph, and shows up as duplicate rows in
    every join against Edge, so record_edge_created refuses it. A retracted edge does not
    count, so the same edge can be asserted again after being withdrawn.
    SameAsEdge is deliberately not covered: two same_as rows for the same pair are two
    independent assertions (their own asserted_by/method/confidence), which invariant 3
    exists to keep distinct."""
    row = db.fetchone(
        f'SELECT 1 FROM "Edge" WHERE edge_subject = {db.ph(1)} AND predicate = {db.ph(1)} '
        f"AND object = {db.ph(1)} AND retracted_at IS NULL",
        (subject, predicate.value, obj),
    )
    return row is not None


def find_edge(db: Database, subject: str, predicate: EdgePredicate, obj: str) -> str | None:
    """The edge_id of a believed edge with this exact triple, or None. What an idempotent
    re-link returns instead of failing on the duplicate check."""
    row = db.fetchone(
        f'SELECT edge_id FROM "Edge" WHERE edge_subject = {db.ph(1)} AND predicate = {db.ph(1)} '
        f"AND object = {db.ph(1)} AND retracted_at IS NULL",
        (subject, predicate.value, obj),
    )
    return None if row is None else str(row[0])


def insert_edge(
    db: Database,
    subject: str,
    predicate: EdgePredicate,
    obj: str,
    valid_time: datetime,
    edge_id: str | None = None,
) -> str:
    edge = Edge(
        edge_id=edge_id or new_id(),
        edge_subject=subject,
        predicate=predicate,
        object=obj,
        valid_time=valid_time,
    )
    db.execute(
        'INSERT INTO "Edge" (edge_id, edge_subject, predicate, object, valid_time) '
        f"VALUES ({db.ph(5)})",
        (
            edge.edge_id,
            edge.edge_subject,
            str(edge.predicate),
            edge.object,
            valid_time.isoformat(),
        ),
    )
    return str(edge.edge_id)


def insert_same_as_edge(
    db: Database,
    subject: str,
    obj: str,
    asserted_by: str,
    method: str,
    confidence: float,
    valid_time: datetime,
    edge_id: str | None = None,
    asserted_at: datetime | None = None,
) -> str:
    edge = SameAsEdge(
        edge_id=edge_id or new_id(),
        edge_subject=subject,
        predicate=EdgePredicate.same_as,
        object=obj,
        asserted_by=asserted_by,
        asserted_at=asserted_at or datetime.now(UTC),
        method=method,
        confidence=confidence,
        valid_time=valid_time,
    )
    # SameAsEdge is a standalone table (LinkML's abstract-class DDL) - it does not
    # also get a row in "Edge".
    db.execute(
        'INSERT INTO "SameAsEdge" (edge_id, edge_subject, predicate, object, asserted_by, '
        "asserted_at, method, confidence, valid_time) "
        f"VALUES ({db.ph(9)})",
        (
            edge.edge_id,
            edge.edge_subject,
            str(edge.predicate),
            edge.object,
            edge.asserted_by,
            edge.asserted_at.isoformat(),
            edge.method,
            edge.confidence,
            valid_time.isoformat(),
        ),
    )
    return str(edge.edge_id)


def list_entities(
    db: Database,
    entity_type: str,
    limit: int,
    parent: tuple[str, str] | None = None,
    include_retracted: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    after: str | None = None,
    without: Sequence[MissingEdge] | None = None,
) -> list[tuple[str, str, Any]]:
    """Returns (internal_id, name, valid_time) rows, ordered by name then internal_id.

    parent, if given, is (predicate, parent_internal_id): filter to rows with an Edge
    edge_subject=<this entity>, predicate=<predicate>, object=<parent_internal_id>.
    valid_from/valid_to bound the row's valid_time inclusively; `after` continues from the
    internal_id of the previous page's last row."""
    # The entity table is aliased "t" in both shapes below, so every fragment can name its
    # columns explicitly. An earlier version rewrote unaliased SQL with str.replace and
    # corrupted the cursor's own subquery, which selects `name` from the same table.
    after_sql, after_params = keyset_after(db, entity_type, "internal_id", after, "name", alias="t")
    without_sql, without_params = missing_edge_clauses(db, without or (), "t")
    if parent is None:
        range_sql, range_params = valid_time_range(db, valid_from, valid_to, "t.valid_time")
        # "WHERE 1=1" so the range and belief fragments can both be plain " AND ..." - the
        # alternative is assembling the first predicate conditionally in two places.
        rows = db.fetchall(
            f'SELECT t.internal_id, t.name, t.valid_time FROM "{entity_type}" t WHERE 1=1'
            f"{believed(include_retracted, alias='t')}{range_sql}{after_sql}{without_sql} "
            f"ORDER BY t.name, t.internal_id LIMIT {db.ph(1)}",
            (*range_params, *after_params, *without_params, limit),
        )
        return [(i, n, iso_timestamp(v)) for i, n, v in rows]
    predicate, parent_id = parent
    range_sql, range_params = valid_time_range(db, valid_from, valid_to, "t.valid_time")
    # DISTINCT: record_edge_created refuses duplicate edges now, but a log written before
    # it did (or replayed from one) can still hold two identical rows - one entity, not two.
    # A retracted edge never joins: the parent relationship it asserted is not believed.
    rows = db.fetchall(
        f'SELECT DISTINCT t.internal_id, t.name, t.valid_time FROM "{entity_type}" t '
        'JOIN "Edge" e ON e.edge_subject = t.internal_id AND e.retracted_at IS NULL '
        f"WHERE e.predicate = {db.ph(1)} AND e.object = {db.ph(1)}"
        f"{believed(include_retracted, 'AND', alias='t')}"
        f"{range_sql}{after_sql}{without_sql} "
        f"ORDER BY t.name, t.internal_id LIMIT {db.ph(1)}",
        (predicate, parent_id, *range_params, *after_params, *without_params, limit),
    )
    return [(i, n, iso_timestamp(v)) for i, n, v in rows]


class EdgeRow:
    __slots__ = ("edge_id", "predicate", "other_id", "asserted_by", "method", "confidence")

    def __init__(
        self,
        edge_id: str,
        predicate: str,
        other_id: str,
        asserted_by: str | None = None,
        method: str | None = None,
        confidence: float | None = None,
    ) -> None:
        self.edge_id = edge_id
        self.predicate = predicate
        self.other_id = other_id
        self.asserted_by = asserted_by
        self.method = method
        self.confidence = confidence


def _same_as_row(r: tuple[Any, ...]) -> EdgeRow:
    return EdgeRow(
        edge_id=r[0],
        predicate="same_as",
        other_id=r[1],
        asserted_by=r[2],
        method=r[3],
        confidence=r[4],
    )


def _merge_by_edge_id(a: list[EdgeRow], b: list[EdgeRow], limit: int) -> list[EdgeRow]:
    """The first `limit` edges in creation order across both tables. edge_id is a UUIDv7,
    so ordering by it is chronological - the same order each per-table query already used."""
    return sorted(a + b, key=lambda e: e.edge_id)[:limit]


def get_edges(
    db: Database, internal_id: str, edge_limit: int, include_retracted: bool = False
) -> tuple[list[EdgeRow], list[EdgeRow]]:
    """Returns (outgoing, incoming), each the first edge_limit edges in creation order
    across both "Edge" (the five non-identity predicates) and "SameAsEdge" (its own table,
    carry no foreign key). Both tables are queried with the same ORDER BY/LIMIT and then merged, so
    a small limit truncates the oldest-first sequence as a whole - it never drops one
    table's rows wholesale just because the other filled the limit on its own."""
    outgoing = [
        EdgeRow(edge_id=r[0], predicate=r[1], other_id=r[2])
        for r in db.fetchall(
            f'SELECT edge_id, predicate, object FROM "Edge" WHERE edge_subject = {db.ph(1)}'
            f"{believed(include_retracted)} ORDER BY edge_id LIMIT {db.ph(1)}",
            (internal_id, edge_limit),
        )
    ]
    incoming = [
        EdgeRow(edge_id=r[0], predicate=r[1], other_id=r[2])
        for r in db.fetchall(
            f'SELECT edge_id, predicate, edge_subject FROM "Edge" WHERE object = {db.ph(1)}'
            f"{believed(include_retracted)} ORDER BY edge_id LIMIT {db.ph(1)}",
            (internal_id, edge_limit),
        )
    ]
    outgoing_same_as = [
        _same_as_row(r)
        for r in db.fetchall(
            'SELECT edge_id, object, asserted_by, method, confidence FROM "SameAsEdge" '
            f"WHERE edge_subject = {db.ph(1)}{believed(include_retracted)} "
            f"ORDER BY edge_id LIMIT {db.ph(1)}",
            (internal_id, edge_limit),
        )
    ]
    incoming_same_as = [
        _same_as_row(r)
        for r in db.fetchall(
            'SELECT edge_id, edge_subject, asserted_by, method, confidence FROM "SameAsEdge" '
            f"WHERE object = {db.ph(1)}{believed(include_retracted)} "
            f"ORDER BY edge_id LIMIT {db.ph(1)}",
            (internal_id, edge_limit),
        )
    ]
    return (
        _merge_by_edge_id(outgoing, outgoing_same_as, edge_limit),
        _merge_by_edge_id(incoming, incoming_same_as, edge_limit),
    )
