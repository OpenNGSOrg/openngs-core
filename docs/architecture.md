# OpenNGS: architecture and scope

## 1. What OpenNGS is

OpenNGS is an **open standard for sample lineage in sequencing labs**, plus a reference
implementation of it.

It records the provenance of every physical and digital artifact in the chain from a
person to a variant call: which specimen came from whom, which extract came from which
specimen using which kit lot and which operator, which libraries were pooled onto which
run, which files that run produced, which pipeline version consumed them, and what QC
values describe each step. It resolves identity across the systems that touch those
artifacts, keeps an immutable, bitemporal record of everything it learns, and exposes
that record for querying.

The one-line framing: **OpenLineage for the wet lab.** OpenLineage standardized data
lineage with a small, frozen core object model, pushed all variability into versioned
*facets*, stayed agnostic to the backend, and won adoption through integrations rather
than by asking anyone to conform to its schema. OpenNGS applies the same pattern to the
layer of the sequencing chain that has no standard: specimen through FASTQ and beyond.

Two boundaries define it:

- **A metadata plane, not a data plane.** OpenNGS stores references to files, never file
  contents. QC *metrics* are in scope; QC *files* are not.
- **An integrator, not an executor.** OpenNGS records what happened. It does not run
  protocols, schedule pipelines, or decide what happens next.

### Who it is for

- A **sequencing core or clinical lab** that needs to answer "which kit lot, operator, or
  instrument correlates with this QC failure" across the wet-lab/bioinformatics boundary,
  and needs an audit trail of who knew what, when.
- A **bioinformatics group** that needs every output tied to the exact inputs, pipeline
  version, and upstream sample it came from.
- A **LIMS or platform vendor** that wants a lineage substrate underneath its own
  product, with the vendor's own accession numbers and no ID migration.
- A **data manager** preparing archive submissions who needs the provenance already
  assembled.

`docs/use-cases.md` walks three of these through this release in detail.

### What it is not

- **Not a LIMS.** No sample entry forms, no plate maps, no barcode printing, no
  liquid-handler control, no protocol execution. Data arrives through the API and
  adapters; a LIMS owns the bench.
- **Not a workflow engine.** No scheduler, no state machine, no "ready for sequencing"
  signal. Process state is derived from the graph, never stored as the answer.
- **Not a data store.** No FASTQ, BAM, CRAM, or VCF payloads. References only, via
  GA4GH DRS URIs or plain URIs.
- **Not a clinical record.** Provenance, not diagnoses. No phenotype or interpretation in
  the core model; those belong in facets bound to Phenopackets and similar standards, or
  in the systems built for them.
- **Not a configurable schema.** The entity and edge set is closed. If a use case needs
  a new entity type, that is a major version of the standard, not a setting.

## 2. The core model

Fifteen entity types, six edge types, and one rule: **freeze the topology, extend the
nodes.** The entity and edge types are a closed set that changes only on a major spec
version. Everything a lab actually varies on lives in facets, which version
independently and require no spec revision.

This is the single most important structural decision in the project, and it is the one
that killed every predecessor. MINSEQE froze fields and became unimplementable. Overture's
SONG made schemas fully configurable and stopped being a standard. Facets are the middle
path, proven at scale in OpenLineage and OpenTelemetry.

`docs/data-model.md` describes every entity and edge, its intent, and how a real lab's
work maps onto them. In summary:

| Group | Entities |
|---|---|
| Physical | `Subject`, `Specimen`, `Extract`, `Library`, `Pool` |
| Instrument | `SequencingRun` |
| Digital | `DataFile`, `DataFileSet`, `AnalysisRun` |
| Contextual | `Protocol`, `Reagent`, `Actor`, `Project`, `Context`, `DataPoint` |

| Edge | Meaning |
|---|---|
| `derived_from` | material or data transformation; the backbone, including aliquoting as self-derivation |
| `part_of` | composition: pool membership, file-set membership, cohort or project membership |
| `produced_by` | an output to the run that made it |
| `used` | a run to the protocol, reagent lot, actor, or input data it consumed |
| `characterizes` | a `DataPoint` to the entity it describes |
| `same_as` | an identity assertion between two records, never a merge |

![The OpenNGS lineage graph: Subject, Specimen, Extract, Library and Pool on the physical side; the sequencing run, its raw output set, demultiplexing, the run-level and per-sample FASTQ sets, secondary analysis and the VCF on the digital side](img/ngs_data_lineage.svg)

Entities carry only identity. Two mechanisms carry everything else:

- **Facets**: named, versioned, independently schema'd objects attached to an entity or
  an edge. Every facet declares `_producer` and `_schemaURL`, so any consumer can tell
  what wrote it and validate it without prior knowledge. No facet is part of core; a
  facet is promoted only when two independent implementations need it to interoperate.
  A core facet is a permanent maintenance obligation, and the project resists
  standardizing early.
- **DataPoints**: single, typed, independently correctable values (a QC metric, a flag)
  attached to what they describe, for the fields worth querying across the whole graph.

Two independently authored facets can declare that a field in one means the same thing
as a field in another using LinkML's native SKOS mapping slots. `schema/vocabularies/
datapoints.yaml` seeds an OpenNGS-native vocabulary for NGS/QC concepts that no existing
ontology covers yet. Wherever an existing ontology has a term (OBI, NCIT, UBERON, EFO,
DUO, HPO), facet fields bind to it as a CURIE rather than to an invented enumeration.

### Authoring

The schema is authored in **LinkML**. One YAML source generates JSON Schema, Pydantic
classes, SQL DDL, and documentation, which removes the drift between spec, bindings, and
docs. Facet authors use the same tool in their own namespace.

## 3. Identity

The failure mode that destroys a lineage graph is not a bad schema. It is unresolvable
identity.

Every entity has three layers of identity:

- **`internal_id`**: opaque, immutable, globally unique, non-semantic (UUIDv7). Never
  derived from a barcode, an accession, a date, or a subject attribute; semantic IDs
  guarantee an eventual collision or an unrepresentable correction.
- **`name`**: `openngs://{org}/{namespace}/{entity_type}/{local_id}`, where `local_id`
  is whatever the source system already calls the thing. A LIMS emits its own accession
  numbers on day one with no ID migration.
- **`xrefs`**: CURIEs and URIs identifying the entity in other systems. Many-to-many,
  additive, never authoritative.

When two records turn out to describe one physical thing, OpenNGS records a `same_as`
edge carrying the asserting actor, the time, the method, and a confidence. It never
collapses the nodes. Eager merging is unrecoverable; deduplication is a *query-time*
choice, resolved at whatever confidence threshold the caller wants. This is also the
precondition for two labs ever being allowed to disagree.

## 4. Events and time

The authoritative store is an ordered, immutable log of events. The graph is a
materialized projection of that log, rebuildable from it at any time. There are no
updates and no deletes on lineage; a correction is a new event that supersedes an earlier
one, carrying a pointer to what it supersedes and a reason. Correcting a record replaces
its content and leaves it believed; retracting one withdraws it, and it stays in the store
and the log, visible on request. Corrections form a single line per record: only the latest
event about it may be superseded.

This yields an audit trail as a property of the data model rather than a bolt-on, the
ability to rebuild the projection when the schema evolves, and the point-in-time
reconstruction that troubleshooting needs.

Every event carries two timestamps. **Valid time** is when the fact was true in the lab.
**Transaction time** is when OpenNGS learned it. They diverge constantly, and forensics
needs both: "what was true of this library on 3 March" and "what did we believe about it
on 3 March" are different questions, and the second is the one that explains a bad
decision.

The envelope is **CloudEvents 1.0**, which gives interoperability with Kafka, NATS,
EventBridge, and Pub/Sub for free and means integrators already know the shape.

### Choreography, not orchestration

OpenNGS emits events. It does not drive next steps. Consumers follow the log and decide.

Following it is a poll with a cursor: ask for everything after the last event you handled,
optionally narrowed by type or producer. The log is append-only, so an event already
returned never moves and a new one only ever appears after the cursor, which makes a
restarting consumer see exactly what it missed, once each. Push delivery (a webhook, a
broker sink) is not built yet; the cursor is what makes polling correct in the meantime.

The moment OpenNGS emitted `ready_for_sequencing` and a lab acted on it, OpenNGS would
have an availability SLA and, in a clinical setting, a regulatory surface. That may be a
product later, as an optional, separately deployed component reading the same public
event stream any third party can read. It will never be privileged and never in core.

## 5. Components

**The standard.** `schema/openngs.yaml` and its generated artifacts (JSON Schema,
Pydantic models, SQL DDL). The entity and edge closed set, the facet base class, the
event envelope, the naming conventions, the seed vocabularies.

**The store.** SQLite or Postgres, with all SQL portable between them. The event log and
the graph projection live in one database. Lineage traversal uses recursive CTEs, which
handle lab scale comfortably; a dedicated graph database is a future decision gated on a
demonstrated bottleneck, not a plan.

**Four interfaces onto one store**, all reading and writing through the same paths:

| Interface | Doc | Shape |
|---|---|---|
| CLI (`openngs`) | `docs/cli-design.md` | create, list, show, link, facet, datapoint, event, ingest manifest |
| REST API | `docs/api-design.md` | the same surface over HTTP, with Swagger UI |
| GraphQL | `docs/graphql-design.md` | query-only traversal, mounted at `/graphql` |
| MCP server | `docs/mcp-design.md` | one tool per REST route, plus `execute_graphql`, for AI agents |

The HTTP interfaces authenticate bearer tokens and record the principal behind every write;
the CLI talks to the database directly and is not constrained by them. See
`docs/authentication.md`.

Every write, from any interface, is an event first and a projection update second, in
one transaction.

**Adapters** are the component that determines whether any of this matters. Adoption
comes from integrations, not from the spec. The integration surfaces below are the
planned ones; none ships in this release.

## 6. Integration surfaces

- **MultiQC.** Present in effectively every NGS pipeline and emitting structured
  `multiqc_data.json`. One adapter yields QC facets and DataPoints across the whole
  nf-core ecosystem. The highest adoption leverage per line of code in the project.
- **Workflow Run RO-Crate**, via `nf-prov` for Nextflow. Consuming RO-Crate rather than
  parsing any one engine's internals also covers CWL and Snakemake where they emit it.
- **Illumina run metadata**: `RunInfo.xml`, `RunParameters.xml`, sample sheets, InterOp.
  Unglamorous, universal, and the only path to the instrument half of the graph.
- **LIMS APIs** (Clarity, Benchling) as bidirectional adapters. OpenNGS gives them a
  lineage substrate and cross-boundary QC they do not have; it does not replace them.
- **GA4GH DRS** for file references; **Phenopackets** for the subject layer; **DUO** for
  consent vocabulary.
- **Archive submission export** to ENA, SRA, BioSample, EGA, dbGaP: the most legible
  value to a lab manager who does not care about standards.

## 7. Licensing and governance

**Apache 2.0** on the spec, the reference implementation, and everything in between, with
no GPL or AGPL dependencies anywhere. This follows directly from the requirement that a
commercial LIMS vendor be able to embed OpenNGS. Overture's AGPL licensing is a
substantial part of why nobody commercially embeds SONG despite its technical quality.

Spec governance is to be separated from any one company's economics before the first
external adopter, on the OpenLineage model: spec in a neutral foundation, reference
implementation and any hosted service operated commercially. Before external adoption,
the project intends to publish a facet promotion process, a spec versioning and
deprecation policy, a conformance suite anyone can run to claim compliance, and a named
decision-making structure.

## 8. Known limits of this release

- **No point-in-time reconstruction.** Corrections are recorded and applied, but the
  projection holds only current belief. "The graph as we believed it on 3 March" is
  supported by the log and not yet by a query; it needs a row per version rather than a
  row per record.
- **No adapters.** The integration surfaces above are designed, not built. Data enters
  through the CLI, REST, or MCP.
- **Static tokens only.** The HTTP interfaces authenticate bearer tokens configured per
  deployment, with read-versus-write authorization. Validating an OIDC or JWT credential
  against a lab's identity provider, and any per-namespace rule, is still to come.
- **Facet schemas are local.** A facet validates against a JSON Schema on the server's
  filesystem or one registered in the database. Fetching a remote `_schemaURL` is not
  supported.
- **Single namespace per deployment.** One server serves one org and namespace.

## 9. Open risks

The entity set must be right, because facets absorb field-level change but not
topological change. A workflow that needs an entity the closed set lacks means a major
version.

Adapters are unglamorous, endless, and the actual product.

The "standalone tool" and "LIMS backend" requirements pull the user experience in opposite
directions. Holding the line at read-only troubleshooting resolves it, but there will be
sustained pressure to add sample entry. Adding it forfeits the vendor channel, because a
LIMS vendor will not embed a competitor.

Instrument and LIMS vendors can bundle sample tracking into accounts they already own.
Neither can easily ship an *open standard*, which is the only durable asymmetry OpenNGS
has.

## Sources

[OpenLineage docs](https://openlineage.io/docs/) · [How OpenLineage takes inspiration from OpenTelemetry](https://openlineage.io/blog/openlineage-takes-inspiration-from-opentelemetry/) · [OpenLineage naming conventions](https://openlineage.io/docs/spec/naming) · [Marquez](https://marquezproject.ai/) · [CloudEvents](https://cloudevents.io/) · [LinkML](https://linkml.io/linkml/) · [Overture SONG](https://github.com/overture-stack/song) · [nf-prov](https://github.com/nextflow-io/nf-prov) · [Workflow Run RO-Crate](https://www.researchobject.org/workflow-run-crate/outreach.html) · [GA4GH DRS](https://www.ga4gh.org/product/data-repository-service-drs/) · [GA4GH Phenopackets](https://www.ga4gh.org/product/phenopackets/) · [ENA sample checklists](https://ena-browser-docs.readthedocs.io/en/latest/browser/sample-checklists.html)
