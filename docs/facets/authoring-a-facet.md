# Authoring a facet

A worked, end-to-end example of writing your own facet, attaching an instance to a real
entity, and inspecting it, using nothing that is not already in this repository.

A facet is how lab-specific detail attaches to the fixed core model: a tool's QC report,
a kit's metadata, an instrument's run settings, a subject's role in a pedigree. You
define its shape in your own namespace; OpenNGS validates every instance against that
shape and records what produced it. No facet is part of the core standard, and nothing in
this guide touches `schema/openngs.yaml`.

The example is a `QcMetricsFacet`: one named metric from a QC tool.

![Three facets attached along the sequencing run to VCF chain, each declaring a _producer and pointing at the schema that validates it](../img/ngs_facets.svg)

Where this one lands: attached to a FASTQ `DataFileSet`, declaring `fastqc/0.12.1` as its
`_producer`, and validated against a schema held in the registered store. The two other
facets shown are illustrative - this guide builds only the middle one.

## 1. Write the facet schema in LinkML

Facets are authored in [LinkML](https://linkml.io/linkml/), the same tool the core schema
uses. The example lives at `docs/facets/examples/qc_metrics/qc_metrics.yaml`:

```yaml
id: https://acme.example/schema/facets/qc_metrics
name: acme_facet_qc_metrics
prefixes:
  linkml: https://w3id.org/linkml/
  acme: https://acme.example/schema/facets/qc_metrics/
default_prefix: acme
default_range: string

imports:
  - linkml:types

classes:
  QcMetricsFacet:
    description: Open-ended named QC metrics, e.g. from a MultiQC report.
    slots:
      - tool
      - sample_name
      - metric_name
      - metric_value

slots:
  tool:
    range: string
  sample_name:
    range: string
  metric_name:
    range: string
    required: true
  metric_value:
    range: float
    required: true
```

Nothing about this file is OpenNGS-specific. A schema may define several classes, use
enums, and nest classes; instances are validated against whichever class you name when
attaching, with the rest of the schema available for references.

## 2. Generate a JSON Schema from it

OpenNGS validates instances against JSON Schema, so the CLI and server only need the
lightweight `jsonschema` library rather than the LinkML toolchain. Generating one is one
command:

```bash
uv run linkml generate json-schema qc_metrics.yaml > qc_metrics.schema.json
```

The checked-in copy is `docs/facets/examples/qc_metrics/qc_metrics.schema.json`.
Regenerate it whenever the `.yaml` changes; do not hand-edit it.

## 3. Register the schema

A schema can be referenced by file path (`--schema-url`), but a path can move and is
useless on another machine. Registering it once puts it in the database, versioned,
alongside the data it validates:

```bash
export OPENNGS_ORG=acme-genomics OPENNGS_NAMESPACE=core-lab OPENNGS_DB_URL=sqlite:///openngs.db

openngs facet schema register qc-metrics \
  --file docs/facets/examples/qc_metrics/qc_metrics.schema.json
# prints a schema_id
```

Every registration is a new, immutable version with its own `schema_id`; registering
`qc-metrics` again after changing the schema adds a version, never overwrites. A bare
name resolves to the newest version; a `schema_id` pins one exactly.

```bash
openngs facet schema list --name qc-metrics    # every version
openngs facet schema show qc-metrics           # the newest one's content
```

## 4. Attach an instance

```bash
openngs sequencing-run create RUN-001
openngs data-file create RUN-001-R1.fastq.gz --produced-by RUN-001

openngs facet attach \
  --to RUN-001-R1.fastq.gz \
  --schema-id qc-metrics \
  --type QcMetricsFacet \
  --producer "fastqc/0.12.1" \
  --data '{"tool":"fastqc","metric_name":"openngs-dp:percent_duplication","metric_value":12.3}'
```

- `--to` is any `REF`, or a bare `edge_id`: a facet can describe an edge as well as an
  entity. A subject's role in a pedigree, for instance, belongs on its `part_of` edge to
  the `Context`, not on the subject.
- `--type` names the class within the schema.
- `--producer` says what wrote this: a tool and version, a system name.
- `--data` is inline JSON or `@path/to/file.json`.

Validation happens before anything is written:

```bash
openngs facet attach --to RUN-001-R1.fastq.gz --schema-id qc-metrics \
  --type QcMetricsFacet --producer test --data '{"tool":"fastqc"}'
# error: data does not validate against 'QcMetricsFacet' in '...': 'metric_name' is a required property
```

The instance records the exact schema version it validated against, as
`openngs-schema://<schema_id>`, so "what did this validate against" stays answerable
regardless of what `qc-metrics` later resolves to.

To use a file path instead of registering, replace `--schema-id qc-metrics` with
`--schema-url docs/facets/examples/qc_metrics/qc_metrics.schema.json`. The instance then
records that path.

## 5. Inspect it

```bash
openngs facet list --to RUN-001-R1.fastq.gz
openngs facet show <facet_id>
openngs facet show <facet_id> --output json
```

`show` prints the data and resolves what the facet is attached to. The same operations
are available over REST (`POST /facets`, `POST /facet-schemas`) and as MCP tools.

## Making fields comparable across facets

Two independently written facets will name the same concept differently. OpenNGS handles
this with LinkML's own SKOS mapping slots (`exact_mappings`, `close_mappings`, and so on)
plus a seed vocabulary of NGS/QC concepts, `schema/vocabularies/datapoints.yaml`, for the
ones no existing ontology covers.

- A **fixed-field** facet (one slot per concept) maps its slot definitions directly, with
  `exact_mappings` on the slot.
- An **open-ended** facet like this example (where the concept is a data *value*, not a
  slot) maps by using a vocabulary CURIE as that value: `metric_name:
  "openngs-dp:percent_duplication"` says this instance reports the same datapoint as
  anyone else using that CURIE, without either party agreeing on it directly.

Prefer a term from an existing ontology (OBI, NCIT, EDAM, STATO) wherever one exists; use
`openngs-dp:` terms for the rest; never assert a mapping to an ontology term that has not
been verified.

## Facet or DataPoint

This facet keeps a tool's report whole. When one specific value in it, such as
`percent_duplication`, needs to be filtered, grouped, or aggregated across many samples,
give that value a `DataPoint` too:

```bash
openngs datapoint create RUN-001-R1-percent-dup --for RUN-001-R1.fastq.gz \
  --type openngs-dp:percent_duplication --kind number --value 12.3
```

A facet's data is stored as JSON, validated as a unit; a `DataPoint` is a typed, indexed
column. Keep the report as a facet and promote the fields worth querying. See
`docs/data-model.md` for the full comparison.

## Correcting an instance

A facet attached with the wrong data is corrected, not edited: `openngs facet correct
<facet_id> --data @fixed.json --reason "re-ran fastqc"` keeps the same `facet_id` and
re-validates against the schema this instance was pinned to. One attached to the wrong
entity, or against the wrong schema, is retracted instead (`openngs facet retract
<facet_id> --reason ...`) and attached again. Both are new events; nothing is overwritten.

## Staying out of core

This facet lives entirely in your namespace. The core schema does not know it exists, and
attaching, listing, and showing it required no change to OpenNGS. A facet enters the core
standard only when two independent implementations need the same shape to interoperate;
until then, every facet is a user or vendor facet, validated only against its own
declared schema.

## Limits

- Schemas are read from the local filesystem (`--schema-url`, `register --file`) or the
  database. Fetching a schema from a remote URL is not supported.
- `register` accepts generated JSON Schema, not LinkML source.
- Facet data is stored as a JSON string. Filtering on a facet field is a JSON operation,
  not a plain `WHERE`; use a `DataPoint` for values you query on.
- A registered schema cannot be edited or removed: registering again adds a version.
