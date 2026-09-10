.PHONY: install gen check db db-postgres db-postgres-down cli-install api mcp compose-up compose-down

DB_FILE          ?= openngs.db
CONTAINER_ENGINE ?= docker
PG_CONTAINER     ?= openngs-postgres
PG_USER          ?= openngs
PG_PASSWORD      ?= openngs
PG_DB            ?= openngs
PG_PORT          ?= 5432

install:
	uv sync

# Both DDL files go through scripts/postprocess_ddl.py for the two things LinkML's
# generator cannot express: timestamps that keep their UTC offset on Postgres, and a
# partial unique index on each entity's name. That script carries the reasons.
gen:
	{ echo "# GENERATED from schema/openngs.yaml by \`make gen\` — never hand-edit."; \
	  uv run linkml generate pydantic schema/openngs.yaml; } > src/openngs/model/generated.py
	{ echo "-- GENERATED from schema/openngs.yaml by \`make gen\` — never hand-edit."; \
	  uv run linkml generate sqltables --dialect sqlite schema/openngs.yaml \
	    | uv run python scripts/postprocess_ddl.py sqlite; } > generated/schema.sql
	{ echo "-- GENERATED from schema/openngs.yaml by \`make gen\` — never hand-edit."; \
	  uv run linkml generate sqltables --dialect postgresql schema/openngs.yaml \
	    | uv run python scripts/postprocess_ddl.py postgresql; } > generated/schema.postgres.sql

check:
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy src
	uv run pytest

# SQLite, the default. Destructive: always starts from a clean file, same as
# yesterday's `sqlite3 openngs.db < generated/schema.sql` but without depending on the
# sqlite3 CLI binary (stdlib sqlite3 module only, so this works anywhere Python does).
db:
	rm -f $(DB_FILE)
	uv run python3 -c "\
import pathlib, sqlite3; \
conn = sqlite3.connect('$(DB_FILE)'); \
conn.executescript(pathlib.Path('generated/schema.sql').read_text()); \
conn.commit(); \
conn.close()"
	@echo "SQLite database ready: sqlite:///$(DB_FILE)"

# Postgres, as an alternative to SQLite. Requires docker or podman (they're
# CLI-compatible; override with `make db-postgres CONTAINER_ENGINE=podman` if you don't
# have docker). Destructive, like `db` above: drops and recreates the container fresh
# every run.
db-postgres:
	@$(CONTAINER_ENGINE) rm -f $(PG_CONTAINER) >/dev/null 2>&1 || true
	$(CONTAINER_ENGINE) run -d --name $(PG_CONTAINER) \
		-e POSTGRES_USER=$(PG_USER) \
		-e POSTGRES_PASSWORD=$(PG_PASSWORD) \
		-e POSTGRES_DB=$(PG_DB) \
		-p $(PG_PORT):5432 \
		docker.io/library/postgres:16 >/dev/null
	@echo "waiting for postgres to accept connections..."
	@until $(CONTAINER_ENGINE) exec $(PG_CONTAINER) pg_isready -U $(PG_USER) >/dev/null 2>&1; do sleep 1; done
	$(CONTAINER_ENGINE) cp generated/schema.postgres.sql $(PG_CONTAINER):/tmp/schema.sql
	$(CONTAINER_ENGINE) exec -e PGPASSWORD=$(PG_PASSWORD) $(PG_CONTAINER) \
		psql -U $(PG_USER) -d $(PG_DB) -v ON_ERROR_STOP=1 -f /tmp/schema.sql
	@echo "Postgres database ready: postgresql://$(PG_USER):$(PG_PASSWORD)@localhost:$(PG_PORT)/$(PG_DB)"

db-postgres-down:
	$(CONTAINER_ENGINE) rm -f $(PG_CONTAINER)

# Installs the CLI as a uv-managed tool (its own isolated venv, editable against this
# checkout, shimmed onto PATH) so `openngs` works from any shell without `uv run`.
cli-install:
	uv tool install --editable .
	@echo "installed - if 'openngs' isn't found, run: uv tool update-shell"

# REST API dev server (docs/api-design.md). Needs OPENNGS_ORG/OPENNGS_NAMESPACE/
# OPENNGS_DB_URL set the same way the CLI does. --reload picks up code changes.
api:
	uv run uvicorn openngs.api:app --reload

# MCP server wrapping the API (docs/mcp-design.md) - same env vars as `api` above. stdio by
# default (how an MCP client normally launches this); OPENNGS_MCP_TRANSPORT=http instead.
mcp:
	uv run python -m openngs.mcp_server

# The full stack (Postgres + the API, built from the Dockerfile) via docker-compose.yml -
# an alternative to db-postgres+api for running both together in containers. Unlike
# db-postgres, NOT destructive on every run: Postgres data lives in a named volume that
# survives `compose-down` (only `podman compose down -v` drops it), and the schema loads
# once, the first time that volume is created (generated/schema.postgres.sql, mounted as a
# Postgres docker-entrypoint-initdb.d script). CONTAINER_ENGINE=podman if you don't have
# docker; needs `podman compose` (or a podman-compose install) as well as podman itself.
compose-up:
	$(CONTAINER_ENGINE) compose up -d --build
	@echo "API: http://localhost:8000/docs   Postgres: postgresql://openngs:openngs@localhost:5432/openngs"

compose-down:
	$(CONTAINER_ENGINE) compose down
