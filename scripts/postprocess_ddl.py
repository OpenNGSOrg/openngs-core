"""Adjust the DDL LinkML generates, for the two things its generator cannot express.

Run by `make gen` for each dialect. Kept as a script rather than a chain of `sed` in the
Makefile so each change can carry its reason.

1. **Timestamps keep their offset.** The generator hardcodes SQLAlchemy's `DateTime()` for
   every `datetime` slot, which is `TIMESTAMP WITHOUT TIME ZONE` on Postgres - a column
   that silently drops the offset every writer in `src/` supplies, since all timestamps are
   normalized to UTC before writing. SQLite is unaffected: its `DATETIME` stores the ISO
   string as written.

2. **Entity names are unique while believed.** LinkML's `unique_keys` would emit a plain
   `UNIQUE (name)`, which is almost right but would also make a retracted name permanently
   unusable - and a retracted name is deliberately freed for reuse. A *partial*
   unique index says exactly what is meant, and both SQLite (3.8+) and Postgres support it.
"""

from __future__ import annotations

import sys

# The closed entity set, whose `name` is the human-facing identifier. Deliberately not
# FacetSchema: registering the same schema_name again is how a new version is created
# . Not Edge/SameAsEdge/FacetInstance either: they have no name.
ENTITY_TABLES = (
    "Subject",
    "Specimen",
    "Extract",
    "Library",
    "Pool",
    "SequencingRun",
    "DataFile",
    "AnalysisRun",
    "DataFileSet",
    "Protocol",
    "Reagent",
    "Actor",
    "Project",
    "Context",
    "DataPoint",
)


def postprocess(ddl: str, dialect: str) -> str:
    if dialect == "postgresql":
        ddl = ddl.replace("TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP WITH TIME ZONE")
    indexes = "\n".join(
        f'CREATE UNIQUE INDEX "uq_{table}_name" ON "{table}" (name) WHERE retracted_at IS NULL;'
        for table in ENTITY_TABLES
    )
    return (
        f"{ddl}\n"
        "-- One entity of a given type per name, while it is believed. A retracted name is\n"
        "-- free to reuse, which is why this is a partial index.\n"
        f"{indexes}\n"
    )


if __name__ == "__main__":
    sys.stdout.write(postprocess(sys.stdin.read(), sys.argv[1]))
