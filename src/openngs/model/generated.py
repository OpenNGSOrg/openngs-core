# GENERATED from schema/openngs.yaml by `make gen` — never hand-edit.
from __future__ import annotations

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer
)


metamodel_version = "1.11.0"
version = "None"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        serialize_by_alias = True,
        validate_by_name = True,
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )





class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'openngs',
     'default_range': 'string',
     'description': 'An open standard for sample lineage in sequencing labs. A '
                    'frozen core entity graph, with all variability confined to '
                    'versioned facets.',
     'id': 'https://openngs.org/schema/openngs',
     'imports': ['linkml:types',
                 'facets/_base',
                 'facets/generic',
                 'facets/schema_store',
                 'events'],
     'license': 'https://www.apache.org/licenses/LICENSE-2.0',
     'name': 'openngs',
     'prefixes': {'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'},
                  'openngs': {'prefix_prefix': 'openngs',
                              'prefix_reference': 'https://openngs.org/schema/openngs/'}},
     'source_file': 'schema/openngs.yaml',
     'title': 'OpenNGS'} )

class EventType(str, Enum):
    entity_created = "entity_created"
    """
    A new row in some entity table (any of the closed set, including DataPoint).
    """
    edge_created = "edge_created"
    """
    A new row in the Edge table (any predicate but same_as).
    """
    same_as_edge_created = "same_as_edge_created"
    """
    A new row in the SameAsEdge table.
    """
    facet_instance_attached = "facet_instance_attached"
    """
    A new row in FacetInstance.
    """
    facet_schema_registered = "facet_schema_registered"
    """
    A new row in FacetSchema.
    """
    entity_xref_added = "entity_xref_added"
    """
    One more external identifier for an entity that already exists. Additive, not a correction: the entity was right, it now has one more name. The commonest late-arriving fact there is - an ENA/SRA accession, a barcode assigned after registration, an ID from a system integrated later.
    """
    entity_corrected = "entity_corrected"
    """
    An entity's content was wrong and is replaced. The payload carries the full corrected state, never a diff, so replay needs no knowledge of what came before. Covers DataPoint's value_* fields too.
    """
    entity_retracted = "entity_retracted"
    """
    An entity should never have existed. Sets retracted_at; the row stays in the projection but is filtered out of every read by default.
    """
    edge_retracted = "edge_retracted"
    """
    A relationship in the Edge table is false and stops being believed.
    """
    same_as_edge_retracted = "same_as_edge_retracted"
    """
    An identity assertion is withdrawn.
    """
    facet_instance_corrected = "facet_instance_corrected"
    """
    A facet instance's data was wrong and is replaced, keeping the same facet_id believed.
    """
    facet_instance_retracted = "facet_instance_retracted"
    """
    A facet instance should never have been attached.
    """


class EdgePredicate(str, Enum):
    derived_from = "derived_from"
    """
    Material or data transformation. The backbone of the graph. Also used self-referentially (Specimen→Specimen, Extract→Extract, Library→Library, Pool→Pool) to represent aliquoting, splitting, or re-pooling, so there is no separate Aliquot entity type.
    """
    part_of = "part_of"
    """
    Composition, e.g. pool membership, DataFileSet membership (including a DataFileSet nested inside another), or membership in a Context.
    """
    characterizes = "characterizes"
    """
    A DataPoint to the entity it characterizes: DataPoint→Entity. Replaces measured_by - retired, unused, and pointed the wrong way for a DataPoint's own `create` to work like every other entity's. Unconstrained target type, like derived_from/part_of/same_as.
    """
    produced_by = "produced_by"
    """
    Links an output to the process that made it.
    """
    used = "used"
    """
    Links a process to the Protocol, Reagent, or Actor it consumed, or to the DataFile / DataFileSet it took as input - so an AnalysisRun can assert exactly which dataset it ran against, independent of what its outputs' derived_from edges declare.
    """
    same_as = "same_as"
    """
    An identity assertion, always carried on a SameAsEdge instance.
    """


class ValueKind(str, Enum):
    number = "number"
    """
    value_number is populated.
    """
    text = "text"
    """
    value_text is populated.
    """
    boolean = "boolean"
    """
    value_boolean is populated.
    """



class Facet(ConfiguredBaseModel):
    """
    A named, versioned, independently-schema'd metadata object attached to an entity or edge. _producer and _schemaURL are mandatory on every facet so an unknown consumer can tell what wrote it and validate it without prior knowledge.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True,
         'from_schema': 'https://openngs.org/schema/openngs/facets/base'})

    attached_to: str = Field(default=..., description="""internal_id of the Entity, or edge_id of the Edge, this facet describes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })
    producer: str = Field(default=..., alias="_producer", description="""Identifies what produced this facet, e.g. a tool name and version, or a system name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })
    schemaURL: str = Field(default=..., alias="_schemaURL", description="""URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })


class Event(ConfiguredBaseModel):
    """
    One occurrence in the append-only log - a CloudEvents 1.0 envelope. Never updated or deleted once written (invariant 1); a correction would be a new Event whose supersedes names the event_id it corrects (not yet emitted by anything).
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs/events'})

    event_id: str = Field(default=..., description="""Opaque, immutable UUIDv7 - CloudEvents' `id`.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    source: str = Field(default=..., description="""CloudEvents `source` - identifies what emitted this event, e.g. \"openngs-cli\". Not a URI validated against any scheme, just a string identifying the producer.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    type: EventType = Field(default=..., description="""CloudEvents `type` - what kind of fact this event records.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    specversion: str = Field(default=..., description="""CloudEvents spec version. Always \"1.0\" for now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    subject: Optional[str] = Field(default=None, description="""CloudEvents `subject` - the internal_id/edge_id/facet_id/schema_id this event concerns, when there's a single obvious one. Kept as `subject`, matching the CloudEvents spec field name exactly; `Edge`'s own subject-of-a-triple slot is named `edge_subject` instead, to leave this name free.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    time: datetime  = Field(default=..., description="""CloudEvents `time` - when this occurrence was recorded. Mirrors transaction_time; kept as its own field because CloudEvents consumers expect it at the envelope level.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    datacontenttype: Optional[str] = Field(default=None, description="""CloudEvents `datacontenttype` for `payload`. Always \"application/json\" for now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    transaction_time: datetime  = Field(default=..., description="""When OpenNGS learned the fact (invariant 2). Always wall-clock now at write time.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    recorded_by: Optional[str] = Field(default=None, description="""Who recorded this event - the authenticated principal for an API write, the operating system or configured identity for a CLI one. Distinct from `source`, which says which program produced the event (\"openngs-api\"), not which person or service was behind it. Optional: a deployment that has deliberately turned authentication off has no principal to record, and saying so honestly is better than inventing one.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    supersedes: Optional[str] = Field(default=None, description="""event_id of a prior event this one corrects (invariant 1). Not yet populated by anything the CLI does - the column exists so this schema doesn't need to change when corrections are designed.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    supersede_reason: Optional[str] = Field(default=None, description="""Why the correction was made. Required alongside supersedes: a correction with no stated reason is not worth more than the wrong fact it replaces.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })
    payload: str = Field(default=..., description="""The type-specific content (CloudEvents `data`, minus the bitemporal/supersedes fields already promoted to real columns above), as a JSON string - the same portable TEXT-column pattern already used for FacetInstance.data/FacetSchema.json_schema.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event']} })

    @field_validator('event_id')
    def pattern_event_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid event_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid event_id format: {v}"
            raise ValueError(err_msg)
        return v


class FacetInstance(Facet):
    """
    A facet instance of a type not (yet, or ever) promoted to core. `data` is validated at write time against the JSON Schema `_schemaURL` points to - a local file for now fetching a remote URL isn't supported yet.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs/facets/generic'})

    facet_id: str = Field(default=..., description="""Opaque, immutable UUIDv7, same shape as internal_id/edge_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance']} })
    facet_type: str = Field(default=..., description="""The class name within the schema at _schemaURL this instance conforms to - a schema file can define more than one class.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance']} })
    data: str = Field(default=..., description="""This instance's fields, serialized as a JSON string. A plain string column, not a native json/jsonb type, so the same DDL is portable between SQLite and Postgres.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    attached_to: str = Field(default=..., description="""internal_id of the Entity, or edge_id of the Edge, this facet describes.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })
    producer: str = Field(default=..., alias="_producer", description="""Identifies what produced this facet, e.g. a tool name and version, or a system name.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })
    schemaURL: str = Field(default=..., alias="_schemaURL", description="""URL of the schema this facet instance validates against, so an unknown consumer can validate an unknown third-party facet without prior knowledge of it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Facet']} })

    @field_validator('facet_id')
    def pattern_facet_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid facet_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid facet_id format: {v}"
            raise ValueError(err_msg)
        return v


class FacetSchema(ConfiguredBaseModel):
    """
    One registered, immutable version of a JSON Schema document. `json_schema` is typically generated externally via `linkml generate json-schema` - the conversion itself stays outside OpenNGS's runtime dependencies; this store only ever accepts and serves already-generated JSON Schema text.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs/facets/schema_store'})

    schema_id: str = Field(default=..., description="""Opaque, immutable UUIDv7, same shape as internal_id/edge_id/facet_id.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetSchema']} })
    schema_name: str = Field(default=..., description="""openngs://{org}/{namespace}/facet-schema/{local_id} - the same naming convention every other named thing in OpenNGS uses. Not unique: multiple FacetSchema rows can share a schema_name, one per registered version.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetSchema']} })
    json_schema: str = Field(default=..., description="""The registered JSON Schema document, as a JSON string - a plain TEXT column, not a native json/jsonb type, for the same SQLite/Postgres portability reason as FacetInstance.data.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetSchema']} })

    @field_validator('schema_id')
    def pattern_schema_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid schema_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid schema_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('schema_name')
    def pattern_schema_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid schema_name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid schema_name format: {v}"
            raise ValueError(err_msg)
        return v


class Entity(ConfiguredBaseModel):
    """
    Mixin providing the three-layer identity common to every node in the OpenNGS graph. Concrete entity types add no further slots by design: \"freeze the topology, extend the nodes\" means all type-specific detail belongs in facets, never in the entity itself. The one explicit exception is DataPoint, whose entire reason for existing is a value and what kind of measurement it is.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True, 'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Subject(Entity):
    """
    The source a specimen was taken from: a person, an organism, or an environmental sampling site (a lake, a river station, a soil plot). The root of every physical chain - what lets specimens taken from the same source, at different times, be recognized as such, and what a cohort, a pedigree, or a per-site time series groups.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Specimen(Entity):
    """
    Material as collected, before any lab processing. An aliquot taken from a Specimen is itself a Specimen, linked to its parent via a derived_from edge — aliquoting is a relationship, not a distinct entity type.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Extract(Entity):
    """
    Nucleic acid extracted from a Specimen. A split or re-aliquoted portion of an Extract is itself an Extract, linked to its parent via derived_from.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Library(Entity):
    """
    A sequencing-ready library prepared from an Extract. A split portion of a Library is itself a Library, linked to its parent via derived_from.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Pool(Entity):
    """
    Multiple Libraries combined for a shared sequencing run. A re-pooled or split portion of a Pool is itself a Pool, linked to its parent via derived_from.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class SequencingRun(Entity):
    """
    One execution of a sequencing instrument.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class DataFile(Entity):
    """
    A reference to a data payload (FASTQ, BAM, VCF, ...). OpenNGS is a metadata plane, not a data plane: it never stores the payload itself, only references to it.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class AnalysisRun(Entity):
    """
    One execution of an analysis pipeline or tool.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class DataFileSet(Entity):
    """
    A named group of DataFiles produced together by one SequencingRun or AnalysisRun - a raw BCL run folder, or the result files of one pipeline execution. Member DataFiles join via part_of; the set itself is linked to the run that made it via produced_by, the same predicate an individual DataFile uses. A DataFileSet may itself be part_of another DataFileSet, e.g. a per-sample FASTQ subset nested inside a multi-sample demultiplexing run's overall output set.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Protocol(Entity):
    """
    A documented procedure used by a process.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Reagent(Entity):
    """
    A kit lot, not a kit type. Lot-level granularity is intentional: it is what makes the QC-by-kit-lot forensics query possible.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Actor(Entity):
    """
    A human or an instrument that performed or operated a process.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Project(Entity):
    """
    An administrative grouping of specimens, runs, and analyses.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Context(Entity):
    """
    A generic scientific or analytical grouping that gives meaning to a set of entities considered together, e.g. a cohort of Subjects, a cohort of Specimens, or a pedigree linking the Subjects in a familial genetic test. Distinct from Project, which is an administrative grouping (funding, ownership) rather than a scientific one; the two commonly cut across each other and both may apply to the same entity. Any entity type may join a Context via part_of; what role it plays in that context (e.g. proband, affected, control) is not a field on the entity or the edge but a facet attached to the part_of edge, so it stays open-ended without growing this closed entity/edge set.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class DataPoint(Entity):
    """
    An atomic, independently-correctable measurement or fact - a QC metric worth cross-cutting queries, a business-logic value, or a fact pulled from a third-party system. Formal, vendor-versioned, multi-field tool output (FastQC, DRAGEN, ...) belongs in a Facet instead, kept whole; a DataPoint is for the specific fields worth querying across the graph on their own, or facts that never came from a tool report at all.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs'})

    datapoint_type: str = Field(default=..., description="""What was measured, as a CURIE. Prefer a term from schema/vocabularies/datapoints.yaml (e.g. openngs-dp:percent_duplication) where one exists; fall back to a vendor or institution CURIE otherwise (e.g. acme-lims:sample-priority). Not a closed enum: the datapoint vocabulary is additive, and most business-logic datapoints will never belong to it at all.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataPoint']} })
    value_kind: ValueKind = Field(default=..., description="""Which of value_number/value_text/value_boolean is populated.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataPoint']} })
    value_number: Optional[float] = Field(default=None, description="""Populated when value_kind is number. Covers both integer and float - a float represents realistic QC-scale integer magnitudes (read counts, etc.) exactly, so a separate integer column isn't worth it.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataPoint']} })
    value_text: Optional[str] = Field(default=None, description="""Populated when value_kind is text.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataPoint']} })
    value_boolean: Optional[bool] = Field(default=None, description="""Populated when value_kind is boolean.""", json_schema_extra = { "linkml_meta": {'domain_of': ['DataPoint']} })
    internal_id: str = Field(default=..., description="""Opaque, immutable UUIDv7. Never derived from a barcode, accession, date, or subject attribute.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    name: str = Field(default=..., description="""Namespaced name: openngs://{org}/{namespace}/{entity_type}/{local_id}.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    xrefs: Optional[list[str]] = Field(default=None, description="""CURIEs identifying this entity in external systems, e.g. biosample:SAMN12345678. Many-to-many, additive, never authoritative.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Entity']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('internal_id')
    def pattern_internal_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid internal_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid internal_id format: {v}"
            raise ValueError(err_msg)
        return v

    @field_validator('name')
    def pattern_name(cls, v):
        pattern=re.compile(r"^openngs://[^/]+/[^/]+/[^/]+/.+$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid name format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid name format: {v}"
            raise ValueError(err_msg)
        return v


class Edge(ConfiguredBaseModel):
    """
    A lineage relationship or identity assertion between two entities. Edges are first-class objects, not slots on Entity, because facets can attach to an edge and same_as needs its own evidentiary fields.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'abstract': True, 'from_schema': 'https://openngs.org/schema/openngs'})

    edge_id: str = Field(default=..., description="""Opaque, immutable UUIDv7.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    edge_subject: str = Field(default=..., description="""internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents' own field once events.yaml's slots merge into this schema's single flat namespace.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    predicate: EdgePredicate = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    object: str = Field(default=..., description="""internal_id of the Entity this edge points to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('edge_id')
    def pattern_edge_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid edge_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid edge_id format: {v}"
            raise ValueError(err_msg)
        return v


class SameAsEdge(Edge):
    """
    An identity assertion, never a merge: same_as never collapses two nodes into one. Deduplication is resolved at query time via same_as closure at a caller-supplied confidence threshold.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://openngs.org/schema/openngs',
         'slot_usage': {'predicate': {'equals_string': 'same_as', 'name': 'predicate'}}})

    asserted_by: str = Field(default=..., description="""internal_id of the Actor making this identity assertion.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SameAsEdge']} })
    asserted_at: datetime  = Field(default=..., description="""When the identity assertion was made.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SameAsEdge']} })
    method: str = Field(default=..., description="""How the assertion was made, e.g. barcode_scan, operator_claim, fingerprint_concordance, submission_receipt.""", json_schema_extra = { "linkml_meta": {'domain_of': ['SameAsEdge']} })
    confidence: float = Field(default=..., ge=0, le=1, json_schema_extra = { "linkml_meta": {'domain_of': ['SameAsEdge']} })
    edge_id: str = Field(default=..., description="""Opaque, immutable UUIDv7.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    edge_subject: str = Field(default=..., description="""internal_id of the Entity this edge originates from. Named edge_subject, not subject, to leave `subject` free for CloudEvents' own field once events.yaml's slots merge into this schema's single flat namespace.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    predicate: Literal["same_as"] = Field(default=..., json_schema_extra = { "linkml_meta": {'domain_of': ['Edge'], 'equals_string': 'same_as'} })
    object: str = Field(default=..., description="""internal_id of the Entity this edge points to.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Edge']} })
    valid_time: datetime  = Field(default=..., description="""When the fact was true in the lab (invariant 2). Caller-supplied; defaults to now.""", json_schema_extra = { "linkml_meta": {'domain_of': ['Event', 'FacetInstance', 'Entity', 'Edge']} })
    retracted_at: Optional[datetime ] = Field(default=None, description="""Transaction time at which this row stopped being believed - set by a retraction event NULL while the row is believed, which is what every read filters on. A transaction time, not a valid time: a retraction is a change of belief, not a change of what was true in the lab.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })
    retracted_by_event: Optional[str] = Field(default=None, description="""event_id of the retraction event that set retracted_at.""", json_schema_extra = { "linkml_meta": {'domain_of': ['FacetInstance', 'Entity', 'Edge']} })

    @field_validator('edge_id')
    def pattern_edge_id(cls, v):
        pattern=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-7[0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$")
        if isinstance(v, list):
            for element in v:
                if isinstance(element, str) and not pattern.match(element):
                    err_msg = f"Invalid edge_id format: {element}"
                    raise ValueError(err_msg)
        elif isinstance(v, str) and not pattern.match(v):
            err_msg = f"Invalid edge_id format: {v}"
            raise ValueError(err_msg)
        return v


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Facet.model_rebuild()
Event.model_rebuild()
FacetInstance.model_rebuild()
FacetSchema.model_rebuild()
Entity.model_rebuild()
Subject.model_rebuild()
Specimen.model_rebuild()
Extract.model_rebuild()
Library.model_rebuild()
Pool.model_rebuild()
SequencingRun.model_rebuild()
DataFile.model_rebuild()
AnalysisRun.model_rebuild()
DataFileSet.model_rebuild()
Protocol.model_rebuild()
Reagent.model_rebuild()
Actor.model_rebuild()
Project.model_rebuild()
Context.model_rebuild()
DataPoint.model_rebuild()
Edge.model_rebuild()
SameAsEdge.model_rebuild()
