# Runs the REST API (src/openngs/api.py, docs/api-design.md) by default, and the
# MCP server (src/openngs/mcp_server.py - docs/mcp-design.md) too, same image, CMD
# overridden in docker-compose.yml's `mcp` service - both are the same source, and fastmcp
# is a real (non-dev) dependency, so it's already installed here either way. Not used by the
# CLI or the test suite.
# 3.14, matching pyproject.toml's requires-python - new_id() calls stdlib
# uuid.uuid7(), which doesn't exist before 3.14.
FROM python:3.14-slim

# uv, the project's own dependency and environment manager - copied from
# Astral's official distroless image rather than pip-installed, per their documented
# Docker pattern.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Dependencies first, isolated from source changes, so editing src/ doesn't invalidate this
# layer. --no-install-project defers installing openngs itself to the second `uv sync`,
# once the source (and its version, read from pyproject.toml at build time) is present.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-dev

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 8000
EXPOSE 8001
# --no-sync: the venv built above already matches uv.lock --no-dev exactly: don't have
# `uv run` re-resolve/re-sync (and pull dev-only deps like mypy/ruff/pytest) on every
# container start. Default CMD is the REST API; docker-compose.yml's `mcp` service
# overrides this to run the MCP server instead.
CMD ["uv", "run", "--no-sync", "uvicorn", "openngs.api:app", "--host", "0.0.0.0", "--port", "8000"]
