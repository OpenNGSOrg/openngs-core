# The REST API

Reference for the HTTP interface (`src/openngs/api.py`, FastAPI). It mirrors the CLI's
command surface over HTTP: the same entity create/list/show, `link`, `facet`,
`datapoint`, and `event` operations, against the same database and the same event log.
Every write is an event first and a graph update second, in one transaction.

Interactive documentation (Swagger UI) is served at `/docs`; the GraphQL query API
(`docs/graphql-design.md`) is mounted at `/graphql` in the same server.

## Running it

```bash
export OPENNGS_ORG=acme-genomics
export OPENNGS_NAMESPACE=core-lab
export OPENNGS_DB_URL=sqlite:///openngs.db     # or postgresql://user:pass@host:port/db
make api                                       # http://127.0.0.1:8000
```

Or with Postgres and the MCP server in containers: `make compose-up`
(`CONTAINER_ENGINE=podman` if you do not have Docker). See `docs/getting-started.md`.

## Configuration

The server reads the same three environment variables as the CLI: `OPENNGS_ORG`,
`OPENNGS_NAMESPACE`, `OPENNGS_DB_URL`. One deployment serves one org and namespace; there
is no per-request org or namespace. A missing org or namespace is a 500, since it is a
server misconfiguration rather than a client error.

## Authentication

**A deployment has to choose.** A server with neither tokens configured nor authentication
explicitly disabled refuses every request with a 500 saying which of the two to do. That is
deliberate: this graph carries barcodes, accessions and patient-linked lineage, and
defaulting either way is worse than making someone decide. Defaulting open leaves a
mistyped token path quietly serving everything; defaulting closed with no opt-out would
misrepresent what this release can enforce.

```bash
# tokens: a JSON object of token -> principal
export OPENNGS_AUTH_TOKENS='{"tok-airflow":"airflow","tok-dash":{"principal":"grafana","role":"read"}}'
# or, preferred, since it can be a mounted secret rather than a process-visible env var
export OPENNGS_AUTH_TOKENS_FILE=/run/secrets/openngs-tokens.json
# or, explicitly, no authentication at all - only behind your own gateway
export OPENNGS_AUTH_MODE=none
```

A bare string is shorthand for write access; `{"principal": ..., "role": "read"|"write"}`
spells it out. Requests present `Authorization: Bearer <token>`. A missing or unknown token
is a **401**; a write attempted with a read-only token is a **403**.

Authorization is read versus write, decided by HTTP method. `/graphql` is the one
exception: it is query-only by construction, so it needs only read access even though
every GraphQL query arrives as a POST. `/health` needs no credential and no database.

Only static tokens are supported. Validating an OIDC or JWT credential against a lab's
identity provider is the shape most real deployments will want; the `Principal` seam is
there so adding it changes nothing outside `src/openngs/auth.py`.

**[docs/authentication.md](authentication.md) is the full guide**: generating and rotating
tokens, deployment patterns, and - importantly - what this protects and what it does not.
The CLI bypasses it entirely, and there is no TLS.

**Every event records who made it.** `Event.recorded_by` carries the authenticated
principal, distinct from `source`, which says which program produced the event
(`openngs-api`) rather than who was behind it. With authentication disabled the principal
is `anonymous`, which is an honest answer rather than an invented one.

## References (`REF`)

Every reference in a path or a request body accepts the same three forms as the CLI: an
`internal_id`, a full `openngs://{org}/{ns}/{type}/{local_id}` name, or a bare `local_id`
resolved against the server's org and namespace. Path parameters accept the full-name
form with its slashes.

## Entities

```
POST /{plural}                    create
GET  /{plural}                    list
GET  /{plural}/{ref}              show
POST /{plural}/{ref}/xrefs        add external identifiers
POST /{plural}/{ref}/correct      correct
POST /{plural}/{ref}/retract      retract
GET  /health                      liveness
```

`{plural}` is one of `subjects`, `specimens`, `extracts`, `libraries`, `pools`,
`sequencing-runs`, `data-files`, `analysis-runs`, `data-file-sets`, `protocols`,
`reagents`, `actors`, `projects`, `contexts`. `DataPoint` has its own routes, below.

### `POST /{plural}`

```json
{
  "local_id": "SPEC-001",
  "subject": "SUBJ-001",
  "xrefs": ["biosample:SAMN12345678"],
  "valid_time": "2026-01-15T09:00:00"
}
```

- `local_id`: required, non-empty.
- The **parent field**, present only on entities with a required parent: `subject` on
  specimens, `specimen` on extracts, `extract` on libraries, `produced_by` on data files
  and data file sets. Each route's OpenAPI schema names the field. Exactly one of it and
  `no_parent: true` is required; sending neither is a 422, so an omitted parent can never
  silently orphan a record. `no_parent` is for records that genuinely came from nothing:
  an extraction blank, a mock community, a no-template control, a legacy file. See
  `docs/cli-design.md` for the full list and for how to record what kind of control it is.
- `derived_from`: data files only, a list of `REF`s, default `[]`.
- `xrefs`: optional, default `[]`; duplicates are ignored.
- `valid_time`: optional ISO 8601; defaults to now. A value without an offset is taken
  as UTC.

A name identifies one thing: each entity table has a unique index on `name`, so a
collision is a **409** and there is no override.
The index is partial, ignoring retracted rows, so a retracted name is free to reuse. To
record a genuinely different thing, give it its own `local_id` and assert `same_as` if the
two turn out to be one.

`?if_exists=return` makes the write **idempotent**: if the name is already taken the
existing record is returned with `"created": false`, and no event is emitted, because
nothing happened. A poller that re-sees the same patient, or a task that retries, can send
the same request repeatedly without accumulating duplicates or log noise.

Reuse is not unconditional. If the existing record has a **different parent** than the
request asked for - two subjects' specimens sharing a local ID, say - that is a data
problem, not a repeat, and it is a 409. Silently returning the wrong record would bury it.

A 409 body is structured so a client can act on it without parsing prose:

```json
{"detail": {"detail": "Specimen with name '...' already exists; ...",
            "type": "Specimen", "name": "openngs://...", "internal_id": "018f..."}}
```

`?if_exists=` also works on `POST /links/*` (an edge is its triple, so a repeat is
unambiguous), on `POST /datapoints`, and on `POST /facet-schemas`. Each batch operation
takes it as a body field, which is what makes a whole batch rerunnable.

Response: `{"type": "Specimen", "internal_id": "...", "name": "openngs://..."}`.

### `GET /{plural}`

`?limit=N` (default 50), plus the parent filter on entities that have one, named as in
the create body (`GET /specimens?subject=SUBJ-001`).

`?valid_from=` and `?valid_to=` bound the record's `valid_time` (the lab time of the event
that last set its content). **Both bounds are inclusive.** A bare date means midnight, and
a value with no offset is taken as UTC. They compose with the parent filter:

```
GET /specimens?subject=SITE-LAKE-01&valid_from=2025-06-01&valid_to=2025-08-31
```

`GET /facets` and `GET /datapoints` take the same two parameters.

`?without=DIRECTION:PREDICATE[:TYPE]` (repeatable) returns only entities that have no such
edge, which is how a caller derives process state that OpenNGS deliberately never stores:

```
GET /specimens?without=incoming:derived_from:Extract     # awaiting extraction
GET /data-file-sets?without=incoming:used                # no run has consumed it
```

Name the far end's type where it matters: "no incoming `derived_from`" and "no extract"
are different questions, because an aliquot is a `Specimen` derived from a `Specimen`. A
retracted edge never counts. Several `without` values all have to hold, and a malformed
one is a 400. See `docs/cli-design.md` for the full reasoning.

`?after=<id>` continues from the last row of the previous page. The cursor is that row's
own id, already in the body, so there is no token to decode:

```
GET /specimens?limit=100
GET /specimens?limit=100&after=018f5b2a-0000-7000-8000-c42387ec762e
```

When a page comes back full, the response carries **`X-Next-Cursor`** with the id to pass
next; its absence means this was the last page. A full page is only evidence that there
*may* be more, so the final request can return an empty list. That is the cost of not
counting the whole table on every request.

It is a keyset cursor, not an offset: inserting rows while a client pages does not shift
the window. Entity names are unique among believed records, but the index is
partial, so a retracted row and a live one may share a name; the cursor therefore compares
name and id together, and a page boundary between two such rows neither drops nor repeats
one. An unknown cursor is a **400**, not an empty
page. `?after=` composes with the parent filter and the date range, and `GET /facets`,
`GET /facet-schemas` and `GET /datapoints` all take it.

Response: `[{"internal_id": "...", "name": "...", "valid_time": "..."}, ...]`, sorted by
name then internal_id. All timestamps are ISO 8601 strings in UTC, identical on either
backend.

### `GET /{plural}/{ref}`

`?edge_limit=N` (default 20) caps edges per direction, oldest first. `?events=true` adds
this record's events (its creation event, every correction and retraction of it, and the
creation event of every edge shown). `?include_retracted=true` also returns retracted
records, which carry a `retracted_by_event` field. Every list route takes it too.

```json
{
  "type": "Specimen",
  "internal_id": "018f5b2a-0000-7000-8000-c42387ec762e",
  "name": "openngs://acme-genomics/core-lab/specimen/SPEC-001",
  "valid_time": "2026-01-15T09:00:00+00:00",
  "xrefs": ["biosample:SAMN12345678"],
  "outgoing": [
    {"predicate": "derived_from", "other_type": "Subject", "other_id": "...", "other_name": "openngs://..."}
  ],
  "incoming": [
    {"predicate": "derived_from", "other_type": "Extract", "other_id": "...", "other_name": "openngs://..."}
  ]
}
```

A `same_as` edge also carries `asserted_by`, `method`, and `confidence`. An edge whose
far end is not in any entity table has `other_type` and `other_name` null.

### `POST /{plural}/{ref}/xrefs`

```json
{"xrefs": ["biosample:SAMN12345678", "ena:ERS1234567"], "valid_time": "..."}
```

Adds external identifiers to a record that already exists, the everyday case of an
accession arriving after submission. Additive, not a correction: no reason is required and
nothing is superseded. Each CURIE becomes its own `entity_xref_added` event, all in one
transaction. An identifier the record already has is a **400**; an empty list is a 422.
Removing or replacing identifiers is `POST .../correct` instead.

The response carries the record's full xref set. `POST /datapoints/{ref}/xrefs` is the
same.

### `POST /{plural}/{ref}/correct` and `/retract`

```json
POST /specimens/SPEC-001/correct   {"reason": "mislabelled tube", "local_id": "SPEC-002", "xrefs": ["barcode:B"], "valid_time": "..."}
POST /specimens/SPEC-001/retract   {"reason": "duplicate registration", "cascade": true, "valid_time": "..."}
```

Nothing is ever edited or deleted; both emit an event superseding the last one about that
record. See `docs/cli-design.md` for the semantics.

- `reason` is required and non-empty; omitting it is a 422.
- On `correct`, `local_id` and `xrefs` are both optional but at least one must change, else
  a 400. `xrefs` given replaces the whole set, `[]` clears it, omitted keeps it.
- On `retract`, an entity with live edges is a 400 unless `cascade` is true. The response
  carries `retracted_by_event` and the `retracted_edges` that went with it.

## Links

```
POST /links/derived-from   {"from": REF, "to": REF, "valid_time"?: ISO8601}
POST /links/part-of        {"from": REF, "to": REF, "valid_time"?: ISO8601}
POST /links/used           {"from": REF, "to": REF, "valid_time"?: ISO8601}
POST /links/produced-by    {"from": REF, "to": REF, "valid_time"?: ISO8601}
POST /links/characterizes  {"from": REF, "to": REF, "valid_time"?: ISO8601}
POST /links/same-as        {"from": REF, "to": REF, "asserted_by": REF, "method": str, "confidence": float, "valid_time"?: ISO8601}
```

One route per predicate, so each has an accurate request schema. Entity types are
checked per predicate exactly as the CLI's `link` table in `docs/cli-design.md`
describes: `used` targets a `Protocol`, `Reagent`, `Actor`, `DataFile`,
`DataFileSet`, `Pool`, or `Library`; `produced_by` targets a `SequencingRun` or `AnalysisRun`;
`characterizes` must come from a `DataPoint`; the rest are open. `same_as`'s
`asserted_by` must be an `Actor`, and `confidence` is 0 to 1.

A self-loop, or an exact duplicate of an existing non-`same_as` edge, is a 400.

Response: `{"edge_id": "...", "predicate": "...", "from": "<internal_id>", "to": "<internal_id>"}`,
plus `asserted_by`, `method`, `confidence` for `same_as`.

`POST /links/{edge_id}/retract` with `{"reason": "..."}` withdraws one edge. Both entities
stay; only the relationship stops being believed, and the triple is free to assert again.
An edge id that is not live is a 404.

## Facets

```
POST /facets                     {"to": REF, "schema_url"?: str, "schema_id"?: REF, "type": str, "producer": str, "data": {...}, "valid_time"?: ISO8601}
GET  /facets                     ?to=REF&limit=N
GET  /facets/{facet_id}          ?events=true&include_retracted=true
POST /facets/{facet_id}/correct  {"data": {...}, "reason": str, "type"?: str, "valid_time"?: ISO8601}
POST /facets/{facet_id}/retract  {"reason": str, "valid_time"?: ISO8601}

POST /facet-schemas              {"local_id": str, "json_schema": {...}, "valid_time"?: ISO8601}
GET  /facet-schemas              ?name=REF&limit=N
GET  /facet-schemas/{ref}        ?events=true
```

`POST /facets` requires exactly one of `schema_url` (a JSON Schema file path **on the
server**) or `schema_id` (a registered schema, by `schema_id`, name, or local ID; the
newest version wins for the latter two). `to` is any `REF` or a bare `edge_id`. `data` is
validated against the schema before anything is written; a failure is a 400 naming the
field.

`POST /facet-schemas` takes the JSON Schema document inline. Every registration is a new,
immutable version. `?if_exists=return` returns the version that already holds *identical*
content instead of adding another, so a client that registers its schema on every startup
does not accumulate a version per restart; content that differs is a genuine change and
still registers a new version. `GET /facet-schemas/{ref}` resolves a `schema_id`, a full name, or a
local ID.

## DataPoints

```
POST /datapoints              {"local_id": str, "for": REF, "type": str, "kind": "number"|"text"|"boolean", "value": str, "xrefs"?: [str], "valid_time"?: ISO8601}
GET  /datapoints               ?for=REF&limit=N
GET  /datapoints/{ref}         ?edge_limit=N&events=true&include_retracted=true
POST /datapoints/{ref}/correct {"reason": str, "value"?: str, "kind"?: str, "type"?: str, "local_id"?: str, "xrefs"?: [str]}
POST /datapoints/{ref}/retract {"reason": str, "cascade"?: bool}
```

`value` is always a string on the wire and is parsed according to `kind`, the same rules
as the CLI. A bad kind or unparseable value is a 400. A name collision is a 409, as for
entities.

`?if_exists=return` treats a repeat as idempotent only if it is genuinely the same
measurement: same type, kind, value, and characterized entity. A request with a different
value is a **correction**, not a repeat, and returns a 409 pointing at
`POST /datapoints/{ref}/correct`. A DataPoint is its value, so quietly keeping either the
old or the new one would be wrong.

`GET /datapoints` returns the full row per DataPoint (`internal_id`, `name`,
`datapoint_type`, `value_kind`, `value_number`, `value_text`, `value_boolean`).
`GET /datapoints/{ref}` adds `value` (the one populated field), `outgoing`, and
`incoming`.

`POST /datapoints/{ref}/correct` most often changes `value`. `kind` decides how `value`
parses, so sending `kind` without `value` is a 400. A DataPoint's `characterizes` edge is
an edge like any other, so retracting one needs `cascade`.

Correcting a facet re-validates the new `data` against the schema that instance was pinned
to, whether that was a path or a registered `schema_id`; a failure is a 400.

## Batch

```
POST /batch    {"operations": [ ... ]}    ?dry_run=true
```

Applies an ordered list of operations in **one transaction**: all of them commit, or none
does. Registering one real-world fact is usually several writes - a sequencing run is the
run, its raw output set, a `derived_from` to the pool and a `used` to the instrument - and
over four separate calls a client that fails after the second leaves a half-registered run
behind.

Each operation is `{"op": ...}` plus the fields that operation needs, named as on the
individual routes. `op` is `create`, `link`, `attach_facet`, `create_datapoint` or
`register_schema`. The one difference from the individual routes is that `type` is spelled
out per operation - `entity_type`, `facet_type`, `datapoint_type` - because the three mean
different things.

```json
{"operations": [
  {"op": "create", "entity_type": "pool", "local_id": "POOL-1"},
  {"op": "create", "entity_type": "sequencing-run", "local_id": "RUN-1"},
  {"op": "create", "entity_type": "data-file-set", "local_id": "BCL-1", "parent": "RUN-1"},
  {"op": "link", "predicate": "derived_from", "from": "BCL-1", "to": "POOL-1"}
]}
```

Later operations may name entities created earlier **in the same batch** by local ID, as
above: they are already visible inside the transaction, so ordinary REF resolution finds
them. `entity_type` accepts either the noun a human uses (`sequencing-run`) or the class
name (`SequencingRun`).

Each operation takes its own `if_exists`, applying the same repeat-versus-correction rule
the individual routes use, which is what makes a whole batch rerunnable.

Any failure aborts the whole batch and names the operation by index: a bad reference is a
400, a malformed operation a 422. `?dry_run=true` resolves and validates every operation
and then writes nothing, reporting `"applied": 0` with the results it would have produced.

Batch writes are ordinary events with an ordinary `source`, so a replay reproduces them
like anything else.

## Manifests

```
POST /ingest/manifest    {"manifest": "...", "delimiter": null, "if_exists": "error"}    ?dry_run=true
```

The same operations as `POST /batch`, written as a CSV or TSV spreadsheet instead of JSON,
which is the form a LIMS export or a sequencing sample sheet already arrives in. Rows are
applied in file order in one transaction, and a failure names the line in the file rather
than a position in a list. The response is the batch response.

`if_exists: "skip"` applies `?if_exists=return` to every row, making a resend safe.
`@file` references in a `data` cell are refused over HTTP: the path would name a file on
the server rather than one the sender can see. The column reference is in
[manifests](manifest.md).

## Events

```
GET  /events                  ?limit=N&after=<event_id>&type=<t>&source=<s>
GET  /events/{event_id}
POST /events/replay           ?yes=true
```

**Following the log.** `?after=<event_id>` returns only what happened after that event.
Keep the `event_id` of the last event you processed and pass it back; the response's
`X-Next-Cursor` header carries the id to use next while pages come back full. The log is
append-only, so an event already returned never moves and a new one only ever appears
after the cursor, which is what makes polling correct rather than merely convenient. A
consumer restarting from a stored cursor sees exactly what it missed, once each.

`?type=` (repeatable) and `?source=` narrow the stream, so a consumer interested in one
kind of event need not read and discard the rest. An unknown type is a **400**, not an
empty result: a consumer receiving nothing cannot otherwise distinguish "nothing happened"
from "I asked wrongly". The same applies to an unknown `?after=`.

This is polling, not push. A webhook or broker sink is
[#12](https://github.com/OpenNGSOrg/OpenNGS/issues/12); a cursor is the minimum that makes
polling correct in the meantime.

`GET /events` lists oldest first. `POST /events/replay` truncates every graph table and
rebuilds it from the log; it never touches the log itself and requires `?yes=true`.
Response: `{"replayed": N}`.

All timestamps in responses are ISO 8601 strings in UTC.

## Errors

FastAPI's default `{"detail": ...}` body throughout.

| Status | When |
|---|---|
| 400 | An unknown `?after=` cursor; a reference in the request body does not resolve or is the wrong type; a facet fails validation; a bad `kind`/`value`; a self-loop or duplicate edge; a correction that changes nothing; retracting an entity with live edges without `cascade`; `replay` without `?yes=true` |
| 404 | The `{ref}`, `{facet_id}`, or `{event_id}` in the path does not resolve |
| 409 | A name collision, including one a correction would cause, or an `if_exists=return` whose existing record differs from the request (a different parent, a different DataPoint value). The create body is structured: `detail`, `type`, `name`, `internal_id` |
| 422 | Request-body validation: a missing or empty required field (including an empty `reason`), a malformed `valid_time`, both or neither of `schema_url`/`schema_id` |
| 401 | No bearer token, or an unknown one |
| 403 | A write attempted with a read-only token |
| 500 | `OPENNGS_ORG` or `OPENNGS_NAMESPACE` not set on the server, or no authentication decision made |

Resolution failures do not distinguish "not found" from "ambiguous" or "wrong type" in the
status code; the `detail` message says which.

## Differences from the CLI

- No `dry_run` equivalent.
- `POST /facets` takes `data` inline; there is no `@file` form.
- `POST /facet-schemas` takes the schema document inline, not a file path, since the
  server has no reason to reach the client's filesystem. `schema_url` on `POST /facets`,
  by contrast, is a path on the server, and registering the schema is the portable
  alternative.
- Events written through the API carry `"source": "openngs-api"` in their CloudEvents
  envelope; the CLI writes `"openngs-cli"`.
