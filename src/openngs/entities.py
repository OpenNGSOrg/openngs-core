"""The registry of the 14 `EntityConfig`-shaped entity types - everything in the closed
entity set except `DataPoint`, which needs extra required fields (`--type`/`--kind`/`--value`
in the CLI) that don't fit this generic create/list/show shape. Shared between `cli.py` and
`api.py` (docs/api-design.md) so both clients build entities the same way instead of
drifting: same parent-edge rules, same plural/URL-safe names, same model classes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openngs.model import (
    Actor,
    AnalysisRun,
    Context,
    DataFile,
    DataFileSet,
    Extract,
    Library,
    Pool,
    Project,
    Protocol,
    Reagent,
    SequencingRun,
    Specimen,
    Subject,
)
from openngs.store.repo import ENTITY_TYPES


@dataclass(frozen=True)
class ParentSpec:
    flag: str
    predicate: str
    target_types: tuple[str, ...]


def parent_field_name(parent: ParentSpec) -> str:
    """ "--subject" -> "subject", "--produced-by" -> "produced_by" - the body field/query
    param/GraphQL argument name for this entity's one parent edge in api.py and
    graphql_schema.py, readable in OpenAPI/GraphQL docs instead of a generic "parent_ref"
    on every entity."""
    return parent.flag.lstrip("-").replace("-", "_")


@dataclass(frozen=True)
class EntityConfig:
    type_name: str
    cli_name: str
    model: type[Any]
    plural: str
    parent: ParentSpec | None = None
    extra_derived_from: bool = False  # DataFile only


ENTITIES: list[EntityConfig] = [
    EntityConfig("Subject", "subject", Subject, "subjects"),
    EntityConfig(
        "Specimen",
        "specimen",
        Specimen,
        "specimens",
        ParentSpec("--subject", "derived_from", ("Subject",)),
    ),
    EntityConfig(
        "Extract",
        "extract",
        Extract,
        "extracts",
        ParentSpec("--specimen", "derived_from", ("Specimen",)),
    ),
    EntityConfig(
        "Library",
        "library",
        Library,
        "libraries",
        ParentSpec("--extract", "derived_from", ("Extract",)),
    ),
    EntityConfig("Pool", "pool", Pool, "pools"),
    EntityConfig("SequencingRun", "sequencing-run", SequencingRun, "sequencing-runs"),
    EntityConfig(
        "DataFile",
        "data-file",
        DataFile,
        "data-files",
        ParentSpec("--produced-by", "produced_by", ("SequencingRun", "AnalysisRun")),
        extra_derived_from=True,
    ),
    EntityConfig("AnalysisRun", "analysis-run", AnalysisRun, "analysis-runs"),
    EntityConfig(
        "DataFileSet",
        "data-file-set",
        DataFileSet,
        "data-file-sets",
        # SequencingRun as well as AnalysisRun - a raw BCL run folder
        # (many per-cycle files produced together by one SequencingRun, pre-demultiplexing)
        # is exactly the "produced together as a group" shape DataFileSet exists for.
        # DataFile's own ParentSpec, three entries down, already allowed both; DataFileSet
        # was only narrower because the original design had analysis-output grouping in mind.
        ParentSpec("--produced-by", "produced_by", ("SequencingRun", "AnalysisRun")),
    ),
    EntityConfig("Protocol", "protocol", Protocol, "protocols"),
    EntityConfig("Reagent", "reagent", Reagent, "reagents"),
    EntityConfig("Actor", "actor", Actor, "actors"),
    EntityConfig("Project", "project", Project, "projects"),
    EntityConfig("Context", "context", Context, "contexts"),
]

ENTITIES_BY_PLURAL: dict[str, EntityConfig] = {cfg.plural: cfg for cfg in ENTITIES}
# A batch operation names its entity by the noun a human uses ("sequencing-run") or by the
# class name ("SequencingRun"); accept either rather than making callers know which.
ENTITIES_BY_CLI_NAME: dict[str, EntityConfig] = {cfg.cli_name: cfg for cfg in ENTITIES}
ENTITIES_BY_TYPE: dict[str, EntityConfig] = {cfg.type_name: cfg for cfg in ENTITIES}

# The `--from`/`from` and `--to`/`to` type constraints per edge predicate, used by both
# `link <predicate>` and `POST /links/<predicate>` - the type checking `link` exists to do
# that the schema itself won't (docs/cli-design.md). `same_as` isn't in either: it's
# handled as its own case (extra asserted_by/method/confidence fields) by both clients.
#
# Sources are unconstrained except for `characterizes`, which the schema defines as
# DataPoint -> Entity: a DataPoint is the only thing that characterizes. Every
# other predicate has too many legitimate subjects to enumerate (a `used` edge's subject
# is whatever consumed the reagent - an Extract, a Library, an AnalysisRun...).
LINK_SOURCE_TYPES: dict[str, tuple[str, ...]] = {
    "derived_from": ENTITY_TYPES,
    "part_of": ENTITY_TYPES,
    "used": ENTITY_TYPES,
    "produced_by": ENTITY_TYPES,
    "characterizes": ("DataPoint",),
}

LINK_TARGET_TYPES: dict[str, tuple[str, ...]] = {
    "derived_from": ENTITY_TYPES,
    "part_of": ENTITY_TYPES,
    # DataFile/DataFileSet as well as Protocol/Reagent/Actor - lets an
    # AnalysisRun directly assert the exact input dataset it consumed (e.g. which FASTQ
    # output a secondary pipeline ran against), rather than only being reconstructable by
    # walking derived_from backward from whatever its own outputs happen to declare.
    #
    # Pool/Library extend that same argument to the instrument: a SequencingRun
    # consumes material the way an AnalysisRun consumes data, and could previously only be
    # tied to what it sequenced through its own output's derived_from edge. Library as well
    # as Pool because a single-sample run loads a library directly, with no pooling step.
    "used": ("Protocol", "Reagent", "Actor", "DataFile", "DataFileSet", "Pool", "Library"),
    "produced_by": ("SequencingRun", "AnalysisRun"),
    "characterizes": ENTITY_TYPES,
}
