# Contributing

How to work on OpenNGS itself: the mechanics, the layout, and the conventions a change is
expected to follow. [docs/architecture.md](architecture.md) explains what OpenNGS is and
why it is shaped this way; read that first if you are new to the project.

## Setup

```bash
make install       # uv sync: creates .venv and installs OpenNGS in editable mode
make db            # a fresh SQLite database at ./openngs.db
make check         # ruff check, ruff format --check, mypy --strict, pytest
```

`make check` must pass before any commit.

## Make targets

| Target | Does |
|---|---|
| `make install` | `uv sync` |
| `make gen` | Regenerate everything from `schema/openngs.yaml` |
| `make check` | Lint, format check, type check, tests |
| `make db` | Fresh SQLite database (destructive) |
| `make db-postgres` | Fresh Postgres in a container (destructive); `CONTAINER_ENGINE=podman` if needed |
| `make db-postgres-down` | Remove that container |
| `make cli-install` | `uv tool install --editable .`, putting `openngs` on `PATH` |
| `make api` | REST/GraphQL dev server with reload |
| `make mcp` | MCP server, stdio by default |
| `make compose-up` / `compose-down` | Postgres, API, and MCP together in containers |

## The schema is the source of truth

`schema/openngs.yaml` (with its imports under `schema/facets/` and `schema/events.yaml`)
is the standard. `make gen` regenerates from it:

- `src/openngs/model/generated.py`: Pydantic models
- `generated/schema.sql`: SQLite DDL
- `generated/schema.postgres.sql`: Postgres DDL, with `TIMESTAMP WITH TIME ZONE`
  substituted for the generator's default, since every writer supplies UTC-aware
  timestamps and the default column would drop the offset

Never hand-edit a generated file. `make gen` is idempotent; run it and commit the result
alongside any schema change, in its own commit.

GraphQL is the one interface not generated from the schema. `src/openngs/graphql_schema.py`
is hand-authored against the store layer, the same relationship `api.py` has to it:
LinkML's GraphQL generator cannot express this schema, and a generated SDL would not carry
the traversal resolvers that are the substance of the interface anyway.

## Layout

```
schema/                      LinkML source
generated/                   Generated DDL
src/openngs/
  model/generated.py         Generated Pydantic models
  store/db.py                Database wrapper (sqlite3 or pg8000), portable placeholders
  store/repo.py              Reference resolution, entity and edge reads/writes
  store/events.py            The event log: emit, record_*, apply_event, replay
  store/facets.py            Facet instances, validation, the schema store
  store/datapoints.py        DataPoint storage
  entities.py                The EntityConfig registry every interface builds from
  context.py                 Settings and DB-connection dependencies for the HTTP interfaces
  cli.py                     Typer CLI
  api.py                     FastAPI REST API; mounts GraphQL at /graphql
  graphql_schema.py          Strawberry GraphQL schema
  mcp_server.py              FastMCP server derived from api.py's OpenAPI schema
tests/                       pytest; SQLite in a temp dir per test
docs/                        Documentation
```

## How a write flows

Every interface (CLI, REST, MCP through REST) calls a `record_*` function in
`store/events.py`. That function emits a CloudEvents-shaped row into the `Event` table,
then applies the same payload to the graph projection through the `insert_*` functions in
`store/repo.py`, `store/facets.py`, or `store/datapoints.py`, all in one transaction.
`replay` truncates the projection and re-applies every event in order through the same
`insert_*` functions, without re-validating anything: the log is the source of truth.

The `EntityConfig` registry in `entities.py` is what keeps the three interfaces from
drifting: which entity has which required parent, which entity types each `link`
predicate accepts on either side, the plural and URL-safe names. Add an entity-level
rule there, never in one client.

## Testing

```bash
uv run pytest                      # everything
uv run pytest tests/test_cli_events.py -k replay
```

Tests build a fresh SQLite database from `generated/schema.sql` in a temp directory. The
REST tests use FastAPI's `TestClient`; the MCP tests use `fastmcp.Client` in-memory. Both
run in-process with no server.

The suite runs against SQLite only. Postgres-specific behaviour (timestamp columns, enum
column types, connection handling) has to be checked by hand against `make db-postgres`.

## Branching

OpenNGS follows [git-flow](https://nvie.com/posts/a-successful-git-branching-model/).

| Branch | Holds |
|---|---|
| `main` | Released versions only. Every commit is a release, tagged. |
| `develop` | The integration branch. Work lands here first. |
| `feature/<name>` | One change, branched from `develop`, merged back into it |
| `release/<version>` | Stabilising a release: branched from `develop`, merged to both |
| `hotfix/<version>` | An urgent fix to a release: branched from `main`, merged to both |

**Branch from `develop`, not `main`**, and open pull requests against `develop`:

```bash
git switch develop
git switch -c feature/broker-sink
# ... work, with `make check` passing ...
git push -u origin feature/broker-sink
```

`main` currently sits at the initial commit because there has been no release yet
(OpenNGS is alpha — see the README). It will move only when one is cut.

If you have `git-flow` installed, `git flow init` with the defaults matches this layout.

## Conventions

- **Commits**: conventional commits, scoped by component (`feat(store): ...`,
  `fix(cli): ...`, `docs: ...`). Schema changes in their own commit with their regenerated
  artifacts.
- **`make check` passes before every commit**, and `make gen` is idempotent — if
  regenerating produces a diff, commit it with the schema change that caused it.
- **Design decisions**: anything expensive to reverse should be argued in the pull
  request, including the alternatives considered and why they lost. Record the outcome in
  the docs the decision affects, not only in the commit message.
- **SQL**: portable between SQLite and Postgres. Use `db.ph(n)` for placeholders.
- **Dependencies**: Apache-2.0, MIT, or BSD compatible only. Check before adding.
- **Fixtures**: real-world inputs for adapters, never hand-written stand-ins. No secrets,
  no PHI; synthetic subject data only.

## Implementation notes worth knowing

Each of these is load-bearing and non-obvious.

- **`api.py` and `graphql_schema.py` do not use `from __future__ import annotations`.**
  FastAPI and Strawberry both inspect real parameter and return annotations at import
  time to build request models and resolvers. Under postponed evaluation those are
  strings, and the dynamically built models and loop-local `node_cls` those two files use
  are not resolvable from a string. Every other module keeps the deferred import.
- **GraphQL resolvers each open their own database connection.** A REST handler runs as
  one call on one thread, so one connection per request is safe. Strawberry dispatches
  each sync resolver to a thread pool, and SQLite connections are thread-affine, so the
  GraphQL context carries only `(db_url, org, ns)` and each resolver connects for itself.
  Against SQLite this is free. Against Postgres it is a TCP connection per resolved field;
  a connection pool is the mitigation if that ever shows up as a bottleneck.
- **Per-entity and per-predicate routes are registered through factory functions**
  (`_register_entity_routes(cfg)`, `_register_link_route(predicate, slug)`), not inline
  in a loop, so each route's closure captures its own values rather than the loop's last
  iteration.
- **Every `api.py` route sets an explicit `operation_id`.** FastMCP uses it as the tool
  name; FastAPI's default would leak factory-function names.
- **Two differently named functions, not one name redefined in an `if`/`else`**, wherever
  a route or resolver has two signature shapes (with and without a parent filter). Mypy
  treats same-named conditional definitions as overloads requiring identical signatures.
- **`strawberry.field(description=...)` needs `# type: ignore[untyped-decorator]`** under
  `mypy --strict`; the bare decorator does not. The descriptions are kept because they
  show in GraphiQL.
- **`strawberry.scalars.JSON` is a `NewType`.** Return values must be wrapped in
  `JSON(...)` to satisfy mypy even though it is a runtime no-op.
- **Async tests use `anyio`'s pytest plugin**, already installed transitively through
  Starlette, with `anyio_backend` pinned to `asyncio`. No `pytest-asyncio`.
- **Event timestamps are normalized to ISO strings in `store/events.py`**, because
  SQLite returns the string that was written and pg8000 returns `datetime` objects.
  Clients never see a `datetime`.
