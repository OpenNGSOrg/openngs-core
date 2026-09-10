# OpenNGS

An open standard for sample lineage in sequencing labs, plus a reference implementation.

> **Alpha.** OpenNGS is under active development and has not had a release. The schema,
> the APIs and the CLI may change without notice or a migration path, and there are no
> database migrations yet — a schema change means rebuilding from the event log. It is
> ready to evaluate and to build against experimentally; it is not ready to be the system
> of record for work you cannot repeat.
>
> If you intend to hold patient data, read
> [docs/authentication.md](docs/authentication.md) first. Authentication is bearer tokens
> only, the CLI bypasses it entirely by connecting straight to the database, and reads are
> not audited. Those are known gaps with open issues, not oversights — but they are gaps
> today.

OpenNGS records the provenance of everything in the chain from a person to a variant
call: which specimen came from whom, which extract used which kit lot and operator, which
libraries were pooled onto which run, which files that run produced, which pipeline
version consumed them, and what QC values describe each step. Every fact is an event in
an append-only log with two timestamps (when it was true in the lab, when OpenNGS learned
it), and identity across systems is asserted, never merged.

**Mental model: OpenLineage for the wet lab.** A small, frozen core graph of fifteen
entity types and six edge types; all lab-specific variation in versioned facets;
backend-agnostic; adopted through adapters. OpenNGS is a **metadata plane, not a data
plane**, and an **integrator, not an executor**.

It is not a LIMS, not a workflow engine, not a file store, and not a clinical record.

## The lineage backbone

![The OpenNGS lineage graph: Subject, Specimen, Extract, Library and Pool on the physical side; the sequencing run, its raw output set, demultiplexing, the run-level and per-sample FASTQ sets, secondary analysis and the VCF on the digital side](docs/img/ngs_data_lineage.svg)

This is the spine of the model: the path a sample takes from a person to a variant call,
and the entity types OpenNGS exists to connect.

**The physical chain** is one entity per step where a lab makes a decision, consumes a
reagent lot, and can go wrong independently of the other steps. A `Subject` is the source
a specimen was taken from — a person, an organism, or an environmental sampling site. A
`Specimen` is what was collected from it, an `Extract` the nucleic acid pulled out of that,
a `Library` the sequenceable preparation of the extract, and a `Pool` the group of
libraries loaded together. Splitting a tube does not need a new entity type: an aliquot of
a `Specimen` is another `Specimen`, `derived_from` its parent.

**The `SequencingRun`** is where material becomes data, and the only place the two halves
touch. It states the `Pool` it `used`, and the raw run folder it produces is
`derived_from` that same pool.

**The digital chain** is deliberately set-shaped, because real pipelines are. A
`DataFileSet` is a group of files produced together — a raw run folder, one sample's FASTQ
pair, a pipeline's whole output directory — and sets nest, so a per-sample set lives inside
the run-level one. An `AnalysisRun` is one pipeline invocation, which declares the input
it `used` rather than leaving that to be inferred. A `DataFile` is a reference to bytes
that live elsewhere; OpenNGS never stores file contents.

Sample identity survives pooling because the per-sample FASTQ set is `derived_from` its
`Library`. That single edge is what lets a variant call be traced back to one tube without
the pool's other samples getting in the way.

Arrows point from a thing to where it came from, so following them upstream is always
"and where did *that* come from?".

That accounts for nine of the fifteen entity types. The other six are not drawn here:
`Protocol`, `Reagent`, `Actor`, `Project` and `Context` give the chain meaning, and
`DataPoint` carries measured values. They attach to the backbone rather than sitting in
it — see [docs/data-model.md](docs/data-model.md).

## Documentation

| Read this | For |
|---|---|
| [docs/architecture.md](docs/architecture.md) | What OpenNGS is and is not, and why it is shaped this way |
| [docs/data-model.md](docs/data-model.md) | Every entity and edge, its intent, and how a lab's work maps onto them |
| [docs/getting-started.md](docs/getting-started.md) | From a clean clone to a running graph, step by step |
| [docs/worked-example.md](docs/worked-example.md) | A clinical trio built end to end and queried three ways |
| [docs/use-cases.md](docs/use-cases.md) | Three labs walked through against this release: what fits, what is missing, decisions taken |
| [docs/authentication.md](docs/authentication.md) | Securing a deployment: tokens, roles, and what they do not cover |
| [docs/cli-design.md](docs/cli-design.md) | The `openngs` CLI reference |
| [docs/api-design.md](docs/api-design.md) | The REST API reference |
| [docs/manifest.md](docs/manifest.md) | Loading a CSV/TSV sample sheet |
| [docs/event-delivery.md](docs/event-delivery.md) | Subscribing to the event stream, by polling or push |
| [docs/graphql-design.md](docs/graphql-design.md) | The GraphQL query API reference |
| [docs/mcp-design.md](docs/mcp-design.md) | The MCP server, for AI agents |
| [docs/facets/authoring-a-facet.md](docs/facets/authoring-a-facet.md) | Writing your own facet |
| [docs/contributing.md](docs/contributing.md) | Developing OpenNGS itself |

## Quick start

```bash
make install                 # dependencies (uv)
make db                      # SQLite at ./openngs.db (make db-postgres for Postgres)
make cli-install             # put `openngs` on your PATH

export OPENNGS_ORG=acme-genomics OPENNGS_NAMESPACE=core-lab OPENNGS_DB_URL=sqlite:///openngs.db
openngs subject create SUBJ-001
openngs specimen create SPEC-001 --subject SUBJ-001
openngs specimen show SPEC-001
```

Or build a complete, realistic graph in one go:

```bash
bash docs/examples/clinical-trio.sh
```

Then `make api` for the REST and GraphQL APIs at `http://localhost:8000` (Swagger UI at
`/docs`, GraphiQL at `/graphql`), or `make compose-up` for Postgres, the API, and the MCP
server together in containers.

## Ways in

There are five ways to talk to an OpenNGS graph. They are not five implementations — each
is a thin client of one store layer, and **every write goes through the same path**: the
event is appended first, then applied to the graph in the same transaction. Whichever door
a fact arrives through, the projection stays rebuildable from the log.

| Interface | Start it with | Best for |
|---|---|---|
| **CLI** | `make cli-install`, then `openngs` | People at a terminal, and scripts on the same machine as the database |
| **REST API** | `make api` | Adapters, orchestrators, anything over HTTP |
| **GraphQL** | `make api`, then `/graphql` | Traversal — following lineage across many hops in one query |
| **MCP server** | `make mcp` | AI agents |
| **Manifest loader** | `openngs ingest manifest` | Bulk loading a sample sheet a lab already keeps |

### CLI

Connects straight to the database. The full surface: create, list, show, correct and
retract for every entity type, plus `link`, `facet`, `datapoint`, `event` and
`ingest manifest`.

```bash
openngs specimen create SPEC-001 --subject SUBJ-001 --xref barcode:TUBE-00417
openngs link used --from EXT-001 --to KIT-LOT-A1
openngs specimen show SPEC-001 --events
```

Because it bypasses the HTTP layer, it also bypasses authentication — see the note at the
top of this page. Reference: [docs/cli-design.md](docs/cli-design.md).

### REST API

The CLI's surface over HTTP, with OpenAPI at `/docs`.

```bash
curl -X POST localhost:8000/specimens \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"local_id": "SPEC-001", "subject": "SUBJ-001"}'
```

`POST /batch` applies several operations in one transaction, which is what an orchestrator
wants when registering a run and its outputs together. Reference:
[docs/api-design.md](docs/api-design.md).

### GraphQL

Mounted by the same process at `/graphql`, with GraphiQL in a browser. **Query-only** —
there are no mutations, because writes belong on the paths above. It exists because
"follow `derived_from` from this VCF back to the subject" is one GraphQL query and several
REST round trips.

```graphql
{ dataFile(ref: "0042-P.vcf.gz") { name outgoing { predicate other { name } } } }
```

Reference: [docs/graphql-design.md](docs/graphql-design.md).

### MCP server

One MCP tool per REST route, derived automatically from the API's own OpenAPI schema, plus
a hand-written `execute_graphql`. It is a protocol adapter in front of the REST API, not
another client of the store. Reference: [docs/mcp-design.md](docs/mcp-design.md).

### Manifests

A CSV or TSV with one row per entity, edge, datapoint, facet or schema, applied in file
order inside a single transaction — so a bad row anywhere leaves nothing behind.

```bash
openngs ingest manifest run-2026-09-01.tsv --dry-run
openngs ingest manifest run-2026-09-01.tsv
```

Available over HTTP too, as `POST /ingest/manifest`. Reference:
[docs/manifest.md](docs/manifest.md).

### Reading the other way

Consumers do not have to poll. `openngs event relay` follows the event log and pushes each
event to a webhook as a CloudEvents envelope, at least once, with the event id as the
deduplication key. Reference: [docs/event-delivery.md](docs/event-delivery.md).

## Layout

```
schema/openngs.yaml          LinkML source: the standard
schema/facets/               The abstract Facet class, generic facet storage, the schema store
schema/vocabularies/         Seed vocabularies for facet authors (e.g. datapoints.yaml)
generated/                   Generated SQL DDL; never hand-edit
src/openngs/
  model/                     Generated Pydantic models
  store/                     Event log, graph projection, facet and datapoint storage
  entities.py                The entity registry the CLI, REST, and GraphQL all build from
  cli.py                     The openngs CLI
  api.py                     The REST API (FastAPI), which also mounts GraphQL
  graphql_schema.py          The GraphQL schema (Strawberry)
  mcp_server.py              The MCP server (FastMCP), generated from the REST API
docs/                        This documentation
docs/examples/               Runnable example scripts
tests/                       Test suite (pytest)
```

## License

Apache 2.0. See [LICENSE](LICENSE).
