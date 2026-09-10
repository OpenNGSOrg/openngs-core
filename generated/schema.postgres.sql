-- GENERATED from schema/openngs.yaml by `make gen` — never hand-edit.
CREATE TYPE "ValueKind" AS ENUM ('number', 'text', 'boolean');
CREATE TYPE "EdgePredicate" AS ENUM ('derived_from', 'part_of', 'characterizes', 'produced_by', 'used', 'same_as');
CREATE TYPE "EventType" AS ENUM ('entity_created', 'edge_created', 'same_as_edge_created', 'facet_instance_attached', 'facet_schema_registered', 'entity_xref_added', 'entity_corrected', 'entity_retracted', 'edge_retracted', 'same_as_edge_retracted', 'facet_instance_corrected', 'facet_instance_retracted');

CREATE TABLE "Entity" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Entity_internal_id" ON "Entity" (internal_id);
COMMENT ON TABLE "Entity" IS 'Mixin providing the three-layer identity common to every node in the OpenNGS graph. Concrete entity types add no further slots by design: "freeze the topology, extend the nodes" means all type-specific detail belongs in facets, never in the entity itself. The one explicit exception is DataPoint, whose entire reason for existing is a value and what kind of measurement it is.';
COMMENT ON COLUMN "Entity".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Entity".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Entity".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Entity".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Entity".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Subject" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Subject_internal_id" ON "Subject" (internal_id);
COMMENT ON TABLE "Subject" IS 'The source a specimen was taken from: a person, an organism, or an environmental sampling site (a lake, a river station, a soil plot). The root of every physical chain - what lets specimens taken from the same source, at different times, be recognized as such, and what a cohort, a pedigree, or a per-site time series groups.';
COMMENT ON COLUMN "Subject".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Subject".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Subject".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Subject".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Subject".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Specimen" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Specimen_internal_id" ON "Specimen" (internal_id);
COMMENT ON TABLE "Specimen" IS 'Material as collected, before any lab processing. An aliquot taken from a Specimen is itself a Specimen, linked to its parent via a derived_from edge — aliquoting is a relationship, not a distinct entity type.';
COMMENT ON COLUMN "Specimen".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Specimen".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Specimen".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Specimen".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Specimen".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Extract" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Extract_internal_id" ON "Extract" (internal_id);
COMMENT ON TABLE "Extract" IS 'Nucleic acid extracted from a Specimen. A split or re-aliquoted portion of an Extract is itself an Extract, linked to its parent via derived_from.';
COMMENT ON COLUMN "Extract".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Extract".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Extract".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Extract".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Extract".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Library" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Library_internal_id" ON "Library" (internal_id);
COMMENT ON TABLE "Library" IS 'A sequencing-ready library prepared from an Extract. A split portion of a Library is itself a Library, linked to its parent via derived_from.';
COMMENT ON COLUMN "Library".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Library".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Library".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Library".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Library".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Pool" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Pool_internal_id" ON "Pool" (internal_id);
COMMENT ON TABLE "Pool" IS 'Multiple Libraries combined for a shared sequencing run. A re-pooled or split portion of a Pool is itself a Pool, linked to its parent via derived_from.';
COMMENT ON COLUMN "Pool".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Pool".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Pool".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Pool".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Pool".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "SequencingRun" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_SequencingRun_internal_id" ON "SequencingRun" (internal_id);
COMMENT ON TABLE "SequencingRun" IS 'One execution of a sequencing instrument.';
COMMENT ON COLUMN "SequencingRun".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "SequencingRun".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "SequencingRun".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "SequencingRun".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "SequencingRun".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "DataFile" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataFile_internal_id" ON "DataFile" (internal_id);
COMMENT ON TABLE "DataFile" IS 'A reference to a data payload (FASTQ, BAM, VCF, ...). OpenNGS is a metadata plane, not a data plane: it never stores the payload itself, only references to it.';
COMMENT ON COLUMN "DataFile".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "DataFile".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "DataFile".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "DataFile".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "DataFile".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "AnalysisRun" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_AnalysisRun_internal_id" ON "AnalysisRun" (internal_id);
COMMENT ON TABLE "AnalysisRun" IS 'One execution of an analysis pipeline or tool.';
COMMENT ON COLUMN "AnalysisRun".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "AnalysisRun".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "AnalysisRun".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "AnalysisRun".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "AnalysisRun".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "DataFileSet" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataFileSet_internal_id" ON "DataFileSet" (internal_id);
COMMENT ON TABLE "DataFileSet" IS 'A named group of DataFiles produced together by one SequencingRun or AnalysisRun - a raw BCL run folder, or the result files of one pipeline execution. Member DataFiles join via part_of; the set itself is linked to the run that made it via produced_by, the same predicate an individual DataFile uses. A DataFileSet may itself be part_of another DataFileSet, e.g. a per-sample FASTQ subset nested inside a multi-sample demultiplexing run''s overall output set.';
COMMENT ON COLUMN "DataFileSet".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "DataFileSet".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "DataFileSet".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "DataFileSet".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "DataFileSet".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Protocol" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Protocol_internal_id" ON "Protocol" (internal_id);
COMMENT ON TABLE "Protocol" IS 'A documented procedure used by a process.';
COMMENT ON COLUMN "Protocol".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Protocol".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Protocol".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Protocol".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Protocol".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Reagent" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Reagent_internal_id" ON "Reagent" (internal_id);
COMMENT ON TABLE "Reagent" IS 'A kit lot, not a kit type. Lot-level granularity is intentional: it is what makes the QC-by-kit-lot forensics query possible.';
COMMENT ON COLUMN "Reagent".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Reagent".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Reagent".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Reagent".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Reagent".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Actor" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Actor_internal_id" ON "Actor" (internal_id);
COMMENT ON TABLE "Actor" IS 'A human or an instrument that performed or operated a process.';
COMMENT ON COLUMN "Actor".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Actor".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Actor".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Actor".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Actor".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Project" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Project_internal_id" ON "Project" (internal_id);
COMMENT ON TABLE "Project" IS 'An administrative grouping of specimens, runs, and analyses.';
COMMENT ON COLUMN "Project".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Project".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Project".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Project".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Project".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Context" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Context_internal_id" ON "Context" (internal_id);
COMMENT ON TABLE "Context" IS 'A generic scientific or analytical grouping that gives meaning to a set of entities considered together, e.g. a cohort of Subjects, a cohort of Specimens, or a pedigree linking the Subjects in a familial genetic test. Distinct from Project, which is an administrative grouping (funding, ownership) rather than a scientific one; the two commonly cut across each other and both may apply to the same entity. Any entity type may join a Context via part_of; what role it plays in that context (e.g. proband, affected, control) is not a field on the entity or the edge but a facet attached to the part_of edge, so it stays open-ended without growing this closed entity/edge set.';
COMMENT ON COLUMN "Context".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "Context".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "Context".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Context".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Context".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "DataPoint" (
	datapoint_type TEXT NOT NULL,
	value_kind "ValueKind" NOT NULL,
	value_number FLOAT,
	value_text TEXT,
	value_boolean BOOLEAN,
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataPoint_internal_id" ON "DataPoint" (internal_id);
COMMENT ON TABLE "DataPoint" IS 'An atomic, independently-correctable measurement or fact - a QC metric worth cross-cutting queries, a business-logic value, or a fact pulled from a third-party system. Formal, vendor-versioned, multi-field tool output (FastQC, DRAGEN, ...) belongs in a Facet instead, kept whole; a DataPoint is for the specific fields worth querying across the graph on their own, or facts that never came from a tool report at all.';
COMMENT ON COLUMN "DataPoint".datapoint_type IS 'What was measured, as a CURIE. Prefer a term from schema/vocabularies/datapoints.yaml (e.g. openngs-dp:percent_duplication) where one exists; fall back to a vendor or institution CURIE otherwise (e.g. acme-lims:sample-priority). Not a closed enum: the datapoint vocabulary is additive, and most business-logic datapoints will never belong to it at all.';
COMMENT ON COLUMN "DataPoint".value_kind IS 'Which of value_number/value_text/value_boolean is populated.';
COMMENT ON COLUMN "DataPoint".value_number IS 'Populated when value_kind is number. Covers both integer and float - a float represents realistic QC-scale integer magnitudes (read counts, etc.) exactly, so a separate integer column isn''t worth it.';
COMMENT ON COLUMN "DataPoint".value_text IS 'Populated when value_kind is text.';
COMMENT ON COLUMN "DataPoint".value_boolean IS 'Populated when value_kind is boolean.';
COMMENT ON COLUMN "DataPoint".internal_id IS 'Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.';
COMMENT ON COLUMN "DataPoint".name IS 'Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.';
COMMENT ON COLUMN "DataPoint".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "DataPoint".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "DataPoint".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Edge" (
	edge_id TEXT NOT NULL,
	edge_subject TEXT NOT NULL,
	predicate "EdgePredicate" NOT NULL,
	object TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (edge_id)
);
CREATE INDEX "ix_Edge_edge_id" ON "Edge" (edge_id);
COMMENT ON TABLE "Edge" IS 'A lineage relationship or identity assertion between two entities. Edges are first-class objects, not slots on Entity, because facets can attach to an edge and same_as needs its own evidentiary fields.';
COMMENT ON COLUMN "Edge".edge_id IS 'Opaque, immutable UUIDv7.';
COMMENT ON COLUMN "Edge".edge_subject IS 'internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents'' own field once events.yaml''s slots merge into this schema''s single flat namespace.';
COMMENT ON COLUMN "Edge".object IS 'internal_id of the Entity this edge points to.';
COMMENT ON COLUMN "Edge".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Edge".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "Edge".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "SameAsEdge" (
	asserted_by TEXT NOT NULL,
	asserted_at TIMESTAMP WITH TIME ZONE NOT NULL,
	method TEXT NOT NULL,
	confidence FLOAT NOT NULL,
	edge_id TEXT NOT NULL,
	edge_subject TEXT NOT NULL,
	predicate "EdgePredicate" NOT NULL,
	object TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	PRIMARY KEY (edge_id)
);
CREATE INDEX "ix_SameAsEdge_edge_id" ON "SameAsEdge" (edge_id);
COMMENT ON TABLE "SameAsEdge" IS 'An identity assertion, never a merge: same_as never collapses two nodes into one. Deduplication is resolved at query time via same_as closure at a caller-supplied confidence threshold.';
COMMENT ON COLUMN "SameAsEdge".asserted_by IS 'internal_id of the Actor making this identity assertion.';
COMMENT ON COLUMN "SameAsEdge".asserted_at IS 'When the identity assertion was made.';
COMMENT ON COLUMN "SameAsEdge".method IS 'How the assertion was made, e.g. barcode_scan, operator_claim, fingerprint_concordance, submission_receipt.';
COMMENT ON COLUMN "SameAsEdge".edge_id IS 'Opaque, immutable UUIDv7.';
COMMENT ON COLUMN "SameAsEdge".edge_subject IS 'internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents'' own field once events.yaml''s slots merge into this schema''s single flat namespace.';
COMMENT ON COLUMN "SameAsEdge".object IS 'internal_id of the Entity this edge points to.';
COMMENT ON COLUMN "SameAsEdge".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "SameAsEdge".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "SameAsEdge".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';

CREATE TABLE "Facet" (
	id SERIAL NOT NULL,
	attached_to TEXT NOT NULL,
	_producer TEXT NOT NULL,
	"_schemaURL" TEXT NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX "ix_Facet_id" ON "Facet" (id);
COMMENT ON TABLE "Facet" IS 'A named, versioned, independently-schema''d metadata object attached to an entity or edge. _producer and _schemaURL are mandatory on every facet so an unknown consumer can tell what wrote it and validate it without prior knowledge.';
COMMENT ON COLUMN "Facet".attached_to IS 'internal_id of the Entity, or edge_id of the Edge, this facet describes.';
COMMENT ON COLUMN "Facet"._producer IS 'Identifies what produced this facet, e.g. a tool name and version, or a system name.';
COMMENT ON COLUMN "Facet"."_schemaURL" IS 'URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.';

CREATE TABLE "Event" (
	event_id TEXT NOT NULL,
	source TEXT NOT NULL,
	type "EventType" NOT NULL,
	specversion TEXT NOT NULL,
	subject TEXT,
	time TIMESTAMP WITH TIME ZONE NOT NULL,
	datacontenttype TEXT,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	transaction_time TIMESTAMP WITH TIME ZONE NOT NULL,
	recorded_by TEXT,
	supersedes TEXT,
	supersede_reason TEXT,
	payload TEXT NOT NULL,
	PRIMARY KEY (event_id)
);
CREATE INDEX "ix_Event_event_id" ON "Event" (event_id);
COMMENT ON TABLE "Event" IS 'One occurrence in the append-only log - a CloudEvents 1.0 envelope. Never updated or deleted once written (invariant 1); a correction would be a new Event whose supersedes names the event_id it corrects (not yet emitted by anything).';
COMMENT ON COLUMN "Event".event_id IS 'Opaque, immutable UUIDv7 - CloudEvents'' `id`.';
COMMENT ON COLUMN "Event".source IS 'CloudEvents `source` - identifies what emitted this event, e.g. "openngs-cli". Not a URI validated against any scheme, just a string identifying the producer.';
COMMENT ON COLUMN "Event".type IS 'CloudEvents `type` - what kind of fact this event records.';
COMMENT ON COLUMN "Event".specversion IS 'CloudEvents spec version. Always "1.0" for now.';
COMMENT ON COLUMN "Event".subject IS 'CloudEvents `subject` - the internal_id/edge_id/facet_id/schema_id this event concerns, when there''s a single obvious one. Kept as `subject`, matching the CloudEvents spec field name exactly; `Edge`''s own subject-of-a-triple slot is named `edge_subject` instead, to leave this name free.';
COMMENT ON COLUMN "Event".time IS 'CloudEvents `time` - when this occurrence was recorded. Mirrors transaction_time; kept as its own field because CloudEvents consumers expect it at the envelope level.';
COMMENT ON COLUMN "Event".datacontenttype IS 'CloudEvents `datacontenttype` for `payload`. Always "application/json" for now.';
COMMENT ON COLUMN "Event".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "Event".transaction_time IS 'When OpenNGS learned the fact (invariant 2). Always wall-clock now at write time.';
COMMENT ON COLUMN "Event".recorded_by IS 'Who recorded this event - the authenticated principal for an API write, the operating system or configured identity for a CLI one. Distinct from `source`, which says which program produced the event ("openngs-api"), not which person or service was behind it. Optional: a deployment that has deliberately turned authentication off has no principal to record, and saying so honestly is better than inventing one.';
COMMENT ON COLUMN "Event".supersedes IS 'event_id of a prior event this one corrects (invariant 1). Not yet populated by anything the CLI does - the column exists so this schema doesn''t need to change when corrections are designed.';
COMMENT ON COLUMN "Event".supersede_reason IS 'Why the correction was made. Required alongside supersedes: a correction with no stated reason is not worth more than the wrong fact it replaces.';
COMMENT ON COLUMN "Event".payload IS 'The type-specific content (CloudEvents `data`, minus the bitemporal/supersedes fields already promoted to real columns above), as a JSON string - the same portable TEXT-column pattern already used for FacetInstance.data/FacetSchema.json_schema.';

CREATE TABLE "FacetInstance" (
	facet_id TEXT NOT NULL,
	facet_type TEXT NOT NULL,
	data TEXT NOT NULL,
	valid_time TIMESTAMP WITH TIME ZONE NOT NULL,
	retracted_at TIMESTAMP WITH TIME ZONE,
	retracted_by_event TEXT,
	attached_to TEXT NOT NULL,
	_producer TEXT NOT NULL,
	"_schemaURL" TEXT NOT NULL,
	PRIMARY KEY (facet_id)
);
CREATE INDEX "ix_FacetInstance_facet_id" ON "FacetInstance" (facet_id);
COMMENT ON TABLE "FacetInstance" IS 'A facet instance of a type not (yet, or ever) promoted to core. `data` is validated at write time against the JSON Schema `_schemaURL` points to - a local file for now fetching a remote URL isn''t supported yet.';
COMMENT ON COLUMN "FacetInstance".facet_id IS 'Opaque, immutable UUIDv7, same shape as internal_id/edge_id.';
COMMENT ON COLUMN "FacetInstance".facet_type IS 'The class name within the schema at _schemaURL this instance conforms to - a schema file can define more than one class.';
COMMENT ON COLUMN "FacetInstance".data IS 'This instance''s fields, serialized as a JSON string. A plain string column, not a native json/jsonb type, so the same DDL is portable between SQLite and Postgres.';
COMMENT ON COLUMN "FacetInstance".valid_time IS 'When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.';
COMMENT ON COLUMN "FacetInstance".retracted_at IS 'Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.';
COMMENT ON COLUMN "FacetInstance".retracted_by_event IS 'event_id of the retraction event that set retracted_at.';
COMMENT ON COLUMN "FacetInstance".attached_to IS 'internal_id of the Entity, or edge_id of the Edge, this facet describes.';
COMMENT ON COLUMN "FacetInstance"._producer IS 'Identifies what produced this facet, e.g. a tool name and version, or a system name.';
COMMENT ON COLUMN "FacetInstance"."_schemaURL" IS 'URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.';

CREATE TABLE "FacetSchema" (
	schema_id TEXT NOT NULL,
	schema_name TEXT NOT NULL,
	json_schema TEXT NOT NULL,
	PRIMARY KEY (schema_id)
);
CREATE INDEX "ix_FacetSchema_schema_id" ON "FacetSchema" (schema_id);
COMMENT ON TABLE "FacetSchema" IS 'One registered, immutable version of a JSON Schema document. `json_schema` is typically generated externally via `linkml generate json-schema` - the conversion itself stays outside OpenNGS''s runtime dependencies; this store only ever accepts and serves already-generated JSON Schema text.';
COMMENT ON COLUMN "FacetSchema".schema_id IS 'Opaque, immutable UUIDv7, same shape as internal_id/edge_id/facet_id.';
COMMENT ON COLUMN "FacetSchema".schema_name IS 'openngs://{org}/{namespace}/facet-schema/{local_id} - the same naming convention every other named thing in OpenNGS uses. Not unique: multiple FacetSchema rows can share a schema_name, one per registered version.';
COMMENT ON COLUMN "FacetSchema".json_schema IS 'The registered JSON Schema document, as a JSON string - a plain TEXT column, not a native json/jsonb type, for the same SQLite/Postgres portability reason as FacetInstance.data.';

CREATE TABLE "Entity_xrefs" (
	"Entity_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Entity_internal_id", xrefs),
	FOREIGN KEY("Entity_internal_id") REFERENCES "Entity" (internal_id)
);
CREATE INDEX "ix_Entity_xrefs_xrefs" ON "Entity_xrefs" (xrefs);
CREATE INDEX "ix_Entity_xrefs_Entity_internal_id" ON "Entity_xrefs" ("Entity_internal_id");
COMMENT ON TABLE "Entity_xrefs" IS 'None';
COMMENT ON COLUMN "Entity_xrefs"."Entity_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Entity_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Subject_xrefs" (
	"Subject_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Subject_internal_id", xrefs),
	FOREIGN KEY("Subject_internal_id") REFERENCES "Subject" (internal_id)
);
CREATE INDEX "ix_Subject_xrefs_Subject_internal_id" ON "Subject_xrefs" ("Subject_internal_id");
CREATE INDEX "ix_Subject_xrefs_xrefs" ON "Subject_xrefs" (xrefs);
COMMENT ON TABLE "Subject_xrefs" IS 'None';
COMMENT ON COLUMN "Subject_xrefs"."Subject_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Subject_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Specimen_xrefs" (
	"Specimen_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Specimen_internal_id", xrefs),
	FOREIGN KEY("Specimen_internal_id") REFERENCES "Specimen" (internal_id)
);
CREATE INDEX "ix_Specimen_xrefs_Specimen_internal_id" ON "Specimen_xrefs" ("Specimen_internal_id");
CREATE INDEX "ix_Specimen_xrefs_xrefs" ON "Specimen_xrefs" (xrefs);
COMMENT ON TABLE "Specimen_xrefs" IS 'None';
COMMENT ON COLUMN "Specimen_xrefs"."Specimen_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Specimen_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Extract_xrefs" (
	"Extract_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Extract_internal_id", xrefs),
	FOREIGN KEY("Extract_internal_id") REFERENCES "Extract" (internal_id)
);
CREATE INDEX "ix_Extract_xrefs_xrefs" ON "Extract_xrefs" (xrefs);
CREATE INDEX "ix_Extract_xrefs_Extract_internal_id" ON "Extract_xrefs" ("Extract_internal_id");
COMMENT ON TABLE "Extract_xrefs" IS 'None';
COMMENT ON COLUMN "Extract_xrefs"."Extract_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Extract_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Library_xrefs" (
	"Library_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Library_internal_id", xrefs),
	FOREIGN KEY("Library_internal_id") REFERENCES "Library" (internal_id)
);
CREATE INDEX "ix_Library_xrefs_xrefs" ON "Library_xrefs" (xrefs);
CREATE INDEX "ix_Library_xrefs_Library_internal_id" ON "Library_xrefs" ("Library_internal_id");
COMMENT ON TABLE "Library_xrefs" IS 'None';
COMMENT ON COLUMN "Library_xrefs"."Library_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Library_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Pool_xrefs" (
	"Pool_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Pool_internal_id", xrefs),
	FOREIGN KEY("Pool_internal_id") REFERENCES "Pool" (internal_id)
);
CREATE INDEX "ix_Pool_xrefs_Pool_internal_id" ON "Pool_xrefs" ("Pool_internal_id");
CREATE INDEX "ix_Pool_xrefs_xrefs" ON "Pool_xrefs" (xrefs);
COMMENT ON TABLE "Pool_xrefs" IS 'None';
COMMENT ON COLUMN "Pool_xrefs"."Pool_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Pool_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "SequencingRun_xrefs" (
	"SequencingRun_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("SequencingRun_internal_id", xrefs),
	FOREIGN KEY("SequencingRun_internal_id") REFERENCES "SequencingRun" (internal_id)
);
CREATE INDEX "ix_SequencingRun_xrefs_SequencingRun_internal_id" ON "SequencingRun_xrefs" ("SequencingRun_internal_id");
CREATE INDEX "ix_SequencingRun_xrefs_xrefs" ON "SequencingRun_xrefs" (xrefs);
COMMENT ON TABLE "SequencingRun_xrefs" IS 'None';
COMMENT ON COLUMN "SequencingRun_xrefs"."SequencingRun_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "SequencingRun_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "DataFile_xrefs" (
	"DataFile_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataFile_internal_id", xrefs),
	FOREIGN KEY("DataFile_internal_id") REFERENCES "DataFile" (internal_id)
);
CREATE INDEX "ix_DataFile_xrefs_DataFile_internal_id" ON "DataFile_xrefs" ("DataFile_internal_id");
CREATE INDEX "ix_DataFile_xrefs_xrefs" ON "DataFile_xrefs" (xrefs);
COMMENT ON TABLE "DataFile_xrefs" IS 'None';
COMMENT ON COLUMN "DataFile_xrefs"."DataFile_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "DataFile_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "AnalysisRun_xrefs" (
	"AnalysisRun_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("AnalysisRun_internal_id", xrefs),
	FOREIGN KEY("AnalysisRun_internal_id") REFERENCES "AnalysisRun" (internal_id)
);
CREATE INDEX "ix_AnalysisRun_xrefs_AnalysisRun_internal_id" ON "AnalysisRun_xrefs" ("AnalysisRun_internal_id");
CREATE INDEX "ix_AnalysisRun_xrefs_xrefs" ON "AnalysisRun_xrefs" (xrefs);
COMMENT ON TABLE "AnalysisRun_xrefs" IS 'None';
COMMENT ON COLUMN "AnalysisRun_xrefs"."AnalysisRun_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "AnalysisRun_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "DataFileSet_xrefs" (
	"DataFileSet_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataFileSet_internal_id", xrefs),
	FOREIGN KEY("DataFileSet_internal_id") REFERENCES "DataFileSet" (internal_id)
);
CREATE INDEX "ix_DataFileSet_xrefs_DataFileSet_internal_id" ON "DataFileSet_xrefs" ("DataFileSet_internal_id");
CREATE INDEX "ix_DataFileSet_xrefs_xrefs" ON "DataFileSet_xrefs" (xrefs);
COMMENT ON TABLE "DataFileSet_xrefs" IS 'None';
COMMENT ON COLUMN "DataFileSet_xrefs"."DataFileSet_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "DataFileSet_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Protocol_xrefs" (
	"Protocol_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Protocol_internal_id", xrefs),
	FOREIGN KEY("Protocol_internal_id") REFERENCES "Protocol" (internal_id)
);
CREATE INDEX "ix_Protocol_xrefs_Protocol_internal_id" ON "Protocol_xrefs" ("Protocol_internal_id");
CREATE INDEX "ix_Protocol_xrefs_xrefs" ON "Protocol_xrefs" (xrefs);
COMMENT ON TABLE "Protocol_xrefs" IS 'None';
COMMENT ON COLUMN "Protocol_xrefs"."Protocol_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Protocol_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Reagent_xrefs" (
	"Reagent_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Reagent_internal_id", xrefs),
	FOREIGN KEY("Reagent_internal_id") REFERENCES "Reagent" (internal_id)
);
CREATE INDEX "ix_Reagent_xrefs_Reagent_internal_id" ON "Reagent_xrefs" ("Reagent_internal_id");
CREATE INDEX "ix_Reagent_xrefs_xrefs" ON "Reagent_xrefs" (xrefs);
COMMENT ON TABLE "Reagent_xrefs" IS 'None';
COMMENT ON COLUMN "Reagent_xrefs"."Reagent_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Reagent_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Actor_xrefs" (
	"Actor_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Actor_internal_id", xrefs),
	FOREIGN KEY("Actor_internal_id") REFERENCES "Actor" (internal_id)
);
CREATE INDEX "ix_Actor_xrefs_Actor_internal_id" ON "Actor_xrefs" ("Actor_internal_id");
CREATE INDEX "ix_Actor_xrefs_xrefs" ON "Actor_xrefs" (xrefs);
COMMENT ON TABLE "Actor_xrefs" IS 'None';
COMMENT ON COLUMN "Actor_xrefs"."Actor_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Actor_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Project_xrefs" (
	"Project_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Project_internal_id", xrefs),
	FOREIGN KEY("Project_internal_id") REFERENCES "Project" (internal_id)
);
CREATE INDEX "ix_Project_xrefs_Project_internal_id" ON "Project_xrefs" ("Project_internal_id");
CREATE INDEX "ix_Project_xrefs_xrefs" ON "Project_xrefs" (xrefs);
COMMENT ON TABLE "Project_xrefs" IS 'None';
COMMENT ON COLUMN "Project_xrefs"."Project_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Project_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "Context_xrefs" (
	"Context_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Context_internal_id", xrefs),
	FOREIGN KEY("Context_internal_id") REFERENCES "Context" (internal_id)
);
CREATE INDEX "ix_Context_xrefs_Context_internal_id" ON "Context_xrefs" ("Context_internal_id");
CREATE INDEX "ix_Context_xrefs_xrefs" ON "Context_xrefs" (xrefs);
COMMENT ON TABLE "Context_xrefs" IS 'None';
COMMENT ON COLUMN "Context_xrefs"."Context_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "Context_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';

CREATE TABLE "DataPoint_xrefs" (
	"DataPoint_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataPoint_internal_id", xrefs),
	FOREIGN KEY("DataPoint_internal_id") REFERENCES "DataPoint" (internal_id)
);
CREATE INDEX "ix_DataPoint_xrefs_DataPoint_internal_id" ON "DataPoint_xrefs" ("DataPoint_internal_id");
CREATE INDEX "ix_DataPoint_xrefs_xrefs" ON "DataPoint_xrefs" (xrefs);
COMMENT ON TABLE "DataPoint_xrefs" IS 'None';
COMMENT ON COLUMN "DataPoint_xrefs"."DataPoint_internal_id" IS 'Autocreated FK slot';
COMMENT ON COLUMN "DataPoint_xrefs".xrefs IS 'CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.';


-- One entity of a given type per name, while it is believed. A retracted name is
-- free to reuse, which is why this is a partial index.
CREATE UNIQUE INDEX "uq_Subject_name" ON "Subject" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Specimen_name" ON "Specimen" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Extract_name" ON "Extract" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Library_name" ON "Library" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Pool_name" ON "Pool" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_SequencingRun_name" ON "SequencingRun" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_DataFile_name" ON "DataFile" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_AnalysisRun_name" ON "AnalysisRun" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_DataFileSet_name" ON "DataFileSet" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Protocol_name" ON "Protocol" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Reagent_name" ON "Reagent" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Actor_name" ON "Actor" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Project_name" ON "Project" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_Context_name" ON "Context" (name) WHERE retracted_at IS NULL;
CREATE UNIQUE INDEX "uq_DataPoint_name" ON "DataPoint" (name) WHERE retracted_at IS NULL;
