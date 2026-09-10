"""Reading a lab's sample sheet into batch operations.

A manifest is a CSV or TSV with one row per thing to record. It is parsed here into the
same `BatchOperation`s `POST /batch` takes, and applied by the same code, so this is a
reader rather than a second write path. See docs/manifest.md for the column reference.

The format is forgiving about columns and strict about content: a sample sheet is usually
exported from a spreadsheet someone else maintains, so unknown columns are ignored, blank
cells mean absent, and blank lines are skipped. An unknown `kind`, a missing required
field, or a malformed value stops the whole file before anything is written.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from openngs.batch import BatchOperation, BatchShapeError

KINDS = ("entity", "edge", "datapoint", "facet", "schema")

#: The column each kind reads its polymorphic type from, in addition to the generic `type`.
#: One sheet holds rows of every kind, so `type` means something different on each line; a
#: sheet that would rather be explicit can name the per-kind column instead.
_TYPE_COLUMN = {
    "entity": "entity_type",
    "edge": "predicate",
    "datapoint": "datapoint_type",
    "facet": "facet_type",
}

_TRUE = {"true", "yes", "y", "1"}


def _split_list(value: str) -> list[str]:
    """Several values in one cell, for `xrefs` and `derived_from`. Semicolons, commas and
    whitespace all separate, because a spreadsheet produces whichever the author typed."""
    return [part for part in value.replace(";", " ").replace(",", " ").split() if part]


def _load_json_cell(value: str, base: Path | None, allow_files: bool) -> Any:
    """A JSON object inline, or `@file.json` beside the manifest.

    A `@` reference resolves against the manifest's own directory rather than the working
    directory: a sample sheet and the QC blobs it points at travel together, and whoever
    runs the import is often somewhere else. `allow_files` is false when the manifest
    arrived over HTTP, where a `@` path would name a file on the server rather than one the
    sender can see.
    """
    if value.startswith("@"):
        if not allow_files:
            raise BatchShapeError(
                f"{value!r} refers to a file, which is only read from a local manifest - "
                "inline the JSON instead"
            )
        target = Path(value[1:])
        if not target.is_absolute() and base is not None:
            target = base / target
        try:
            value = target.read_text()
        except OSError as exc:
            raise BatchShapeError(f"cannot read {value!r}: {exc}") from exc
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise BatchShapeError(f"not valid JSON: {exc}") from exc


def _row_to_operation(row: dict[str, str], base: Path | None, allow_files: bool) -> BatchOperation:
    kind = row.get("kind", "").strip().lower()
    if kind not in KINDS:
        raise BatchShapeError(f"unknown kind {kind!r} - expected one of {', '.join(KINDS)}")

    def cell(*names: str) -> str:
        """The first of these columns that is present and non-empty."""
        for name in names:
            value = row.get(name, "")
            if value.strip():
                return value.strip()
        return ""

    def json_cell(*names: str) -> Any:
        value = cell(*names)
        return _load_json_cell(value, base, allow_files) if value else None

    common: dict[str, Any] = {"if_exists": cell("if_exists") or "error"}
    valid_time = cell("valid_time")
    if valid_time:
        try:
            common["valid_time"] = datetime.fromisoformat(valid_time)
        except ValueError as exc:
            raise BatchShapeError(f"valid_time {valid_time!r} is not ISO 8601: {exc}") from exc
    type_cell = cell(_TYPE_COLUMN.get(kind, "type"), "type")

    fields: dict[str, Any]
    if kind == "entity":
        fields = {
            "op": "create",
            "entity_type": type_cell,
            "local_id": cell("local_id"),
            "parent": cell("parent") or None,
            "no_parent": cell("no_parent").lower() in _TRUE,
            "xrefs": _split_list(cell("xrefs")),
            "derived_from": _split_list(cell("derived_from")),
        }
    elif kind == "edge":
        confidence = cell("confidence")
        try:
            parsed_confidence = float(confidence) if confidence else None
        except ValueError as exc:
            raise BatchShapeError(f"confidence {confidence!r} is not a number") from exc
        fields = {
            "op": "link",
            "predicate": type_cell,
            "from": cell("from"),
            "to": cell("to"),
            "asserted_by": cell("asserted_by") or None,
            "method": cell("method") or None,
            "confidence": parsed_confidence,
        }
    elif kind == "datapoint":
        fields = {
            "op": "create_datapoint",
            "local_id": cell("local_id"),
            "for": cell("for"),
            "datapoint_type": type_cell,
            "kind": cell("value_kind"),
            "value": cell("value"),
            "xrefs": _split_list(cell("xrefs")),
        }
    elif kind == "facet":
        fields = {
            "op": "attach_facet",
            "to": cell("to"),
            "facet_type": type_cell,
            "producer": cell("producer") or None,
            "schema_id": cell("schema_id") or None,
            "schema_url": cell("schema_url") or None,
            "data": json_cell("data"),
        }
    else:
        fields = {
            "op": "register_schema",
            "local_id": cell("local_id"),
            "json_schema": json_cell("json_schema", "data"),
        }
    try:
        return BatchOperation.model_validate(fields | common)
    except ValidationError as exc:
        # A cell whose value the operation model itself rejects, e.g. a `predicate` that is
        # not one of the six. Pydantic's own message names the field and the value.
        raise BatchShapeError(str(exc)) from exc


@dataclass(frozen=True)
class ParsedManifest:
    """The operations a manifest asks for, and the file line each one came from.

    The two are kept alongside each other rather than folded into the operation because an
    operation from a manifest and one from a batch request are the same thing; only the
    error message differs.
    """

    operations: list[BatchOperation] = field(default_factory=list)
    lines: list[int] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.operations)


def parse_manifest(
    text: str,
    base: Path | None = None,
    delimiter: str | None = None,
    allow_files: bool = True,
) -> ParsedManifest:
    """Parse a CSV or TSV manifest into operations, in file order.

    `delimiter` is read from the header when not given, so a file exported as TSV works
    without a flag. `base` is the directory `@file` references resolve against, and
    `allow_files` turns those references off for a manifest that arrived over the network.
    """
    if not text.strip():
        raise BatchShapeError("the manifest is empty")
    if delimiter is None:
        header = text.splitlines()[0]
        delimiter = "\t" if header.count("\t") > header.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    fields = [(name or "").strip() for name in reader.fieldnames or []]
    if "kind" not in fields:
        raise BatchShapeError(
            "the manifest needs a 'kind' column; found " + (", ".join(fields) or "no columns")
        )

    parsed = ParsedManifest()
    for raw in reader:
        # The reader's own line number, not a count of rows: it is what the author sees in
        # their editor, and the two diverge as soon as the sheet has a blank line, which
        # csv skips silently.
        number = reader.line_num
        row = {(k or "").strip(): (v or "") for k, v in raw.items() if k is not None}
        if not any(value.strip() for value in row.values()):
            continue  # a blank line, which spreadsheets add freely
        if row.get("kind", "").lstrip().startswith("#"):
            continue  # a comment row, so a sheet can carry its own notes
        try:
            parsed.operations.append(_row_to_operation(row, base, allow_files))
        except BatchShapeError as exc:
            raise BatchShapeError(f"line {number}: {exc}") from exc
        parsed.lines.append(number)
    if not parsed.operations:
        raise BatchShapeError("the manifest has a header but no rows")
    return parsed
