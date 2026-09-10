#!/usr/bin/env bash
# Builds the clinical-trio lineage graph described in docs/worked-example.md, end to end,
# with the openngs CLI. Needs an empty database (make db) and OPENNGS_ORG /
# OPENNGS_NAMESPACE / OPENNGS_DB_URL set (defaults below match docs/getting-started.md).
#
#   make db && bash docs/examples/clinical-trio.sh
#
# Every command is an ordinary `openngs ...` call; nothing here is special to the script.
set -euo pipefail

export OPENNGS_ORG="${OPENNGS_ORG:-acme-genomics}"
export OPENNGS_NAMESPACE="${OPENNGS_NAMESPACE:-core-lab}"
export OPENNGS_DB_URL="${OPENNGS_DB_URL:-sqlite:///openngs.db}"

cd "$(dirname "$0")/../.."   # repo root, so the facet schema path below resolves

SAMPLES=(P M F)              # proband, mother, father

# --- 1. Context: the study and the family -------------------------------------------------
openngs project create PROJ-RARE-2026
openngs context create TRIO-0042

# --- 2. Resources every sample shares: people, instruments, kit lots, protocols ----------
openngs actor create ACTOR-JDOE              --xref orcid:0000-0002-1825-0097
openngs actor create ACTOR-NOVASEQ-01        --xref "illumina.serial:A01234"
openngs reagent create KIT-QIAAMP-LOT-A1     --xref "qiagen.lot:172345678"
openngs reagent create KIT-NEXTERA-LOT-B7    --xref "illumina.lot:20654321"
openngs protocol create SOP-DNA-EXTRACT-v3
openngs protocol create SOP-LIB-PREP-v2
openngs protocol create bclconvert-4.2.7
openngs protocol create nf-core/sarek-3.4.0  --xref "doi:10.5281/zenodo.3476425"

# --- 3. The physical chain, per sample ---------------------------------------------------
for S in "${SAMPLES[@]}"; do
  openngs subject create "SUBJ-0042-$S"
  openngs link part-of --from "SUBJ-0042-$S" --to TRIO-0042
  openngs link part-of --from "SUBJ-0042-$S" --to PROJ-RARE-2026

  # Blood drawn on 8 Jan; the LIMS barcode is its external identifier.
  openngs specimen create "SPEC-0042-$S" --subject "SUBJ-0042-$S" \
    --xref "barcode:TUBE-0042-$S" --valid-time 2026-01-08T10:30:00

  # DNA extracted on Monday 12 Jan, recorded now: valid_time and transaction_time diverge.
  openngs extract create "EXT-0042-$S" --specimen "SPEC-0042-$S" --valid-time 2026-01-12T09:00:00
  openngs link used --from "EXT-0042-$S" --to KIT-QIAAMP-LOT-A1  --valid-time 2026-01-12T09:00:00
  openngs link used --from "EXT-0042-$S" --to SOP-DNA-EXTRACT-v3 --valid-time 2026-01-12T09:00:00
  openngs link used --from "EXT-0042-$S" --to ACTOR-JDOE         --valid-time 2026-01-12T09:00:00

  openngs library create "LIB-0042-$S" --extract "EXT-0042-$S" --valid-time 2026-01-13T11:00:00
  openngs link used --from "LIB-0042-$S" --to KIT-NEXTERA-LOT-B7 --valid-time 2026-01-13T11:00:00
  openngs link used --from "LIB-0042-$S" --to SOP-LIB-PREP-v2    --valid-time 2026-01-13T11:00:00
done

# --- 4. Pool the three libraries and sequence the pool -----------------------------------
openngs pool create POOL-20260113
for S in "${SAMPLES[@]}"; do
  openngs link part-of --from "LIB-0042-$S" --to POOL-20260113
done

openngs sequencing-run create RUN-20260113 --valid-time 2026-01-13T18:00:00
openngs link used --from RUN-20260113 --to ACTOR-NOVASEQ-01

# What was loaded on the run, stated by the run itself. True from the moment
# sequencing starts - the output's derived_from below only becomes true once there is an
# output, which a run that fails never produces.
openngs link used --from RUN-20260113 --to POOL-20260113

# The raw run folder: produced by the run, derived from the pool it sequenced. This one
# edge is the bridge from material to data.
openngs data-file-set create BCL-20260113 --produced-by RUN-20260113 \
  --xref "s3://acme-seq/runs/20260113/" --valid-time 2026-01-15T06:00:00
openngs link derived-from --from BCL-20260113 --to POOL-20260113

# --- 5. Demultiplex: one AnalysisRun, one output set, one nested set per sample -----------
openngs analysis-run create DEMUX-20260113 --valid-time 2026-01-15T07:00:00
openngs link used --from DEMUX-20260113 --to bclconvert-4.2.7
openngs link used --from DEMUX-20260113 --to BCL-20260113

openngs data-file-set create FASTQ-20260113 --produced-by DEMUX-20260113 \
  --xref "s3://acme-seq/fastq/20260113/"
openngs link derived-from --from FASTQ-20260113 --to BCL-20260113

for S in "${SAMPLES[@]}"; do
  # This sample's FASTQ pair, as a set: nested in the run-level set, and traced back to
  # the library it was sequenced from.
  openngs data-file-set create "FASTQ-0042-$S" --produced-by DEMUX-20260113
  openngs link part-of      --from "FASTQ-0042-$S" --to FASTQ-20260113
  openngs link derived-from --from "FASTQ-0042-$S" --to "LIB-0042-$S"

  for R in R1 R2; do
    openngs data-file create "0042-${S}_${R}.fastq.gz" --produced-by DEMUX-20260113 \
      --xref "drs://drs.acme.example/fastq/0042-${S}_${R}"
    openngs link part-of --from "0042-${S}_${R}.fastq.gz" --to "FASTQ-0042-$S"
  done
done

# --- 6. Secondary analysis, per sample -----------------------------------------------------
for S in "${SAMPLES[@]}"; do
  openngs analysis-run create "SAREK-0042-$S" --valid-time 2026-01-16T02:00:00
  openngs link used --from "SAREK-0042-$S" --to nf-core/sarek-3.4.0
  openngs link used --from "SAREK-0042-$S" --to "FASTQ-0042-$S"

  openngs data-file-set create "SAREK-0042-$S-OUT" --produced-by "SAREK-0042-$S" \
    --xref "s3://acme-seq/sarek/0042-$S/"
  openngs link derived-from --from "SAREK-0042-$S-OUT" --to "FASTQ-0042-$S"

  # File-level lineage where it matters: BAM from the two FASTQs, VCF from the BAM.
  openngs data-file create "0042-$S.bam" --produced-by "SAREK-0042-$S" \
    --derived-from "0042-${S}_R1.fastq.gz" --derived-from "0042-${S}_R2.fastq.gz"
  openngs data-file create "0042-$S.vcf.gz" --produced-by "SAREK-0042-$S" \
    --derived-from "0042-$S.bam"
  openngs link part-of --from "0042-$S.bam"    --to "SAREK-0042-$S-OUT"
  openngs link part-of --from "0042-$S.vcf.gz" --to "SAREK-0042-$S-OUT"
done

# --- 7. QC: a facet for the whole report, DataPoints for the values worth querying -------
# Register the example facet schema once; every attach references it by name.
openngs facet schema register qc-metrics \
  --file docs/facets/examples/qc_metrics/qc_metrics.schema.json

DUPLICATION=(11.2 9.8 14.7)
COVERAGE=(31.4 30.1 28.9)
for i in "${!SAMPLES[@]}"; do
  S=${SAMPLES[$i]}
  openngs facet attach --to "0042-${S}_R1.fastq.gz" --schema-id qc-metrics \
    --type QcMetricsFacet --producer "fastqc/0.12.1" \
    --data "{\"tool\":\"fastqc\",\"sample_name\":\"0042-$S\",\"metric_name\":\"openngs-dp:percent_duplication\",\"metric_value\":${DUPLICATION[$i]}}"

  openngs datapoint create "0042-$S-percent-duplication" --for "FASTQ-0042-$S" \
    --type openngs-dp:percent_duplication --kind number --value "${DUPLICATION[$i]}"
  openngs datapoint create "0042-$S-mean-coverage" --for "0042-$S.bam" \
    --type openngs-dp:mean_coverage --kind number --value "${COVERAGE[$i]}"
done

# --- 8. Identity: the LIMS registered the proband's tube under its own accession ---------
# A second record for the same physical tube, asserted identical by the operator who
# scanned both barcodes. Neither record is merged; queries decide how to treat the pair.
openngs specimen create LIMS-88213 --subject SUBJ-0042-P --xref "barcode:TUBE-0042-P"
openngs link same-as --from LIMS-88213 --to SPEC-0042-P \
  --asserted-by ACTOR-JDOE --method barcode_scan --confidence 1.0

echo
echo "Done. Try:"
echo "  openngs data-file show 0042-P.vcf.gz"
echo "  openngs datapoint list --for FASTQ-0042-P"
echo "  openngs specimen show SPEC-0042-P --events"
echo "  openngs event list --limit 5"
