# Use cases

Three labs, walked through end to end against the first release: how each one's work
maps onto the model, where OpenNGS fits, and where it does not yet. Each gap links to the
GitHub issue tracking it. Decisions made during these reviews are recorded at the end
and already reflected in `docs/data-model.md`.

Read `docs/data-model.md` first; this page assumes its vocabulary.

---

## 1. A clinical whole-genome sequencing lab

**Who.** A clinical lab receiving test orders from an EHR. Each sample is processed
independently: automated DNA extraction, manual library prep and pooling, whole-genome
sequencing, and the lab's own Nextflow pipeline on a Kubernetes cluster. All files live
in an S3 bucket.

**What they need.** Every result traceable to its order, patient, specimen, kit lots,
operators, run, and pipeline version. An audit trail that says who knew what, when. QC
forensics across the wet-lab/bioinformatics boundary. Results flowing back to the order.

### Deployment

The container image with Postgres in the same cluster, one deployment, one
`OPENNGS_ORG`/`OPENNGS_NAMESPACE` for the lab. The API authenticates bearer tokens ([#5](https://github.com/OpenNGSOrg/openngs-core/issues/5)),
so each integration gets its own principal and every event records which one made it; a
dashboard gets a read-only token. Static tokens only, so an identity-provider integration
is still the lab's own work. No Kubernetes manifests ship; the lab writes them from the
`Dockerfile` and compose file.

### The journey

| Stage | How it maps | Notes |
|---|---|---|
| **Orders, patients, specimens from the EHR** | A poller reads FHIR `ServiceRequest`/`Patient`/`Specimen` and posts to REST. Patient → `Subject` (lab-internal ID as `local_id`, MRN as an xref). Collected specimen → `Specimen` with collection time as `valid_time`, EHR ID and tube barcode as xrefs. **Test order → `Context`**: subject, specimens, and eventually the outputs join it via `part_of`; test code, clinician, and priority are a facet on it. | Get-or-create is missing ([#4](https://github.com/OpenNGSOrg/openngs-core/issues/4)); the nightly reconciliation job can page the whole specimen list ([#3](https://github.com/OpenNGSOrg/openngs-core/issues/3)). |
| **Automated extraction** | Per sample: `Extract` from the specimen with the robot's timestamp as `valid_time`; `used` the robot (`Actor`), the kit lot (`Reagent`), the SOP (`Protocol`). | Fits cleanly; kit-lot forensics falls out of it. |
| **Manual library prep and pooling** | `Library` from the extract, `used` kit lot and operator; `Pool`; libraries `part_of` the pool. | Someone must record it. OpenNGS has no forms by design; a LIMS feed, or a spreadsheet loaded with `openngs ingest manifest` ([manifests](manifest.md)). |
| **Sequencing** | `SequencingRun` `used` the instrument `Actor`; the raw run folder as a `DataFileSet` produced by the run, `derived_from` the pool, S3 prefix as an xref. | The Illumina run-metadata adapter is unbuilt; the lab parses `RunInfo.xml` and attaches `RunParameters` as a facet. |
| **Nextflow on Kubernetes** | One `AnalysisRun` per invocation, `used` the pipeline `Protocol` (pipeline and version) and the input FASTQ set; output `DataFileSet` with the S3 prefix; BAM and VCF as `DataFile`s. QC metrics as `DataPoint`s. | Hook: an `onComplete` handler or final process posting to REST. RO-Crate and MultiQC adapters are unbuilt. |
| **Results back to the order** | The output set joins the order's `Context`. A results service polls `GET /events?after=<last handled>` and resumes across restarts. | Works by polling ([#2](https://github.com/OpenNGSOrg/openngs-core/issues/2)), or the results service can receive instead: `openngs event relay` pushes to its webhook ([event delivery](event-delivery.md)). |

### What fits

The physical chain; kit-lot and operator provenance; the pipeline-run model (one run per
invocation, pipeline as a `Protocol`, inputs via `used`); S3 references as xrefs; the
two-timestamp model for back-recorded bench work; `Context` as the order.

### What is missing, in order of how hard it blocks this lab

1. ~~**Corrections**~~ ([#1](https://github.com/OpenNGSOrg/openngs-core/issues/1)) — **done**
  . A mislabelled tube is corrected, a sample swap is
   fixed by retracting the wrong edge and asserting the right one, and both are recorded
   with a reason.
2. ~~**Who recorded an event**, and authentication~~
   ([#5](https://github.com/OpenNGSOrg/openngs-core/issues/5)) — **done**. Bearer tokens with
   read/write roles, and `recorded_by` on every event.
3. ~~**Event cursor**~~ ([#2](https://github.com/OpenNGSOrg/openngs-core/issues/2)) — **done**.
   A consumer follows the log by polling `after` the last event it handled.
4. ~~**Pagination**~~ ([#3](https://github.com/OpenNGSOrg/openngs-core/issues/3)) — **done**.
   `after` on every list, over all three interfaces.
5. **Adapters**: EHR/FHIR, Illumina run metadata, Nextflow/MultiQC. All written by the
   lab against REST.
6. **Get-or-create** ([#4](https://github.com/OpenNGSOrg/openngs-core/issues/4)).
7. Kubernetes deployment artifacts (no issue yet; the `Dockerfile` and compose file are
   the starting point).

---

## 2. A metagenomics research lab

**Who.** A research group sampling lakes and rivers, extracting DNA, sequencing, and
running its own pipeline on a local machine. Files on the local filesystem. No LIMS;
students and spreadsheets.

**What they need.** Every dataset traceable to a site, a date, a bottle, a kit lot.
Blanks and mock communities tracked alongside real samples for contamination analysis.
MIxS metadata for ENA submission, and the accessions recorded when they come back.

### Deployment

The simplest case: one machine, SQLite, the CLI, `file://` URIs as xrefs.
`make install && make db && make cli-install`. Several projects can share one database
and switch `--ns` per campaign, since the CLI takes the namespace per command.

### The journey

| Stage | How it maps | Notes |
|---|---|---|
| **Field sampling** | **The sampling site is the `Subject`** (a lake, a river station). The sampling trip is a `Context`. Each bottle is a `Specimen` `derived_from` the site, with the sampling date as `valid_time`; field replicates are sibling Specimens; a subsample is a Specimen `derived_from` a Specimen. Coordinates, depth, temperature, and ENVO terms are a facet on the Specimen, using MIxS water-checklist slot names. | The `Subject` definition needed widening to say this ([#8](https://github.com/OpenNGSOrg/openngs-core/issues/8)); the model itself fits. |
| **DNA extraction, with controls** | `Extract` from the specimen, `used` the kit lot and the student. An extraction blank is `openngs extract create BLANK-01 --no-parent`; a mock community is a `Specimen` created the same way. | Works ([#7](https://github.com/OpenNGSOrg/openngs-core/issues/7)); a conventional "controls" Subject remains a valid alternative. **Kit-lot contamination** ("which blanks and samples share lot X") is a one-hop query on the `Reagent`, and the blank shows up in it. |
| **Sequencing** | As in use case 1, whether in-house or at a core facility (the core is an `Actor`). | |
| **Local pipeline** | Co-assembly: one `AnalysisRun` that `used` many per-sample FASTQ sets; the assembly `DataFileSet` `derived_from` each. Binning: each MAG a `DataFile` `derived_from` the assembly. Summary values (reads, contigs, N50, percent classified) as `DataPoint`s. | Taxonomic profiles stay files, not DataPoints. Adapters unbuilt; the pipeline's last step is a script against the CLI. |
| **Submission to ENA/SRA** | MIxS metadata from the Specimen facet; `openngs specimen xref add LK-001 biosample:SAMN... ena:ERS...` when the accessions arrive. | Works ([#6](https://github.com/OpenNGSOrg/openngs-core/issues/6)). The export adapter is still unbuilt. |
| **Asking questions** | "Specimens from site X in summer 2025": `openngs specimen list --subject SITE-X --valid-from 2025-06-01 --valid-to 2025-08-31`. | Works ([#9](https://github.com/OpenNGSOrg/openngs-core/issues/9)); `valid_time` is on the row, so the parent filter and the date range compose. |

### What fits

Kit-lot forensics; `Context` for a sampling campaign; MIxS as a user facet; local
`file://` references; co-assembly and binning lineage; the two-timestamp model for field
dates; the CLI as the whole interface.

### What is missing

1. ~~**Adding an xref to an existing entity**~~
   ([#6](https://github.com/OpenNGSOrg/openngs-core/issues/6)) — **done**.
2. ~~**Registering controls honestly**~~
   ([#7](https://github.com/OpenNGSOrg/openngs-core/issues/7)) — **done**.
3. ~~**The `Subject` definition**~~ ([#8](https://github.com/OpenNGSOrg/openngs-core/issues/8))
   — **done**.
4. ~~**Date-range queries**~~ ([#9](https://github.com/OpenNGSOrg/openngs-core/issues/9)) —
   **done**. `--valid-from`/`--valid-to` on every list, over all three interfaces.
5. ~~**Bulk loading from a sample sheet**~~
   ([#10](https://github.com/OpenNGSOrg/openngs-core/issues/10)) — **done**. `openngs ingest
   manifest` and `POST /ingest/manifest`; see [manifests](manifest.md).

---

## 3. A data engineer orchestrating a clinical lab, with dashboards

**Who.** A data engineer using Airflow to run a clinical lab's operation: pulling from
and pushing to the EHR, the LIMS, and the sequencers; launching pipelines on a third-party
platform (Seqera Platform, Illumina's platform); and building lab-operations dashboards
in a BI tool. OpenNGS is the metadata store underneath all of it.

**What they need.** A store of lineage facts that the orchestrator can read to decide
what to do next and write to as work completes, safely under parallel tasks; a stream to
react to; and SQL a dashboard can be built on.

This is the persona the architecture was written for. Airflow is the separately
deployed component reading the public event stream that "choreography, not
orchestration" describes. OpenNGS holds the facts; Airflow holds execution state and
decides. Nothing here asks OpenNGS to become a workflow engine.

### Deployment

Postgres from day one (parallel writers). The API next to Airflow behind the engineer's
own gateway ([#5](https://github.com/OpenNGSOrg/openngs-core/issues/5)). Alternatively,
`pip install openngs` and use the store layer in-process from tasks, which works today but
is an internal surface with no stability promise
([#15](https://github.com/OpenNGSOrg/openngs-core/issues/15)).

### The journey

| Stage | How it maps | Notes |
|---|---|---|
| **Sensing what to do next** | `GET /specimens?without=incoming:derived_from:Extract`, `GET /data-file-sets?without=incoming:used`. One query per sensor, answered and interpreted by the consumer. | Works ([#11](https://github.com/OpenNGSOrg/openngs-core/issues/11)); composes with the cursor and the date range. |
| **Reacting to change** | Follow the event stream, polling `after` the last event handled, optionally narrowed by `type`. | Polling works ([#2](https://github.com/OpenNGSOrg/openngs-core/issues/2)); a webhook sink now pushes instead ([event delivery](event-delivery.md)). A broker sink is still unbuilt ([#23](https://github.com/OpenNGSOrg/openngs-core/issues/23)). |
| **Writing from tasks** | Registering a run is one `POST /batch` of four operations, applied in a single transaction. | Atomic ([#13](https://github.com/OpenNGSOrg/openngs-core/issues/13)); retries still hit 409s ([#4](https://github.com/OpenNGSOrg/openngs-core/issues/4)) and parallel workers can still create two nodes for one name ([#14](https://github.com/OpenNGSOrg/openngs-core/issues/14)). |
| **Launching pipelines on a platform** | `AnalysisRun` at launch with the platform's workflow ID as an xref, `used` the pipeline `Protocol` and the input set; on completion the output set, files, and QC `DataPoint`s. **The run's outcome is a set of `DataPoint`s** on the run, using the `openngs-dp:run_outcome` family. | Fits well ([#17](https://github.com/OpenNGSOrg/openngs-core/issues/17)); platform IDs arriving late are recorded with `xref add` ([#6](https://github.com/OpenNGSOrg/openngs-core/issues/6)). |
| **EHR and LIMS** | The DAGs are the adapters; OpenNGS is passive. | Get-or-create ([#4](https://github.com/OpenNGSOrg/openngs-core/issues/4)) and the manifest loader ([manifests](manifest.md)) cover the mechanics; the adapters are still per-lab code. |
| **Several labs, one orchestrator** | One namespace per API deployment. | Per-request org/namespace ([#16](https://github.com/OpenNGSOrg/openngs-core/issues/16)). |
| **Operating it** | Long-lived production store. | No migrations for the `Event` table ([#18](https://github.com/OpenNGSOrg/openngs-core/issues/18)); no metrics beyond `/health`. |

### Dashboards

The right path is **direct SQL on Postgres from a BI tool**; the APIs have no
aggregation, and the store was chosen to make SQL possible. The raw tables are hostile to
it today: fifteen entity tables with no common view, `Edge` endpoints with no type,
`valid_time` on the event rather than the entity (keyed by an unindexed column), facet
fields as JSON strings, and `same_as` deduplication as an unwritten recursive CTE.

| Dashboard question | What it needs |
|---|---|
| Throughput and backlog per stage | The `without` filter ([#11](https://github.com/OpenNGSOrg/openngs-core/issues/11)), or the same anti-join as a view ([#19](https://github.com/OpenNGSOrg/openngs-core/issues/19)) |
| Turnaround time | `valid_time` is on the row now ([#9](https://github.com/OpenNGSOrg/openngs-core/issues/9)); the views still want an index |
| QC trends by kit lot and operator | A `DataPoint` join walked up to the `Reagent`, on the views from [#19](https://github.com/OpenNGSOrg/openngs-core/issues/19) |
| Counting specimens without double-counting `same_as` pairs | A closure view at a confidence threshold |

### What fits

The boundary itself (facts in OpenNGS, execution state in Airflow); the pipeline-run
model with platform IDs as xrefs; `used` for declared inputs; `DataPoint` typed columns
for QC aggregation; CloudEvents as the envelope once it can be delivered.

### What is missing

1. ~~**Derived-state queries**~~ ([#11](https://github.com/OpenNGSOrg/openngs-core/issues/11))
   — **done**.
2. ~~**Outbound event delivery**~~ ([#12](https://github.com/OpenNGSOrg/openngs-core/issues/12))
   — **done**. `openngs event relay` follows the log and pushes to a webhook; see
   [event delivery](event-delivery.md).
3. ~~**Atomic batch writes**~~ ([#13](https://github.com/OpenNGSOrg/openngs-core/issues/13))
   — **done**.
4. ~~**Unique index on `name`**~~ ([#14](https://github.com/OpenNGSOrg/openngs-core/issues/14)) — **done**.
5. **A supported Python client** ([#15](https://github.com/OpenNGSOrg/openngs-core/issues/15)).
6. **Per-request namespace** ([#16](https://github.com/OpenNGSOrg/openngs-core/issues/16)).
7. ~~**Run-outcome vocabulary**~~ ([#17](https://github.com/OpenNGSOrg/openngs-core/issues/17))
   — **done**.
8. **Migrations** ([#18](https://github.com/OpenNGSOrg/openngs-core/issues/18)).
9. **Reporting views and indexes** ([#19](https://github.com/OpenNGSOrg/openngs-core/issues/19)).
10. **GraphQL aggregates** ([#21](https://github.com/OpenNGSOrg/openngs-core/issues/21)).
11. **A read-only database role** ([#22](https://github.com/OpenNGSOrg/openngs-core/issues/22)).

---

## Decisions made in these reviews

| Question | Decision |
|---|---|
| Where does a clinical test order live? | A `Context` per order. Subject, specimens, and outputs join it via `part_of`; order details are a facet on it. |
| What is the `Subject` of an environmental sample? | The sampling site. `Subject` is "the source a specimen was taken from: a person, an organism, or a site". |
| How are controls (blanks, mock communities) registered? | `--no-parent` on `create`, with the control's role as a facet ([#7](https://github.com/OpenNGSOrg/openngs-core/issues/7)). A conventional "controls" Subject remains a valid alternative; both are to be documented. |
| How is name uniqueness guaranteed under concurrent writers? | A unique index on `name` per entity table, partial so a retracted name stays reusable. `--force` is removed; a deliberate second record for the same real thing is a distinct local ID plus a `same_as` assertion. |
| How is a run's outcome recorded? | As `DataPoint`s on the run (`run_outcome`, `exit_status`, `run_duration_seconds`, ...), never as a status field ([#17](https://github.com/OpenNGSOrg/openngs-core/issues/17)). |

## Themes across all three

- **Every lab writes the same adapters.** EHR, LIMS, sequencer metadata, pipeline
  completion, and QC ingest are all custom code against REST today. The manifest loader
  and batch endpoint are the floor; the named adapters are the ceiling.
- **Late-arriving facts are the norm**: accessions, platform IDs, run outcomes. Add-only
  is fine; add-only-at-creation is not.
- **Consumers need to follow the log.** Choreography is the architecture. Polling with a
  cursor works, and `openngs event relay` pushes to a webhook for consumers that would
  rather receive; a broker sink ([#23](https://github.com/OpenNGSOrg/openngs-core/issues/23))
  is what remains.
- **The store is meant to be queried in SQL**, and the tables need views before that is
  pleasant.
- **Enumerating is as important as looking one thing up.** Reconciliation jobs, exports and
  dashboards all walk whole tables, which is why lists needed a cursor before they needed
  anything cleverer.
