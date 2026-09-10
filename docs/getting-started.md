# Getting started

From a fresh clone to a running lineage graph you can query from the CLI, over REST, over
GraphQL, and from an AI agent. Every step is a `make` target; `Makefile` shows the raw
commands.

If you want to understand the model before touching it, read `docs/data-model.md` first.
If you want to see a realistic graph built end to end, `docs/worked-example.md` does that
in one script once you have finished step 5 here.

## Prerequisites

- **Python 3.14+**
- **[uv](https://docs.astral.sh/uv/)**, which installs the Python toolchain and manages
  the virtual environment:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- **Docker or Podman**, only if you want Postgres instead of the SQLite default.

## 1. Clone and install

```bash
git clone https://github.com/OpenNGSOrg/OpenNGS.git
cd OpenNGS
make install
```

`make install` runs `uv sync`: it creates `.venv/` and installs everything, including
OpenNGS itself in editable mode.

## 2. Create a database

### SQLite (default)

```bash
make db
```

Creates `openngs.db` in the repo root. **Destructive**: it always starts from a clean file.

### Postgres

```bash
make db-postgres                          # docker
make db-postgres CONTAINER_ENGINE=podman  # podman
```

Starts a `postgres:16` container named `openngs-postgres`, loads the schema, and prints
the connection URL:

```
postgresql://openngs:openngs@localhost:5432/openngs
```

Also destructive on every run. `make db-postgres-down` removes the container.

### Postgres, the API, and the MCP server together

```bash
make compose-up                           # or CONTAINER_ENGINE=podman
```

Builds one image and starts Postgres, the REST/GraphQL API, and the MCP server:

```
API:      http://localhost:8000   (Swagger UI at /docs, GraphiQL at /graphql)
MCP:      http://localhost:8001/mcp
Postgres: postgresql://openngs:openngs@localhost:5432/openngs
```

Unlike `make db-postgres`, this is **not** destructive: data lives in a named volume that
survives `make compose-down`, and the schema loads only the first time that volume is
created. To start truly fresh, drop the volume too (`docker compose down -v`).

## 3. Install the CLI

```bash
make cli-install
```

Puts `openngs` on your `PATH` from any shell, editable against this checkout. If it is
not found afterwards, run `uv tool update-shell` and open a new shell.

Prefer not to touch your `PATH`? Skip this step and prefix every command with `uv run`
from inside the repo.

## 4. Configure it

Every interface reads the same three settings: the org and namespace used to build and
resolve entity names, and the database to talk to.

```bash
export OPENNGS_ORG=acme-genomics
export OPENNGS_NAMESPACE=core-lab
export OPENNGS_DB_URL=sqlite:///openngs.db
# or, for Postgres:
# export OPENNGS_DB_URL=postgresql://openngs:openngs@localhost:5432/openngs
```

The CLI also accepts `--org`, `--ns`, and `--db-url` per command. Set `OPENNGS_PRINCIPAL`
if you want events to record something other than your operating-system user as having
made them.

The HTTP interfaces need one more decision before they will serve anything: either
configure tokens, or say explicitly that you are running without authentication.

```bash
export OPENNGS_AUTH_MODE=none            # a local database on your own machine
# or, for anything reachable by anyone else:
# export OPENNGS_AUTH_TOKENS='{"tok-dev":"you"}'
```

There is no default on purpose. `docs/authentication.md` covers tokens, roles, deployment
patterns, and what authentication does not cover - notably that the CLI talks to the
database directly and is unaffected by any of it.

## 5. Build your first graph

```bash
# A Subject, then a Specimen taken from it.
openngs subject create SUBJ-001
openngs specimen create SPEC-001 --subject SUBJ-001

openngs specimen list
openngs specimen show SPEC-001

# Continue the physical chain: Extract -> Library -> Pool.
openngs extract create EXT-001 --specimen SPEC-001
openngs library create LIB-001 --extract EXT-001
openngs pool create POOL-001
openngs link part-of --from LIB-001 --to POOL-001

# Record what the extraction used: the kit lot and the operator.
openngs reagent create REAGENT-KIT-LOTA1
openngs actor create ACTOR-OPERATOR-A
openngs link used --from EXT-001 --to REAGENT-KIT-LOTA1
openngs link used --from EXT-001 --to ACTOR-OPERATOR-A

openngs extract show EXT-001

# On to the digital side: a SequencingRun producing a DataFile.
openngs sequencing-run create RUN-001
openngs data-file create RUN-001-R1.fastq.gz --produced-by RUN-001
```

Every `create` validates its required parent before writing anything. Try
`openngs specimen create SPEC-002 --subject NOPE` to see the error. `--dry-run` on any
`create` validates and prints what would happen without writing.

`docs/cli-design.md` is the full command reference.

## 6. Attach a facet

A facet holds structured, schema-validated detail about an entity or an edge, in your own
namespace. This repo ships a worked example you can attach right away:

```bash
openngs facet attach \
  --to RUN-001-R1.fastq.gz \
  --schema-url docs/facets/examples/qc_metrics/qc_metrics.schema.json \
  --type QcMetricsFacet \
  --producer "fastqc/0.12.1" \
  --data '{"tool":"fastqc","metric_name":"openngs-dp:percent_duplication","metric_value":12.3}'

openngs facet list --to RUN-001-R1.fastq.gz
openngs facet show <facet_id>
```

`docs/facets/authoring-a-facet.md` shows how to write your own, including registering the
schema in the database so it is not tied to a file path.

## 7. Record a DataPoint

A single value worth querying across the whole graph gets a typed home of its own:

```bash
openngs datapoint create RUN-001-R1-percent-dup \
  --for RUN-001-R1.fastq.gz \
  --type openngs-dp:percent_duplication \
  --kind number \
  --value 12.3

openngs datapoint list --for RUN-001-R1.fastq.gz
```

`--kind` is `number`, `text`, or `boolean`. `docs/data-model.md` explains when to use a
facet and when to use a DataPoint.

## 8. Look at the event log

Every command above wrote an event first and updated the graph second:

```bash
openngs event list
openngs event show <event_id>
```

Record something that happened earlier than now, the everyday case of entering Monday's
work on Wednesday:

```bash
openngs extract create EXT-002 --specimen SPEC-001 --valid-time 2026-01-12T09:00:00
openngs event show <event_id> --output json
# valid_time is what you passed; transaction_time is now. Both are kept.
```

Because that date is on the record itself, you can filter by it. Both bounds are
inclusive:

```bash
openngs extract list --valid-from 2026-01-01 --valid-to 2026-01-31
openngs specimen list --subject SUBJ-001 --valid-from 2026-01-12
```

Rebuild the entire graph from the log. Nothing changes:

```bash
openngs event replay --yes
openngs specimen show SPEC-001
```

To follow the log the way an integration would, keep the last `event_id` you handled and
ask for what came after it:

```bash
openngs event list --after <event_id>
openngs event list --after <event_id> --type entity_created
```

Any `show` can include the events behind that one record:

```bash
openngs specimen show SPEC-001 --events
```

## 9. Correct something

Nothing is ever edited or deleted. A correction is a new event that supersedes the last one
about that record, with a reason you have to give:

```bash
# Wrong local ID on a specimen.
openngs specimen correct SPEC-001 --local-id SPEC-002 --reason "mislabelled tube"

# A relationship that turned out to be wrong. `link` printed an edge_id when you made it
# in step 5; `show --events` finds it again if you did not keep it.
openngs library show LIB-001 --events
openngs link retract <edge_id> --reason "wrong pool"

# A record that should never have existed. Its edges have to go too, explicitly.
openngs subject retract SUBJ-001 --reason "duplicate registration" --cascade
```

A retracted record stops appearing in reads but is still there:

```bash
openngs subject show SUBJ-001                       # error: not found
openngs subject show SUBJ-001 --include-retracted   # marked [RETRACTED], with the event
openngs subject show SUBJ-001 --include-retracted --events
```

Replay still reproduces exactly this state, corrections and all.

## 10. Use the REST API

The full CLI surface over HTTP, against the same database. Skip `make api` if you used
`make compose-up`.

```bash
make api
```

In another shell (add `-H "Authorization: Bearer <token>"` if you configured tokens rather
than `OPENNGS_AUTH_MODE=none`):

```bash
curl -s -X POST localhost:8000/subjects -H 'Content-Type: application/json' \
  -d '{"local_id":"SUBJ-002"}'
curl -s localhost:8000/subjects/SUBJ-002

curl -s -X POST localhost:8000/specimens -H 'Content-Type: application/json' \
  -d '{"local_id":"SPEC-003","subject":"SUBJ-002"}'
curl -s -X POST localhost:8000/links/used -H 'Content-Type: application/json' \
  -d '{"from":"SPEC-003","to":"REAGENT-KIT-LOTA1"}'

curl -s -X POST localhost:8000/datapoints -H 'Content-Type: application/json' \
  -d '{"local_id":"SPEC-003-flag","for":"SPEC-003","type":"acme:flagged","kind":"boolean","value":"true"}'
curl -s "localhost:8000/events?limit=3"
```

Swagger UI, with every route runnable interactively, is at `http://localhost:8000/docs`.
`docs/api-design.md` is the reference.

## 11. Query with GraphQL

Mounted in the same server at `/graphql`; GraphiQL is at that URL in a browser.

```bash
curl -s -X POST localhost:8000/graphql -H 'Content-Type: application/json' -d '{
  "query": "{ specimen(ref: \"SPEC-003\") { internalId name outgoing { predicate other { internalId name ... on Reagent { xrefs } } } } }"
}'
```

One query walks from the specimen to everything it is linked to and pulls type-specific
fields only where an inline fragment asks for them. `docs/graphql-design.md` is the
reference; `docs/worked-example.md` has deeper traversals.

## 12. Connect an AI agent (MCP)

The MCP server exposes one tool per REST route plus `execute_graphql`, so an MCP client
(Claude Desktop, or any agent framework) gets the same surface an HTTP client does. It
talks to the same database in-process; `make api` does not need to be running.

```bash
make mcp                                          # stdio, for a local client
OPENNGS_MCP_TRANSPORT=http OPENNGS_MCP_PORT=8001 make mcp   # over HTTP
```

For a local client, point its configuration at `uv run python -m openngs.mcp_server` in
this repo with the same three environment variables. `docs/mcp-design.md` has the
details.

## Next

- `docs/worked-example.md`: a clinical trio built end to end, with real queries.
- `docs/data-model.md`: what every entity and edge is for.
- `docs/contributing.md`: if you want to change OpenNGS itself.
