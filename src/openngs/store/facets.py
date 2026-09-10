"""Generic facet-instance storage and validation, plus the facet schema store
the schema store.

FacetInstance holds any facet whose type isn't a promoted core facet - which right now is
every facet, since none are core. An instance validates against a JSON Schema
that's either a local file (_schemaURL) or a version registered in FacetSchema
and referenced by schema_id - either way, LinkML is the recommended authoring
tool (`linkml generate json-schema your_facet.yaml`), but the runtime dependency here is
only `jsonschema`, not the LinkML generator toolchain.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import jsonschema
from referencing.exceptions import Unresolvable

from openngs.model import FacetInstance
from openngs.store.db import Database
from openngs.store.repo import (
    NAME_RE,
    UUID_RE,
    RepoError,
    believed,
    iso_timestamp,
    keyset_after,
    new_id,
    valid_time_range,
)

SCHEMA_URI_PREFIX = "openngs-schema://"


class FacetValidationError(RepoError):
    """The facet's data doesn't validate against its declared schema."""


def load_json_schema(schema_url: str) -> dict[str, Any]:
    path_str = schema_url[len("file://") :] if schema_url.startswith("file://") else schema_url
    path = Path(path_str)
    if not path.is_file():
        raise RepoError(
            f"_schemaURL {schema_url!r} doesn't resolve to a local file - remote URLs "
            "aren't supported yet"
        )
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise RepoError(f"{schema_url!r} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RepoError(f"{schema_url!r} must contain a JSON Schema object")
    return loaded


def _schema_for_type(schema: dict[str, Any], facet_type: str, schema_ref: str) -> dict[str, Any]:
    """A schema document can define more than one class - find facet_type's definition,
    whether it's the top-level schema itself or one of several under $defs/definitions
    (what LinkML's json-schema generator emits for a multi-class file).

    The class's definition is never pulled out of the document on its own: LinkML emits a
    `$ref: "#/$defs/..."` for every enum-typed or nested-class slot, and a fragment
    validated in isolation can't resolve those (every instance, valid or not, then fails
    with an unresolvable-reference error). Instead the whole defs table stays attached and
    the returned schema is a `$ref` into it, so sibling definitions resolve exactly as they
    would from the document's own root."""
    for defs_key in ("$defs", "definitions"):
        defs = schema.get(defs_key)
        if isinstance(defs, dict) and facet_type in defs:
            target: dict[str, Any] = {"$ref": f"#/{defs_key}/{facet_type}", defs_key: defs}
            if "$schema" in schema:
                target["$schema"] = schema["$schema"]
            return target
    if schema.get("title") == facet_type:
        return schema
    raise RepoError(
        f"facet_type {facet_type!r} not found in schema {schema_ref!r} "
        "(looked in $defs/definitions and the top-level title)"
    )


def _validate_against_schema(
    schema: dict[str, Any], facet_type: str, data: dict[str, Any], schema_ref: str
) -> None:
    target = _schema_for_type(schema, facet_type, schema_ref)
    try:
        jsonschema.validate(instance=data, schema=target)
    except jsonschema.ValidationError as exc:
        raise FacetValidationError(
            f"data does not validate against {facet_type!r} in {schema_ref!r}: {exc.message}"
        ) from exc
    except Unresolvable as exc:
        # A $ref the schema document itself can't satisfy (a typo, or a reference to a
        # remote document - not supported). A problem with the schema, not the
        # data, so RepoError rather than FacetValidationError.
        raise RepoError(
            f"schema {schema_ref!r} has an unresolvable $ref while validating {facet_type!r}: {exc}"
        ) from exc


def validate_facet_data(schema_url: str, facet_type: str, data: dict[str, Any]) -> None:
    """Local-file path."""
    schema = load_json_schema(schema_url)
    _validate_against_schema(schema, facet_type, data, schema_url)


def insert_facet_instance(
    db: Database,
    attached_to: str,
    producer: str,
    schema_url: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    facet_id: str | None = None,
) -> str:
    """Local-file path. See insert_facet_instance_from_store for --schema-id."""
    validate_facet_data(schema_url, facet_type, data)
    return write_facet_instance(
        db, attached_to, producer, schema_url, facet_type, data, valid_time, facet_id
    )


def write_facet_instance(
    db: Database,
    attached_to: str,
    producer: str,
    schema_url: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    facet_id: str | None = None,
) -> str:
    """The unvalidated write both insert_facet_instance* paths end in. Also what replay
    (events.py) calls directly: an event's data was validated when it was recorded, and
    re-validating on replay would make rebuilding the projection depend on a local schema
    file still existing, unchanged, at the path the event named - the exact durability
    problem the schema store exists to solve, and a violation of "the projection is
    rebuildable from the log alone". Live writes must go through insert_facet_instance or
    insert_facet_instance_from_store, never here."""
    instance = FacetInstance(
        facet_id=facet_id or new_id(),
        attached_to=attached_to,
        facet_type=facet_type,
        data=json.dumps(data),
        valid_time=valid_time,
        **{"_producer": producer, "_schemaURL": schema_url},
    )
    db.execute(
        'INSERT INTO "FacetInstance" '
        '(facet_id, facet_type, data, attached_to, _producer, "_schemaURL", valid_time) '
        f"VALUES ({db.ph(7)})",
        (
            instance.facet_id,
            instance.facet_type,
            instance.data,
            instance.attached_to,
            instance.producer,
            instance.schemaURL,
            valid_time.isoformat(),
        ),
    )
    return str(instance.facet_id)


def update_facet_instance(
    db: Database,
    facet_id: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
) -> None:
    """Replace a facet instance's data in place, keeping the same facet_id, so
    anything already referring to this instance still refers to the corrected one.
    attached_to and _schemaURL are not correctable: a facet on the wrong entity, or one
    validated against the wrong schema, is retracted and re-attached instead."""
    ph = db.ph(1)
    db.execute(
        f'UPDATE "FacetInstance" SET facet_type = {ph}, data = {ph}, valid_time = {ph} '
        f"WHERE facet_id = {ph}",
        (facet_type, json.dumps(data), valid_time.isoformat(), facet_id),
    )


def set_facet_instance_retracted(
    db: Database, facet_id: str, retracted_at: datetime, event_id: str
) -> None:
    ph = db.ph(1)
    db.execute(
        f'UPDATE "FacetInstance" SET retracted_at = {ph}, retracted_by_event = {ph} '
        f"WHERE facet_id = {ph}",
        (retracted_at.isoformat(), event_id, facet_id),
    )


def list_facet_instances(
    db: Database,
    attached_to: str | None,
    limit: int,
    include_retracted: bool = False,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
    after: str | None = None,
) -> list[tuple[str, str, str, str, Any]]:
    """Returns (facet_id, facet_type, _producer, _schemaURL, valid_time) rows,
    newest-ID-last."""
    columns = 'facet_id, facet_type, _producer, "_schemaURL", valid_time'
    range_sql, range_params = valid_time_range(db, valid_from, valid_to)
    after_sql, after_params = keyset_after(db, "FacetInstance", "facet_id", after)
    if attached_to is None:
        rows = db.fetchall(
            f'SELECT {columns} FROM "FacetInstance" WHERE 1=1'
            f"{believed(include_retracted)}{range_sql}{after_sql} "
            f"ORDER BY facet_id LIMIT {db.ph(1)}",
            (*range_params, *after_params, limit),
        )
        return [(a, b, c, d, iso_timestamp(v)) for a, b, c, d, v in rows]
    rows = db.fetchall(
        f'SELECT {columns} FROM "FacetInstance" '
        f"WHERE attached_to = {db.ph(1)}{believed(include_retracted)}{range_sql}{after_sql} "
        f"ORDER BY facet_id LIMIT {db.ph(1)}",
        (attached_to, *range_params, *after_params, limit),
    )
    return [(a, b, c, d, iso_timestamp(v)) for a, b, c, d, v in rows]


def get_facet_instance(
    db: Database, facet_id: str, include_retracted: bool = False
) -> dict[str, Any] | None:
    row = db.fetchone(
        'SELECT facet_id, facet_type, data, attached_to, _producer, "_schemaURL", valid_time '
        f'FROM "FacetInstance" WHERE facet_id = {db.ph(1)}{believed(include_retracted)}',
        (facet_id,),
    )
    if row is None:
        return None
    return {
        "facet_id": row[0],
        "facet_type": row[1],
        "data": json.loads(row[2]),
        "attached_to": row[3],
        "_producer": row[4],
        "_schemaURL": row[5],
        "valid_time": iso_timestamp(row[6]),
    }


# --- facet schema store -------------------------------------------------------


def build_schema_name(org: str, ns: str, local_id: str) -> str:
    return f"openngs://{org}/{ns}/facet-schema/{local_id}"


def register_facet_schema(
    db: Database, schema_name: str, json_schema_text: str, schema_id: str | None = None
) -> str:
    """Always inserts a new row - re-registering under an existing schema_name adds a new
    version, it never overwrites."""
    try:
        json.loads(json_schema_text)
    except json.JSONDecodeError as exc:
        raise RepoError(f"not valid JSON: {exc}") from exc
    schema_id = schema_id or new_id()
    db.execute(
        f'INSERT INTO "FacetSchema" (schema_id, schema_name, json_schema) VALUES ({db.ph(3)})',
        (schema_id, schema_name, json_schema_text),
    )
    return schema_id


def resolve_facet_schema_ref(db: Database, ref: str, org: str, ns: str) -> tuple[str, str]:
    """Resolve a --schema-id REF to (schema_id, json_schema_text). An exact schema_id pins
    one version; a bare schema_name or local_id resolves to the newest matching version
    (schema_id sorts chronologically, being UUIDv7) - unlike resolve_ref, multiple matches
    here is the expected shape, not an ambiguity to reject."""
    if UUID_RE.match(ref):
        row = db.fetchone(
            f'SELECT schema_id, json_schema FROM "FacetSchema" WHERE schema_id = {db.ph(1)}',
            (ref,),
        )
        if row is None:
            raise RepoError(f"no registered schema found with schema_id {ref!r}")
        return row[0], row[1]

    name = ref if NAME_RE.match(ref) else build_schema_name(org, ns, ref)
    row = db.fetchone(
        'SELECT schema_id, json_schema FROM "FacetSchema" '
        f"WHERE schema_name = {db.ph(1)} ORDER BY schema_id DESC LIMIT 1",
        (name,),
    )
    if row is None:
        raise RepoError(f"no registered schema found with name {name!r}")
    return row[0], row[1]


def validate_facet_data_from_store(
    schema_id: str, json_schema_text: str, facet_type: str, data: dict[str, Any]
) -> None:
    try:
        schema = json.loads(json_schema_text)
    except json.JSONDecodeError as exc:
        raise RepoError(f"registered schema {schema_id!r} is not valid JSON: {exc}") from exc
    _validate_against_schema(schema, facet_type, data, schema_id)


def insert_facet_instance_from_store(
    db: Database,
    attached_to: str,
    producer: str,
    schema_id: str,
    json_schema_text: str,
    facet_type: str,
    data: dict[str, Any],
    valid_time: datetime,
    facet_id: str | None = None,
) -> str:
    validate_facet_data_from_store(schema_id, json_schema_text, facet_type, data)
    schema_url = f"{SCHEMA_URI_PREFIX}{schema_id}"
    return write_facet_instance(
        db, attached_to, producer, schema_url, facet_type, data, valid_time, facet_id
    )


def list_facet_schemas(
    db: Database, name_filter: str | None, limit: int, after: str | None = None
) -> list[tuple[str, str]]:
    """Returns (schema_id, schema_name) rows, newest-first within a name (schema_id sorts
    chronologically) so every version of the same name is visible, not just the latest.

    The id ordering is descending here, so the cursor's tie-break flips with it."""
    if name_filter is None:
        after_sql, after_params = keyset_after(
            db, "FacetSchema", "schema_id", after, "schema_name", id_desc=True
        )
        return db.fetchall(
            'SELECT schema_id, schema_name FROM "FacetSchema" WHERE 1=1'
            f"{after_sql} ORDER BY schema_name, schema_id DESC LIMIT {db.ph(1)}",
            (*after_params, limit),
        )
    after_sql, after_params = keyset_after(db, "FacetSchema", "schema_id", after, id_desc=True)
    return db.fetchall(
        'SELECT schema_id, schema_name FROM "FacetSchema" '
        f"WHERE schema_name = {db.ph(1)}{after_sql} ORDER BY schema_id DESC LIMIT {db.ph(1)}",
        (name_filter, *after_params, limit),
    )


def get_facet_schema(db: Database, schema_id: str) -> dict[str, Any] | None:
    row = db.fetchone(
        'SELECT schema_id, schema_name, json_schema FROM "FacetSchema" '
        f"WHERE schema_id = {db.ph(1)}",
        (schema_id,),
    )
    if row is None:
        return None
    return {"schema_id": row[0], "schema_name": row[1], "json_schema": json.loads(row[2])}
