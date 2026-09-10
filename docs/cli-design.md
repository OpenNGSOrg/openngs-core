# The `openngs` CLI

Reference for the command-line interface (`src/openngs/cli.py`). The CLI builds and
inspects a lineage graph by hand while enforcing the lineage rules the schema itself
leaves to the writer: which entity types an edge may connect, that a specimen cannot
exist without a subject, and so on. Every write is an event in the append-only log first
and a graph update second, in one transaction.

It is not a bulk loader and not a query engine. Adapters and analytical queries are
separate components.

## Command tree

```
openngs <entity> create LOCAL_ID (--<parent> REF | --no-parent) [--xref CURIE]... [--valid-time ISO8601] [--if-exists ...] [--dry-run] [--output ...]
openngs <entity> list [--<parent> REF] [--limit N] [--after ID] [--without SPEC]... [--valid-from D] [--valid-to D] [--include-retracted] [--output ...]
openngs <entity> show REF [--edge-limit N] [--events] [--include-retracted] [--output ...]
openngs <entity> correct REF --reason TEXT [--local-id ID] [--xref CURIE]... [--clear-xrefs] [--valid-time ISO8601]
openngs <entity> retract REF --reason TEXT [--cascade] [--valid-time ISO8601]
openngs <entity> xref add REF CURIE... [--valid-time ISO8601]

openngs link <predicate> --from REF --to REF [--valid-time ISO8601]
openngs link same-as --from REF --to REF --asserted-by REF --method STR --confidence FLOAT [--valid-time ISO8601]
openngs link retract EDGE_ID --reason TEXT [--valid-time ISO8601]

openngs facet attach --to REF (--schema-url PATH | --schema-id REF) --type CLASS --producer STR --data JSON|@FILE [--valid-time ISO8601]
openngs facet list [--to REF] [--limit N] [--after ID] [--valid-from D] [--valid-to D] [--include-retracted] [--output ...]
openngs facet show FACET_ID [--events] [--output ...]
openngs facet correct FACET_ID --data JSON|@FILE --reason TEXT [--type CLASS] [--valid-time ISO8601]
openngs facet retract FACET_ID --reason TEXT [--valid-time ISO8601]
openngs facet schema register LOCAL_ID --file PATH [--valid-time ISO8601] [--output ...]
openngs facet schema list [--name REF] [--limit N] [--after ID] [--output ...]
openngs facet schema show REF [--events] [--output ...]

openngs datapoint create LOCAL_ID --for REF --type CURIE --kind number|text|boolean --value VALUE [--xref CURIE]... [--valid-time ISO8601] [--output ...]
openngs datapoint list [--for REF] [--limit N] [--after ID] [--valid-from D] [--valid-to D] [--include-retracted] [--output ...]
openngs datapoint show REF [--edge-limit N] [--events] [--include-retracted] [--output ...]
openngs datapoint correct REF --reason TEXT [--value V] [--kind K] [--type CURIE] [--local-id ID] [--xref CURIE]... [--clear-xrefs]
openngs datapoint retract REF --reason TEXT [--cascade] [--valid-time ISO8601]
openngs datapoint xref add REF CURIE... [--valid-time ISO8601]

openngs ingest manifest FILE [--dry-run] [--if-exists skip] [--delimiter C] [--output ...]

openngs event list [--limit N] [--output ...]
openngs event show EVENT_ID [--output ...]
openngs event replay --yes
openngs event relay [--sink webhook|file] [--url URL] [--path FILE] [--state FILE] [--start now|beginning|EVENT_ID] [--poll-interval S] [--max-retries N] [--dead-letter FILE] [--type T]... [--source S] [--header 'N: v']... [--once]
```

`<entity>` is one of `subject`, `specimen`, `extract`, `library`, `pool`,
`sequencing-run`, `data-file`, `analysis-run`, `data-file-set`, `protocol`, `reagent`,
`actor`, `project`, `context`. `datapoint` has the same commands with extra required
options, described below.

`openngs ingest manifest` loads a CSV/TSV sample sheet; see [manifests](manifest.md). The
other `ingest` subcommands are placeholders for the adapters, none of which is implemented
in this release.

## Configuration

| Flag | Environment variable | Meaning |
|---|---|---|
| `--org` | `OPENNGS_ORG` | The org segment of every name; required |
| `--ns` | `OPENNGS_NAMESPACE` | The namespace segment of every name; required |
| *(none)* | `OPENNGS_PRINCIPAL` | Who to record as having made these writes (`Event.recorded_by`); defaults to the operating-system user |
| `--db-url` | `OPENNGS_DB_URL` | `sqlite:///path/to/file.db` or `postgresql://user:pass@host:port/db`; default `sqlite:///openngs.db` |

Org and namespace are used both to build the `name` of every entity you create and to
resolve a bare local ID back to a name.

The CLI has no credential to check: it connects straight to the database, so anyone who
can run it already has full access. `OPENNGS_PRINCIPAL` is therefore provenance rather
than authorization - it says who to record on each event, and defaults to the
operating-system user.

This means the API's authentication ([docs/authentication.md](authentication.md)) does not
constrain the CLI at all. Access to `OPENNGS_DB_URL` is equivalent to full write access,
and file permissions or database credentials are what actually protect the graph.

## References (`REF`)

Every option that names an existing record (`--subject`, `--from`, `--to`, `--for`, a
`show` argument, ...) accepts any of three forms, tried in this order:

1. **An `internal_id`**: a UUIDv7, looked up directly.
2. **A full name**: `openngs://{org}/{ns}/{type}/{local_id}`, looked up exactly.
3. **A bare `local_id`** (`SPEC-001`): the CLI builds the full name from the active org
   and namespace and the entity type the option expects, then looks that up. This is the
   everyday form.

A reference that resolves to nothing, or to the wrong entity type for that option, is an
error with a non-zero exit and a message naming the reference, the expected type, and the
org and namespace used. Two records sharing a bare local ID across candidate types is
reported as ambiguous; use the full name or the `internal_id`.

Facet `--to` additionally accepts a bare `edge_id`, since a facet can attach to an edge
and edges have no name.

## `create`

```
openngs specimen create SPEC-001 --subject SUBJ-001 --xref biosample:SAMN12345678
```

The positional argument is the local ID, whatever your source system already calls the
thing. It must be non-empty and becomes the last segment of the entity's `name`. The
`internal_id` is always generated; it is never accepted as input.

The **required parent option** is the one structural edge an entity cannot exist without.
Everything else attaches afterwards with `link`.

| Entity | Required option → edge | Notes |
|---|---|---|
| `subject` | none | Root of the physical chain |
| `specimen` | `--subject REF` → `derived_from` a `Subject` | |
| `extract` | `--specimen REF` → `derived_from` a `Specimen` | Kit lot, protocol, operator via `link used` |
| `library` | `--extract REF` → `derived_from` an `Extract` | Pool membership via `link part-of` |
| `pool` | none | Members join with `link part-of --from <library> --to <pool>` |
| `sequencing-run` | none | Instrument via `link used --to <actor>` |
| `data-file` | `--produced-by REF` → `produced_by` a `SequencingRun` or `AnalysisRun` | `--derived-from REF`, repeatable, for file-level lineage |
| `analysis-run` | none | Pipeline via `link used --to <protocol>`; inputs via `link used` |
| `data-file-set` | `--produced-by REF` → `produced_by` a `SequencingRun` or `AnalysisRun` | Members join with `link part-of`; a set may be `part_of` another set |
| `protocol` | none | |
| `reagent` | none | A kit **lot**, not a kit type |
| `actor` | none | A human or an instrument |
| `project` | none | |
| `context` | none | Members of any type join with `link part-of` |
| `datapoint` | `--for REF` → `characterizes` any entity | Also requires `--type`, `--kind`, `--value` |

**`--no-parent`** creates the record with no parent edge. It is mutually exclusive with
the parent option, and one of the two is required: leaving both out is an error, so a
forgotten flag can never silently orphan a record. Use it for things that genuinely came
from nothing:

| Case | What it is |
|---|---|
| An extraction blank | an `Extract` with no `Specimen` |
| A mock community or reference material | a `Specimen` with no `Subject` |
| A no-template control | a `Library` with no `Extract` |
| A legacy or externally supplied file | a `DataFile` with no run |

```bash
openngs extract create BLANK-01 --no-parent
openngs link used --from BLANK-01 --to KIT-QIAAMP-LOT-A1
```

That blank is a real `Extract`, so "which extracts used lot A1" reaches it alongside the
real samples, which is the entire reason for tracking controls at all.

**What kind of control it is, is not a core field.** Nothing in the model says "this is a
blank". Attach a facet in your own namespace (`role: blank | mock | ntc |
unknown-provenance`). The alternative, if you would rather have controls traversable as a
group, is a conventional "controls" `Subject` (or `Context`) that every blank and mock
hangs off, which needs no `--no-parent` at all. Both are supported; pick one and be
consistent.

`datapoint create` has no `--no-parent`: a `DataPoint` is a fact *about* something, and
one characterizing nothing has no meaning.

Common options:

- `--xref CURIE`, repeatable. Duplicates are ignored.
- `--valid-time ISO8601`: when this fact was true in the lab. Defaults to now. A value
  without a UTC offset is taken as UTC; one with an offset is converted to UTC.
- `--dry-run`: resolve and validate everything, print what would be written, write
  nothing.
- `--output table|id|json`: `id` prints just the `internal_id`, for shell composition
  (`SUBJ=$(openngs subject create SUBJ-001 --output id)`); `json` prints the created
  record.

### A name identifies one thing

Each entity table has a unique index on `name`, so two believed records of the same type
cannot share one. The CLI checks first so the
usual case gets a helpful message, but the database is what guarantees it: two people, or
two parallel jobs, racing to create the same local ID both pass a client-side check, and
only one of them wins the insert.

There is no override. To record a genuinely different thing, give it its own `LOCAL_ID`. If
it turns out to be the same real-world thing as an existing record, say so with `link
same-as`, which carries who asserted it, how, and with what confidence - the honest version
of what a forced duplicate name used to imply by coincidence.

The index is *partial*: it ignores retracted rows, so retracting a mislabelled specimen
frees its `LOCAL_ID` for the correct one. Two rows can therefore share a name when one of
them is retracted, which `list --include-retracted` will show.

## `list`

```
openngs specimen list [--subject REF] [--valid-from D] [--valid-to D] [--limit N] [--output table|id|json]
```

Lists entities of one type, sorted by name, capped at `--limit` (default 50). Retracted
records are omitted unless `--include-retracted` is passed. Each row carries its
`valid_time`.

**`--valid-from` / `--valid-to`** bound the record's `valid_time`, the lab time of the
event that last set its content. Both bounds are **inclusive**. A bare date means midnight;
a value with no UTC offset is taken as UTC, exactly as `--valid-time` is on writes. They
compose with the parent filter:

```bash
# every specimen collected from this site in summer 2025
openngs specimen list --subject SITE-LAKE-01 --valid-from 2025-06-01 --valid-to 2025-08-31
```

Because the bound is on `valid_time` and not on when OpenNGS learned the fact, a specimen
back-recorded months later still lands in the range for the day it was actually collected.
A corrected record filters on when the correction says the fact was true.

`facet list` and `datapoint list` take the same two options.

**`--without DIRECTION:PREDICATE[:TYPE]`** (repeatable) returns only entities that have
no such edge. OpenNGS stores no status field and no `next_step` edge on purpose, so
process state is *derived*, and this is the shape every "what is waiting" question takes:

```bash
openngs specimen list --without incoming:derived_from:Extract   # awaiting extraction
openngs library list  --without outgoing:part_of                # not yet pooled
openngs data-file-set list --without incoming:used              # no run has consumed it
```

The third part is worth using. "A specimen with no incoming `derived_from`" is not the
same question as "a specimen with no extract": an aliquot is a `Specimen` derived from a
`Specimen`, so a split-but-not-yet-extracted specimen answers the second and not the
first. Naming the far end's type is what makes the query mean what you meant.

A retracted edge never counts, so withdrawing an extract puts its specimen back on the
backlog. Several `--without` options all have to hold. The result is a list like any
other, and it composes with the parent filter, the date range and the cursor.

This stays a question the caller asks and answers for itself. OpenNGS never emits a
readiness signal, which is the line that keeps it out of the workflow-engine business.

**`--after ID`** continues from the last row of the previous page, so a whole table can be
walked in pages of `--limit`:

```bash
PAGE=$(openngs specimen list --limit 100 --output id)
openngs specimen list --limit 100 --after "$(echo "$PAGE" | tail -1)"
```

The cursor is the last row's own id, which every list already prints, so there is no token
to decode. It is a keyset cursor rather than an offset, so inserting rows while you page
does not shift the window and make you skip or repeat a row. An unknown id is an error
rather than an empty page, since a silent empty page would end a paging loop early and look
like the end of the data. `--after` composes with the parent filter and the date range. Entities
with a required parent accept that same option as a filter (`--subject`, `--specimen`,
`--extract`, `--produced-by`); `datapoint list` filters with `--for`. `--output id`
prints one `internal_id` per line, the natural input to a loop of further commands.

There is no filtering by arbitrary edge or by xref. That is a query, not a listing.

## `show`

```
openngs specimen show SPEC-001 [--edge-limit N] [--events] [--output table|id|json]
```

One record in full, with every edge touching it in either direction:

```
Specimen  openngs://acme-genomics/core-lab/specimen/SPEC-001
internal_id: 018f5b2a-0000-7000-8000-c42387ec762e
xrefs: biosample:SAMN12345678

Outgoing:
  derived_from → Subject   openngs://acme-genomics/core-lab/subject/SUBJ-001

Incoming:
  derived_from ← Extract   openngs://acme-genomics/core-lab/extract/EXT-001
```

A `same_as` edge also shows its `asserted_by`, `method`, and `confidence` inline.

- `--edge-limit N` (default 20) caps edges shown per direction, oldest first. It is a
  display cap for readability on heavily connected entities such as a reagent lot used
  by hundreds of extracts.
- `--events` appends the events the log holds about this record: its own creation event,
  every correction and retraction of it, and the creation event of every edge shown.
- `valid_time` is shown for the record itself, so a specimen's collection date is visible
  without `--events`.
- `--include-retracted` also shows records that have been retracted. A retracted record is
  marked `[RETRACTED]` and reports the event that retracted it.
- `--output json` returns the same information structured: `{type, internal_id, name,
  xrefs, outgoing: [...], incoming: [...], events?: [...]}`.

Facets attached to an entity are not shown inline; use `facet list --to REF`.

## `link`

```
openngs link derived-from  --from REF --to REF
openngs link part-of       --from REF --to REF
openngs link used          --from REF --to REF
openngs link produced-by   --from REF --to REF
openngs link characterizes --from REF --to REF
openngs link same-as       --from REF --to REF --asserted-by REF --method STR --confidence FLOAT
```

Creates one edge. Both references must resolve, and the entity types are checked per
predicate:

| Predicate | `--from` must be | `--to` must be |
|---|---|---|
| `derived_from` | any | any |
| `part_of` | any | any |
| `used` | any | `Protocol`, `Reagent`, `Actor`, `DataFile`, `DataFileSet`, `Pool`, or `Library` |
| `produced_by` | any | `SequencingRun` or `AnalysisRun` |
| `characterizes` | `DataPoint` | any |
| `same_as` | any | any |

`derived_from` and `part_of` are deliberately open: the legitimate pairs (specimen from
subject, aliquot from specimen, file from file, library in pool, set in set, subject in
context) are too many to enumerate, and the `create` commands already guarantee the
physical chain's shape.

Two guardrails apply: an edge from a record to itself is refused for every predicate, and
an exact duplicate of an existing edge (same from, predicate, to) is refused for the five
lineage predicates. `same_as` may be asserted more than once for the same pair, because
each assertion is an independent piece of evidence with its own `asserted_by`, `method`,
and `confidence`.

`same_as --asserted-by` must be an `Actor`. `--confidence` is 0 to 1. The assertion's
`asserted_at` is the edge's `--valid-time`.

`link` prints the new `edge_id`, which a facet can attach to.

## `xref add`

```
openngs specimen xref add LK-001 biosample:SAMN12345678 ena:ERS1234567
```

Records further external identifiers for a record that already exists. This is the
everyday case of an accession arriving weeks after submission.

It is **additive, not a correction**: the record was right, it now has one more name, so
no reason is required and nothing is superseded. Each CURIE becomes its own event, all in
one transaction. An identifier the record already has is refused rather than silently
ignored.

To *remove* or *replace* identifiers, use `correct --xref`/`--clear-xrefs` below: that is
a correction, because it says what was there before was wrong.

## `correct` and `retract`

Nothing written is ever edited or deleted. A correction is a new event that supersedes the
last one about that record, and the graph you read is the result of applying them all.

```
openngs specimen correct SPEC-001 --local-id SPEC-002 --reason "mislabelled tube"
openngs specimen retract SPEC-001 --reason "duplicate registration" [--cascade]
openngs link retract <EDGE_ID> --reason "wrong subject"
openngs datapoint correct DP-1 --value 14.7 --reason "re-measured"
openngs facet correct <FACET_ID> --data @qc.json --reason "re-ran fastqc"
```

**`correct`** replaces content; the record stays believed. For an entity that means its
local ID and its xrefs; for a `DataPoint` also its value, kind, and type; for a facet its
data. Because a correction records the record's full new state, anything you do not pass is
read back and kept: `--xref` replaces the whole set, `--clear-xrefs` empties it, and
omitting both keeps what is there. Correcting a local ID frees the old one for reuse.

**`retract`** withdraws a record: it stops appearing in reads, but stays in the database and
in the log, visible with `--include-retracted`. Retracting an entity that still has edges is
refused, naming how many; `--cascade` retracts those edges with it, each as its own event.
Cascade only ever retracts edges, never another entity. A retracted edge frees its
`(from, predicate, to)` triple, so the same relationship can be asserted again.

**`--reason` is required** on every one of these. A correction with no stated reason is
worth no more than the wrong fact it replaces.

A correction can itself be corrected, without limit. What is refused is superseding an
event that something already supersedes, so each record's history stays a single line.

## `facet`

```
openngs facet attach --to REF (--schema-url PATH | --schema-id REF) --type CLASS --producer STR --data JSON|@FILE
openngs facet list [--to REF] [--limit N]
openngs facet show FACET_ID [--events]
```

Attaches a schema-validated object to an entity or an edge. See
`docs/facets/authoring-a-facet.md` for the full walkthrough.

- `--to` is any `REF`, or a bare `edge_id`.
- Exactly one of `--schema-url` (a local path to a JSON Schema file) or `--schema-id` (a
  schema registered with `facet schema register`) says what `--type` is. `--type` names
  a class within that schema.
- `--producer` identifies what wrote the facet, such as a tool name and version.
- `--data` is inline JSON or `@path/to/file.json`.

`--data` is validated against the schema before anything is written; a failure is an
error naming the field. The instance records the exact schema it validated against: the
path, or `openngs-schema://<schema_id>` for a registered schema.

`show` prints the instance's data and resolves what it is attached to.

### `facet schema`

```
openngs facet schema register LOCAL_ID --file PATH
openngs facet schema list [--name REF] [--limit N]
openngs facet schema show REF [--events]
```

Registers a JSON Schema in the database under
`openngs://{org}/{ns}/facet-schema/{LOCAL_ID}`, so a facet's schema does not depend on a
file path that may move or that other machines do not have.

Every registration is a new, immutable version with its own `schema_id`. Registering
again under the same local ID never overwrites. A bare local ID or name in `--schema-id`
or `show` resolves to the newest version; a `schema_id` pins one exact version. An
attached instance always records the exact `schema_id` it validated against.

`register` accepts already-generated JSON Schema, not LinkML source. Generate it first
with `linkml generate json-schema`.

## `datapoint`

```
openngs datapoint create LOCAL_ID --for REF --type CURIE --kind number|text|boolean --value VALUE
openngs datapoint list [--for REF] [--limit N]
openngs datapoint show REF [--edge-limit N] [--events]
```

A single, typed, independently correctable value attached to the entity it describes.

- `--for` is the entity this value characterizes, of any type; it creates the
  `characterizes` edge.
- `--type` is what was measured, as a CURIE. Prefer a term from
  `schema/vocabularies/datapoints.yaml` (`openngs-dp:percent_duplication`); use a vendor
  or institution CURIE otherwise. Not validated against a closed list.
- `--kind` and `--value` together set exactly one typed value. `--value` is always a
  string on the command line; `number` is parsed as a float, `boolean` accepts
  `true`/`false`/`1`/`0`/`yes`/`no`, `text` is stored as given. A mismatch is an error
  before anything is written.

`list` and `show` print the value inline (`openngs-dp:percent_duplication=12.3`).

## `event`

```
openngs event list [--limit N]
openngs event show EVENT_ID
openngs event replay --yes
openngs event relay --sink webhook --url https://consumer.example/openngs
```

The append-only log every write command feeds.

- `list` prints `event_id`, `type`, `valid_time`, and `subject` (the `internal_id`,
  `edge_id`, `facet_id`, or `schema_id` the event concerns), oldest first. `event_id`s
  are UUIDv7, so ID order is creation order.
- `show` prints the full CloudEvents envelope and the payload.
- `replay --yes` truncates every graph table and rebuilds it from the log, in order. It
  never touches the log itself. It requires `--yes`.
- `relay` follows the log and publishes each event to a sink, so a consumer can receive
  rather than poll. The cursor advances only after a sink reports success, which makes
  delivery at-least-once; consumers deduplicate on the CloudEvents `id`. It runs in the
  foreground until stopped, or with `--once` delivers what is waiting and exits. Full
  reference: [event delivery](event-delivery.md), which also explains why it is a separate
  process rather than a hook on the write path.

## `ingest manifest`

```bash
openngs ingest manifest run-2026-09-01.tsv
openngs ingest manifest run.tsv --dry-run
openngs ingest manifest run.tsv --if-exists skip
```

One row per entity, edge, datapoint, facet or schema, applied in file order inside a single
transaction: a bad row anywhere leaves nothing behind, and the error names the line in the
file. Each row carries its own `valid_time`, which is how a sheet exported from a LIMS
records when things actually happened rather than when it was loaded.

`--dry-run` resolves and validates every row against the real database and then rolls back.
`--if-exists skip` reuses rows that already exist, making a rerun safe. `--delimiter`
overrides the one otherwise read from the header line.

The column reference is in [manifests](manifest.md). Rows become the same operations
`POST /batch` takes and are recorded as the same events, so this is a reader, not a
separate way into the graph.

## Timestamps

Every write records two:

- `valid_time`: when the fact was true in the lab. `--valid-time` sets it; it defaults
  to now.
- `transaction_time`: when OpenNGS learned it. Always now; never an input.

Both are stored UTC-aware. A `--valid-time` without an offset is taken as UTC.

## Limits of this release

- **Local schema files only.** `--schema-url` must be a path on this machine; there is
  no fetching of remote schemas. Registering the schema (`facet schema register`) is the
  portable alternative.
- **No reverse membership filters on `list`** (such as "libraries in this pool"). Use
  `show` on the container, or GraphQL.
