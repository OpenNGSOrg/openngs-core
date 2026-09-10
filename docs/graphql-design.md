# The GraphQL API

Reference for the query interface (`src/openngs/graphql_schema.py`,
[Strawberry](https://strawberry.rocks/)). It is **query-only**: every write stays on the
CLI and the REST API. Its purpose is traversal: walking `derived_from`, `part_of`,
`used`, and the rest from any starting entity, arbitrarily deep, in one request, without
knowing the concrete type of what is on the far side of each edge.

It is mounted at `/graphql` in the same server as the REST API (`make api`). GraphiQL, an
interactive query editor with schema documentation, is served at that URL in a browser.

## The `Node` interface

Every entity type implements it:

```graphql
interface Node {
  internalId: ID!
  name: String!
  xrefs: [String!]!
  validTime: String              # lab time of the event that last set this row's content
  retractedAt: String            # null while believed
  retractedByEvent: String
  outgoing(limit: Int! = 20, includeRetracted: Boolean! = false): [Edge!]!
  incoming(limit: Int! = 20, includeRetracted: Boolean! = false): [Edge!]!
}
```

`Subject`, `Specimen`, `Extract`, `Library`, `Pool`, `SequencingRun`, `DataFile`,
`AnalysisRun`, `DataFileSet`, `Protocol`, `Reagent`, `Actor`, `Project`, `Context`, and
`DataPoint` are the concrete types. `DataPoint` adds `datapointType`, `valueKind`,
`valueNumber`, `valueText`, `valueBoolean`, and `value` (whichever one is populated).

`xrefs`, `outgoing`, `incoming`, `validTime`, `retractedAt`, and `retractedByEvent` are
each fetched only when requested.

**Retracted records are invisible by default**, everywhere: a retracted entity resolves to
`null`, is absent from lists, and its edges are gone from traversal. `includeRetracted:
true` on any of the fields below brings them back, and `retractedAt` then says which are
retracted. Corrections need no flag: a corrected record simply reads as its corrected
content.

## `Edge`

```graphql
type Edge {
  predicate: String!
  other: Node          # null only for a dangling edge
  assertedBy: String   # same_as only
  method: String       # same_as only
  confidence: Float    # same_as only
}
```

`other` is the far end of the edge as a `Node`. Request `internalId` and `name` from it
without knowing its type, and use an inline fragment (`... on Library { ... }`) to ask for
type-specific fields or to keep walking from there. `limit` on `outgoing`/`incoming`
caps edges per direction, oldest first.

`other` is null only when an edge points at an `internal_id` no entity table holds, which
the schema permits since edges carry no foreign key.

## `Query`

```graphql
node(ref: String!, includeRetracted: Boolean! = false): Node       # any type
subject(ref: String!, includeRetracted: Boolean! = false): Subject  # one pair per entity
subjects(limit: Int! = 50, after: String, includeRetracted: Boolean! = false,
         validFrom: String, validTo: String): [Subject!]!
specimen(ref: String!, includeRetracted: Boolean! = false): Specimen
specimens(subject: String, limit: Int! = 50, after: String, without: [String!],
          includeRetracted: Boolean! = false,
          validFrom: String, validTo: String): [Specimen!]!
# ... and so on for every entity, each with its own parent-filter argument

datapoint(ref: String!, includeRetracted: Boolean! = false): DataPoint
datapoints(for: String, limit: Int! = 50, includeRetracted: Boolean! = false): [DataPoint!]!

facet(facetId: ID!, includeRetracted: Boolean! = false): FacetInstance
facets(to: String, limit: Int! = 50, includeRetracted: Boolean! = false): [FacetInstance!]!
facetSchema(ref: String!): FacetSchema
facetSchemas(name: String, limit: Int! = 50): [FacetSchema!]!

event(eventId: ID!): Event
events(ref: String, edgeLimit: Int! = 20, limit: Int! = 50,
       after: String, types: [String!], source: String): [Event!]!
```

- `ref` accepts the same three forms as everywhere else: `internal_id`, full name, or
  bare local ID against the server's org and namespace. `node(ref:)` resolves against
  every type; the typed fields resolve against one.
- A `ref` that does not resolve returns `null` for a single-item field and `[]` for a
  list, not an error.
- List fields filter by the entity's required parent, named as in the CLI and REST
  (`subject`, `specimen`, `extract`, `producedBy`), and take `limit`.
- **`after`** continues from the last row of the previous page, on every list field. The
  cursor is that row's `internalId` (or `facetId`/`schemaId`), so a client pages by reading
  the id it already has. It is a keyset cursor, so inserts do not shift the window. An
  unknown cursor is a GraphQL error rather than an empty list, which would otherwise end a
  paging loop early and look like the end of the data.
- **`without`** (a list of `"DIRECTION:PREDICATE[:TYPE]"`) returns only entities with no
  such edge, all conditions holding: `specimens(without: ["incoming:derived_from:Extract"])`
  is everything awaiting extraction. Strings rather than an input object, so the grammar is
  identical across the CLI, REST and GraphQL. A malformed one is an error.
- **`validFrom` / `validTo`** bound the record's `validTime` inclusively, on every list
  field including `datapoints` and `facets`. They are `String`, an ISO 8601 date or
  datetime, matching how this schema types every other timestamp; a bare date means
  midnight and no offset means UTC.
- `events(ref:)` returns the events concerning one record: its own creation event plus
  the creation event of every edge touching it (within `edgeLimit`). Without `ref` it is
  the whole log, oldest first. A bare `edge_id` is also accepted as `ref`.
- `events(after:)` returns only what happened after that `eventId`, which is how a
  consumer follows the log without re-reading it; `types` and `source` narrow the stream.
  An unknown type or cursor is an error rather than an empty list.

## `FacetInstance`, `FacetSchema`, `Event`

Plain types, not `Node`s: a facet's identity is a `facet_id` and an event has no edges.
They mirror the REST shapes field for field.

```graphql
type FacetInstance { facetId: ID!  facetType: String!  _producer: String!  _schemaURL: String!  attachedTo: String!  data: JSON! }
type FacetSchema   { schemaId: ID!  schemaName: String!  jsonSchema: JSON! }
type Event         { eventId: ID!  source: String!  type: String!  specversion: String!  subject: String
                     time: String!  datacontenttype: String  validTime: String!  transactionTime: String!
                     supersedes: String  supersedeReason: String  payload: JSON! }
```

`_producer` and `_schemaURL` keep their exact names from the facet model. Timestamps are
ISO 8601 strings in UTC. `FacetInstance.attachedTo` and `data`, and
`FacetSchema.jsonSchema`, are fetched only when requested.

## Examples

Walk from a VCF back through the pipeline run to the FASTQ set and the library it came
from, pulling the kit lot along the way:

```graphql
{
  dataFile(ref: "0042-P.vcf.gz") {
    outgoing {
      predicate
      other {
        name
        ... on AnalysisRun {
          outgoing { predicate other { name
            ... on DataFileSet {
              outgoing { predicate other { name
                ... on Library { outgoing { predicate other { name } } }
              } }
            }
          } }
        }
      }
    }
  }
}
```

Everything made with one reagent lot, two hops forward:

```graphql
{
  reagent(ref: "KIT-QIAAMP-LOT-A1") {
    incoming { predicate other { name incoming { predicate other { name } } } }
  }
}
```

Identity assertions on a specimen, with their evidence:

```graphql
{
  specimen(ref: "SPEC-0042-P") {
    incoming { predicate assertedBy method confidence other { name } }
  }
}
```

`docs/worked-example.md` runs these against a real graph and shows the responses.

## Connection model

Each resolver opens and closes its own database connection. Against SQLite this costs
nothing measurable. Against Postgres it is one connection per resolved field, which is
fine at lab scale but is the first thing to revisit if a wide traversal against Postgres
ever proves slow.
