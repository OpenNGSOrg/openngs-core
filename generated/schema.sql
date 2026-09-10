-- GENERATED from schema/openngs.yaml by `make gen` — never hand-edit.
-- # Abstract Class: Entity Description: Mixin providing the three-layer identity common to every node in the OpenNGS graph. Concrete entity types add no further slots by design: "freeze the topology, extend the nodes" means all type-specific detail belongs in facets, never in the entity itself. The one explicit exception is DataPoint, whose entire reason for existing is a value and what kind of measurement it is.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Subject Description: The source a specimen was taken from: a person, an organism, or an environmental sampling site (a lake, a river station, a soil plot). The root of every physical chain - what lets specimens taken from the same source, at different times, be recognized as such, and what a cohort, a pedigree, or a per-site time series groups.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Specimen Description: Material as collected, before any lab processing. An aliquot taken from a Specimen is itself a Specimen, linked to its parent via a derived_from edge — aliquoting is a relationship, not a distinct entity type.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Extract Description: Nucleic acid extracted from a Specimen. A split or re-aliquoted portion of an Extract is itself an Extract, linked to its parent via derived_from.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Library Description: A sequencing-ready library prepared from an Extract. A split portion of a Library is itself a Library, linked to its parent via derived_from.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Pool Description: Multiple Libraries combined for a shared sequencing run. A re-pooled or split portion of a Pool is itself a Pool, linked to its parent via derived_from.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: SequencingRun Description: One execution of a sequencing instrument.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: DataFile Description: A reference to a data payload (FASTQ, BAM, VCF, ...). OpenNGS is a metadata plane, not a data plane: it never stores the payload itself, only references to it.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: AnalysisRun Description: One execution of an analysis pipeline or tool.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: DataFileSet Description: A named group of DataFiles produced together by one SequencingRun or AnalysisRun - a raw BCL run folder, or the result files of one pipeline execution. Member DataFiles join via part_of; the set itself is linked to the run that made it via produced_by, the same predicate an individual DataFile uses. A DataFileSet may itself be part_of another DataFileSet, e.g. a per-sample FASTQ subset nested inside a multi-sample demultiplexing run's overall output set.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Protocol Description: A documented procedure used by a process.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Reagent Description: A kit lot, not a kit type. Lot-level granularity is intentional: it is what makes the QC-by-kit-lot forensics query possible.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Actor Description: A human or an instrument that performed or operated a process.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Project Description: An administrative grouping of specimens, runs, and analyses.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: Context Description: A generic scientific or analytical grouping that gives meaning to a set of entities considered together, e.g. a cohort of Subjects, a cohort of Specimens, or a pedigree linking the Subjects in a familial genetic test. Distinct from Project, which is an administrative grouping (funding, ownership) rather than a scientific one; the two commonly cut across each other and both may apply to the same entity. Any entity type may join a Context via part_of; what role it plays in that context (e.g. proband, affected, control) is not a field on the entity or the edge but a facet attached to the part_of edge, so it stays open-ended without growing this closed entity/edge set.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: DataPoint Description: An atomic, independently-correctable measurement or fact - a QC metric worth cross-cutting queries, a business-logic value, or a fact pulled from a third-party system. Formal, vendor-versioned, multi-field tool output (FastQC, DRAGEN, ...) belongs in a Facet instead, kept whole; a DataPoint is for the specific fields worth querying across the graph on their own, or facts that never came from a tool report at all.
--     * Slot: datapoint_type Description: What was measured, as a CURIE. Prefer a term from schema/vocabularies/datapoints.yaml (e.g. openngs-dp:percent_duplication) where one exists; fall back to a vendor or institution CURIE otherwise (e.g. acme-lims:sample-priority). Not a closed enum: the datapoint vocabulary is additive, and most business-logic datapoints will never belong to it at all.
--     * Slot: value_kind Description: Which of value_number/value_text/value_boolean is populated.
--     * Slot: value_number Description: Populated when value_kind is number. Covers both integer and float - a float represents realistic QC-scale integer magnitudes (read counts, etc.) exactly, so a separate integer column isn't worth it.
--     * Slot: value_text Description: Populated when value_kind is text.
--     * Slot: value_boolean Description: Populated when value_kind is boolean.
--     * Slot: internal_id Description: Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.
--     * Slot: name Description: Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Abstract Class: Edge Description: A lineage relationship or identity assertion between two entities. Edges are first-class objects, not slots on Entity, because facets can attach to an edge and same_as needs its own evidentiary fields.
--     * Slot: edge_id Description: Opaque, immutable UUIDv7.
--     * Slot: edge_subject Description: internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents' own field once events.yaml's slots merge into this schema's single flat namespace.
--     * Slot: predicate
--     * Slot: object Description: internal_id of the Entity this edge points to.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Class: SameAsEdge Description: An identity assertion, never a merge: same_as never collapses two nodes into one. Deduplication is resolved at query time via same_as closure at a caller-supplied confidence threshold.
--     * Slot: asserted_by Description: internal_id of the Actor making this identity assertion.
--     * Slot: asserted_at Description: When the identity assertion was made.
--     * Slot: method Description: How the assertion was made, e.g. barcode_scan, operator_claim, fingerprint_concordance, submission_receipt.
--     * Slot: confidence
--     * Slot: edge_id Description: Opaque, immutable UUIDv7.
--     * Slot: edge_subject Description: internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents' own field once events.yaml's slots merge into this schema's single flat namespace.
--     * Slot: predicate
--     * Slot: object Description: internal_id of the Entity this edge points to.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
-- # Abstract Class: Facet Description: A named, versioned, independently-schema'd metadata object attached to an entity or edge. _producer and _schemaURL are mandatory on every facet so an unknown consumer can tell what wrote it and validate it without prior knowledge.
--     * Slot: id
--     * Slot: attached_to Description: internal_id of the Entity, or edge_id of the Edge, this facet describes.
--     * Slot: _producer Description: Identifies what produced this facet, e.g. a tool name and version, or a system name.
--     * Slot: _schemaURL Description: URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.
-- # Class: Event Description: One occurrence in the append-only log - a CloudEvents 1.0 envelope. Never updated or deleted once written (invariant 1); a correction would be a new Event whose supersedes names the event_id it corrects (not yet emitted by anything).
--     * Slot: event_id Description: Opaque, immutable UUIDv7 - CloudEvents' `id`.
--     * Slot: source Description: CloudEvents `source` - identifies what emitted this event, e.g. "openngs-cli". Not a URI validated against any scheme, just a string identifying the producer.
--     * Slot: type Description: CloudEvents `type` - what kind of fact this event records.
--     * Slot: specversion Description: CloudEvents spec version. Always "1.0" for now.
--     * Slot: subject Description: CloudEvents `subject` - the internal_id/edge_id/facet_id/schema_id this event concerns, when there's a single obvious one. Kept as `subject`, matching the CloudEvents spec field name exactly; `Edge`'s own subject-of-a-triple slot is named `edge_subject` instead, to leave this name free.
--     * Slot: time Description: CloudEvents `time` - when this occurrence was recorded. Mirrors transaction_time; kept as its own field because CloudEvents consumers expect it at the envelope level.
--     * Slot: datacontenttype Description: CloudEvents `datacontenttype` for `payload`. Always "application/json" for now.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: transaction_time Description: When OpenNGS learned the fact (invariant 2). Always wall-clock now at write time.
--     * Slot: recorded_by Description: Who recorded this event - the authenticated principal for an API write, the operating system or configured identity for a CLI one. Distinct from `source`, which says which program produced the event ("openngs-api"), not which person or service was behind it. Optional: a deployment that has deliberately turned authentication off has no principal to record, and saying so honestly is better than inventing one.
--     * Slot: supersedes Description: event_id of a prior event this one corrects (invariant 1). Not yet populated by anything the CLI does - the column exists so this schema doesn't need to change when corrections are designed.
--     * Slot: supersede_reason Description: Why the correction was made. Required alongside supersedes: a correction with no stated reason is not worth more than the wrong fact it replaces.
--     * Slot: payload Description: The type-specific content (CloudEvents `data`, minus the bitemporal/supersedes fields already promoted to real columns above), as a JSON string - the same portable TEXT-column pattern already used for FacetInstance.data/FacetSchema.json_schema.
-- # Class: FacetInstance Description: A facet instance of a type not (yet, or ever) promoted to core. `data` is validated at write time against the JSON Schema `_schemaURL` points to - a local file for now; fetching a remote URL isn't supported yet.
--     * Slot: facet_id Description: Opaque, immutable UUIDv7, same shape as internal_id/edge_id.
--     * Slot: facet_type Description: The class name within the schema at _schemaURL this instance conforms to - a schema file can define more than one class.
--     * Slot: data Description: This instance's fields, serialized as a JSON string. A plain string column, not a native json/jsonb type, so the same DDL is portable between SQLite and Postgres.
--     * Slot: valid_time Description: When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.
--     * Slot: retracted_at Description: Transaction time at which this row stopped being believed - set by a retraction event. NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.
--     * Slot: retracted_by_event Description: event_id of the retraction event that set retracted_at.
--     * Slot: attached_to Description: internal_id of the Entity, or edge_id of the Edge, this facet describes.
--     * Slot: _producer Description: Identifies what produced this facet, e.g. a tool name and version, or a system name.
--     * Slot: _schemaURL Description: URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.
-- # Class: FacetSchema Description: One registered, immutable version of a JSON Schema document. `json_schema` is typically generated externally via `linkml generate json-schema` - the conversion itself stays outside OpenNGS's runtime dependencies; this store only ever accepts and serves already-generated JSON Schema text.
--     * Slot: schema_id Description: Opaque, immutable UUIDv7, same shape as internal_id/edge_id/facet_id.
--     * Slot: schema_name Description: openngs://{org}/{namespace}/facet-schema/{local_id} - the same naming convention every other named thing in OpenNGS uses. Not unique: multiple FacetSchema rows can share a schema_name, one per registered version.
--     * Slot: json_schema Description: The registered JSON Schema document, as a JSON string - a plain TEXT column, not a native json/jsonb type, for the same SQLite/Postgres portability reason as FacetInstance.data.
-- # Class: Entity_xrefs
--     * Slot: Entity_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Subject_xrefs
--     * Slot: Subject_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Specimen_xrefs
--     * Slot: Specimen_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Extract_xrefs
--     * Slot: Extract_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Library_xrefs
--     * Slot: Library_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Pool_xrefs
--     * Slot: Pool_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: SequencingRun_xrefs
--     * Slot: SequencingRun_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: DataFile_xrefs
--     * Slot: DataFile_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: AnalysisRun_xrefs
--     * Slot: AnalysisRun_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: DataFileSet_xrefs
--     * Slot: DataFileSet_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Protocol_xrefs
--     * Slot: Protocol_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Reagent_xrefs
--     * Slot: Reagent_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Actor_xrefs
--     * Slot: Actor_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Project_xrefs
--     * Slot: Project_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: Context_xrefs
--     * Slot: Context_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.
-- # Class: DataPoint_xrefs
--     * Slot: DataPoint_internal_id Description: Autocreated FK slot
--     * Slot: xrefs Description: CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.

CREATE TABLE "Entity" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Entity_internal_id" ON "Entity" (internal_id);

CREATE TABLE "Subject" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Subject_internal_id" ON "Subject" (internal_id);

CREATE TABLE "Specimen" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Specimen_internal_id" ON "Specimen" (internal_id);

CREATE TABLE "Extract" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Extract_internal_id" ON "Extract" (internal_id);

CREATE TABLE "Library" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Library_internal_id" ON "Library" (internal_id);

CREATE TABLE "Pool" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Pool_internal_id" ON "Pool" (internal_id);

CREATE TABLE "SequencingRun" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_SequencingRun_internal_id" ON "SequencingRun" (internal_id);

CREATE TABLE "DataFile" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataFile_internal_id" ON "DataFile" (internal_id);

CREATE TABLE "AnalysisRun" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_AnalysisRun_internal_id" ON "AnalysisRun" (internal_id);

CREATE TABLE "DataFileSet" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataFileSet_internal_id" ON "DataFileSet" (internal_id);

CREATE TABLE "Protocol" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Protocol_internal_id" ON "Protocol" (internal_id);

CREATE TABLE "Reagent" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Reagent_internal_id" ON "Reagent" (internal_id);

CREATE TABLE "Actor" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Actor_internal_id" ON "Actor" (internal_id);

CREATE TABLE "Project" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Project_internal_id" ON "Project" (internal_id);

CREATE TABLE "Context" (
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_Context_internal_id" ON "Context" (internal_id);

CREATE TABLE "DataPoint" (
	datapoint_type TEXT NOT NULL,
	value_kind VARCHAR(7) NOT NULL,
	value_number FLOAT,
	value_text TEXT,
	value_boolean BOOLEAN,
	internal_id TEXT NOT NULL,
	name TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (internal_id)
);
CREATE INDEX "ix_DataPoint_internal_id" ON "DataPoint" (internal_id);

CREATE TABLE "Edge" (
	edge_id TEXT NOT NULL,
	edge_subject TEXT NOT NULL,
	predicate VARCHAR(13) NOT NULL,
	object TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (edge_id)
);
CREATE INDEX "ix_Edge_edge_id" ON "Edge" (edge_id);

CREATE TABLE "SameAsEdge" (
	asserted_by TEXT NOT NULL,
	asserted_at DATETIME NOT NULL,
	method TEXT NOT NULL,
	confidence FLOAT NOT NULL,
	edge_id TEXT NOT NULL,
	edge_subject TEXT NOT NULL,
	predicate VARCHAR(13) NOT NULL,
	object TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	PRIMARY KEY (edge_id)
);
CREATE INDEX "ix_SameAsEdge_edge_id" ON "SameAsEdge" (edge_id);

CREATE TABLE "Facet" (
	id INTEGER NOT NULL,
	attached_to TEXT NOT NULL,
	_producer TEXT NOT NULL,
	"_schemaURL" TEXT NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX "ix_Facet_id" ON "Facet" (id);

CREATE TABLE "Event" (
	event_id TEXT NOT NULL,
	source TEXT NOT NULL,
	type VARCHAR(24) NOT NULL,
	specversion TEXT NOT NULL,
	subject TEXT,
	time DATETIME NOT NULL,
	datacontenttype TEXT,
	valid_time DATETIME NOT NULL,
	transaction_time DATETIME NOT NULL,
	recorded_by TEXT,
	supersedes TEXT,
	supersede_reason TEXT,
	payload TEXT NOT NULL,
	PRIMARY KEY (event_id)
);
CREATE INDEX "ix_Event_event_id" ON "Event" (event_id);

CREATE TABLE "FacetInstance" (
	facet_id TEXT NOT NULL,
	facet_type TEXT NOT NULL,
	data TEXT NOT NULL,
	valid_time DATETIME NOT NULL,
	retracted_at DATETIME,
	retracted_by_event TEXT,
	attached_to TEXT NOT NULL,
	_producer TEXT NOT NULL,
	"_schemaURL" TEXT NOT NULL,
	PRIMARY KEY (facet_id)
);
CREATE INDEX "ix_FacetInstance_facet_id" ON "FacetInstance" (facet_id);

CREATE TABLE "FacetSchema" (
	schema_id TEXT NOT NULL,
	schema_name TEXT NOT NULL,
	json_schema TEXT NOT NULL,
	PRIMARY KEY (schema_id)
);
CREATE INDEX "ix_FacetSchema_schema_id" ON "FacetSchema" (schema_id);

CREATE TABLE "Entity_xrefs" (
	"Entity_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Entity_internal_id", xrefs),
	FOREIGN KEY("Entity_internal_id") REFERENCES "Entity" (internal_id)
);
CREATE INDEX "ix_Entity_xrefs_xrefs" ON "Entity_xrefs" (xrefs);
CREATE INDEX "ix_Entity_xrefs_Entity_internal_id" ON "Entity_xrefs" ("Entity_internal_id");

CREATE TABLE "Subject_xrefs" (
	"Subject_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Subject_internal_id", xrefs),
	FOREIGN KEY("Subject_internal_id") REFERENCES "Subject" (internal_id)
);
CREATE INDEX "ix_Subject_xrefs_xrefs" ON "Subject_xrefs" (xrefs);
CREATE INDEX "ix_Subject_xrefs_Subject_internal_id" ON "Subject_xrefs" ("Subject_internal_id");

CREATE TABLE "Specimen_xrefs" (
	"Specimen_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Specimen_internal_id", xrefs),
	FOREIGN KEY("Specimen_internal_id") REFERENCES "Specimen" (internal_id)
);
CREATE INDEX "ix_Specimen_xrefs_Specimen_internal_id" ON "Specimen_xrefs" ("Specimen_internal_id");
CREATE INDEX "ix_Specimen_xrefs_xrefs" ON "Specimen_xrefs" (xrefs);

CREATE TABLE "Extract_xrefs" (
	"Extract_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Extract_internal_id", xrefs),
	FOREIGN KEY("Extract_internal_id") REFERENCES "Extract" (internal_id)
);
CREATE INDEX "ix_Extract_xrefs_xrefs" ON "Extract_xrefs" (xrefs);
CREATE INDEX "ix_Extract_xrefs_Extract_internal_id" ON "Extract_xrefs" ("Extract_internal_id");

CREATE TABLE "Library_xrefs" (
	"Library_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Library_internal_id", xrefs),
	FOREIGN KEY("Library_internal_id") REFERENCES "Library" (internal_id)
);
CREATE INDEX "ix_Library_xrefs_Library_internal_id" ON "Library_xrefs" ("Library_internal_id");
CREATE INDEX "ix_Library_xrefs_xrefs" ON "Library_xrefs" (xrefs);

CREATE TABLE "Pool_xrefs" (
	"Pool_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Pool_internal_id", xrefs),
	FOREIGN KEY("Pool_internal_id") REFERENCES "Pool" (internal_id)
);
CREATE INDEX "ix_Pool_xrefs_Pool_internal_id" ON "Pool_xrefs" ("Pool_internal_id");
CREATE INDEX "ix_Pool_xrefs_xrefs" ON "Pool_xrefs" (xrefs);

CREATE TABLE "SequencingRun_xrefs" (
	"SequencingRun_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("SequencingRun_internal_id", xrefs),
	FOREIGN KEY("SequencingRun_internal_id") REFERENCES "SequencingRun" (internal_id)
);
CREATE INDEX "ix_SequencingRun_xrefs_xrefs" ON "SequencingRun_xrefs" (xrefs);
CREATE INDEX "ix_SequencingRun_xrefs_SequencingRun_internal_id" ON "SequencingRun_xrefs" ("SequencingRun_internal_id");

CREATE TABLE "DataFile_xrefs" (
	"DataFile_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataFile_internal_id", xrefs),
	FOREIGN KEY("DataFile_internal_id") REFERENCES "DataFile" (internal_id)
);
CREATE INDEX "ix_DataFile_xrefs_xrefs" ON "DataFile_xrefs" (xrefs);
CREATE INDEX "ix_DataFile_xrefs_DataFile_internal_id" ON "DataFile_xrefs" ("DataFile_internal_id");

CREATE TABLE "AnalysisRun_xrefs" (
	"AnalysisRun_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("AnalysisRun_internal_id", xrefs),
	FOREIGN KEY("AnalysisRun_internal_id") REFERENCES "AnalysisRun" (internal_id)
);
CREATE INDEX "ix_AnalysisRun_xrefs_AnalysisRun_internal_id" ON "AnalysisRun_xrefs" ("AnalysisRun_internal_id");
CREATE INDEX "ix_AnalysisRun_xrefs_xrefs" ON "AnalysisRun_xrefs" (xrefs);

CREATE TABLE "DataFileSet_xrefs" (
	"DataFileSet_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataFileSet_internal_id", xrefs),
	FOREIGN KEY("DataFileSet_internal_id") REFERENCES "DataFileSet" (internal_id)
);
CREATE INDEX "ix_DataFileSet_xrefs_DataFileSet_internal_id" ON "DataFileSet_xrefs" ("DataFileSet_internal_id");
CREATE INDEX "ix_DataFileSet_xrefs_xrefs" ON "DataFileSet_xrefs" (xrefs);

CREATE TABLE "Protocol_xrefs" (
	"Protocol_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Protocol_internal_id", xrefs),
	FOREIGN KEY("Protocol_internal_id") REFERENCES "Protocol" (internal_id)
);
CREATE INDEX "ix_Protocol_xrefs_xrefs" ON "Protocol_xrefs" (xrefs);
CREATE INDEX "ix_Protocol_xrefs_Protocol_internal_id" ON "Protocol_xrefs" ("Protocol_internal_id");

CREATE TABLE "Reagent_xrefs" (
	"Reagent_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Reagent_internal_id", xrefs),
	FOREIGN KEY("Reagent_internal_id") REFERENCES "Reagent" (internal_id)
);
CREATE INDEX "ix_Reagent_xrefs_xrefs" ON "Reagent_xrefs" (xrefs);
CREATE INDEX "ix_Reagent_xrefs_Reagent_internal_id" ON "Reagent_xrefs" ("Reagent_internal_id");

CREATE TABLE "Actor_xrefs" (
	"Actor_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Actor_internal_id", xrefs),
	FOREIGN KEY("Actor_internal_id") REFERENCES "Actor" (internal_id)
);
CREATE INDEX "ix_Actor_xrefs_Actor_internal_id" ON "Actor_xrefs" ("Actor_internal_id");
CREATE INDEX "ix_Actor_xrefs_xrefs" ON "Actor_xrefs" (xrefs);

CREATE TABLE "Project_xrefs" (
	"Project_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Project_internal_id", xrefs),
	FOREIGN KEY("Project_internal_id") REFERENCES "Project" (internal_id)
);
CREATE INDEX "ix_Project_xrefs_Project_internal_id" ON "Project_xrefs" ("Project_internal_id");
CREATE INDEX "ix_Project_xrefs_xrefs" ON "Project_xrefs" (xrefs);

CREATE TABLE "Context_xrefs" (
	"Context_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("Context_internal_id", xrefs),
	FOREIGN KEY("Context_internal_id") REFERENCES "Context" (internal_id)
);
CREATE INDEX "ix_Context_xrefs_xrefs" ON "Context_xrefs" (xrefs);
CREATE INDEX "ix_Context_xrefs_Context_internal_id" ON "Context_xrefs" ("Context_internal_id");

CREATE TABLE "DataPoint_xrefs" (
	"DataPoint_internal_id" TEXT,
	xrefs TEXT,
	PRIMARY KEY ("DataPoint_internal_id", xrefs),
	FOREIGN KEY("DataPoint_internal_id") REFERENCES "DataPoint" (internal_id)
);
CREATE INDEX "ix_DataPoint_xrefs_xrefs" ON "DataPoint_xrefs" (xrefs);
CREATE INDEX "ix_DataPoint_xrefs_DataPoint_internal_id" ON "DataPoint_xrefs" ("DataPoint_internal_id");


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
