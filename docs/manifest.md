# Manifests

A manifest is a CSV or TSV file with one row per thing to record. It exists because most
labs already keep one: a sequencing sample sheet, a LIMS export, a spreadsheet someone
maintains by hand. Loading it is one command.

```bash
openngs ingest manifest run-2026-09-01.tsv
```

Every row in the file is applied in order inside **one transaction**. If any row is wrong,
nothing is written at all, and the error names the line in the file rather than a position
in some internal list.

A manifest is not a separate way into the graph. Each row becomes one of the operations
[`POST /batch`](api-design.md#batch) already takes, applied by the same code, recorded as
the same events. Anything a manifest can do, the CLI and the API can already do one call at
a time; the manifest is for when there are two hundred of them.

## The shape of a file

One column is required: **`kind`**, which says what the row is.

| `kind` | What the row records | Equivalent to |
|---|---|---|
| `entity` | One entity | `openngs specimen create` |
| `edge` | One relationship | `openngs link derived-from` |
| `datapoint` | One measurement | `openngs datapoint create` |
| `facet` | One facet instance | `openngs facet attach` |
| `schema` | One facet schema version | `openngs facet schema register` |

Every other column is read only by the kinds that need it, so one file holds rows of every
kind and each row leaves the columns it does not use blank.

```tsv
kind	type	local_id	parent	from	to	xrefs	valid_time
entity	subject	SUBJ-001				biosample:SAMN12345678	2026-09-01T09:00:00Z
entity	specimen	SPEC-001	SUBJ-001			barcode:TUBE-00417	2026-09-01T10:30:00Z
entity	extract	EXT-001	SPEC-001				2026-09-02T11:00:00Z
entity	actor	NOVASEQ-01
edge	used			EXT-001	NOVASEQ-01
```

[`docs/examples/intake-manifest.tsv`](examples/intake-manifest.tsv) is a complete one: the
intake half of the [worked example](worked-example.md), as a LIMS would export it.

A later row may name something an earlier row created, by its `local_id`, as `SPEC-001`
names `SUBJ-001` above. The earlier write is already visible inside the transaction, so
ordinary reference resolution finds it. Order matters only in that direction: a row cannot
name something created below it.

## Columns

**`type`** is polymorphic, because `kind` decides what it means: an entity noun for an
`entity` row, a predicate for an `edge` row, a datapoint type for a `datapoint` row, a
class name for a `facet` row. A sheet that would rather be explicit can use `entity_type`,
`predicate`, `datapoint_type` or `facet_type` instead, and that column wins where both are
present.

| Column | Used by | Meaning |
|---|---|---|
| `kind` | all | `entity`, `edge`, `datapoint`, `facet`, `schema` |
| `type` | all but `schema` | See above |
| `local_id` | `entity`, `datapoint`, `schema` | The identifier your source system already uses |
| `parent` | `entity` | A reference to the required parent, e.g. the Subject a Specimen came from |
| `no_parent` | `entity` | `true` to record an entity with no parent, where the type allows one |
| `derived_from` | `entity` | One or more references, for an aliquot or a re-derived file |
| `from`, `to` | `edge`, `facet` | The two ends of an edge; `to` alone is a facet's attachment point |
| `asserted_by`, `method`, `confidence` | `edge` | Required for `same_as`, ignored otherwise |
| `for` | `datapoint` | A reference to the entity the measurement describes |
| `value_kind`, `value` | `datapoint` | `number`, `text` or `boolean`, and the value itself |
| `producer`, `schema_url`, `schema_id`, `data` | `facet` | As on `facet attach`; exactly one of the two schema columns |
| `json_schema` | `schema` | The schema document, as JSON |
| `xrefs` | `entity`, `datapoint` | Cross-references as CURIEs |
| `valid_time` | all | When the fact was true in the lab, ISO 8601 |
| `if_exists` | all | `skip` for this row alone, overriding the flag |

Columns OpenNGS does not recognise are ignored, so a LIMS export carrying `operator`,
`rack_position` and `plate_well` loads without editing.

**Multi-valued cells** (`xrefs`, `derived_from`) split on semicolons, commas or spaces,
whichever the sheet happens to use.

**JSON cells** (`data`, `json_schema`) take JSON inline, or `@qc.json` to read it from a
file. That path resolves against the manifest's own directory, not the working directory,
so a sheet and the blobs it points at travel together.

**Blank lines and comment rows are skipped.** A row whose `kind` begins with `#` is a note,
which is how a sheet carries its own documentation.

**`valid_time` is per row**, which is the point of loading a sheet rather than typing the
same facts in later. An export from a LIMS records when each thing actually happened, and
the manifest keeps that rather than stamping everything with the moment it was loaded. A
row with no `valid_time` falls back to the load time, as every other write does.

## Reruns

By default a manifest is loaded once. Loading it again fails on the first row whose
`local_id` is taken, and writes nothing.

```bash
openngs ingest manifest run.tsv --if-exists skip
```

With `--if-exists skip`, a row that already exists is reused instead of failing, so a
resend after a network drop or a half-finished import is safe. "Already exists" is checked
strictly: an entity must have the same parent, and a datapoint must carry the same value.
A row whose name is taken by something genuinely different is still refused, because that
is a correction rather than a repeat, and `openngs <type> correct` is the tool for it.

A `schema` row is a repeat only when the schema document is byte-identical, since
registering a name again is how a new version is made. A `facet` row is always written: a
facet instance has no name to collide on.

```bash
openngs ingest manifest run.tsv --dry-run
```

`--dry-run` resolves and validates every row against the real database, then rolls the
whole thing back. It catches a mistyped parent reference or a facet that fails its schema,
which a parse alone cannot.

## Over HTTP

```
POST /ingest/manifest    {"manifest": "<the file text>", "if_exists": "skip"}    ?dry_run=true
```

The same loader, for a client that has the sheet but not a shell on the server. The
response is the batch response: `applied`, `dry_run`, and one result per row.

`@file` references are **refused** here. A path in a manifest sent over the network would
name a file on the server rather than one the sender can see, so inline the JSON or use the
CLI.

## Errors

A failure names the line, counting the way an editor counts, including the header and any
blank or comment lines:

```
error: line 7 (create): no entity found for local_id 'SUBJ-009' among ('Subject',)
```

| Status | Meaning |
|---|---|
| 422 | The file is malformed: no `kind` column, an unknown `kind`, a `valid_time` that is not ISO 8601, a `data` cell that is not JSON |
| 400 | A row names something that does not exist |
| 409 | A row's `local_id` is already taken |

Nothing is written in any of these cases.
