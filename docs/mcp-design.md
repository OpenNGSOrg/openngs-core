# The MCP server

Reference for the [Model Context Protocol](https://modelcontextprotocol.io/) server
(`src/openngs/mcp_server.py`, [FastMCP](https://gofastmcp.com/)), which lets an AI agent
(Claude Desktop, or any MCP client) read and write the lineage graph.

## What it is

A protocol adapter in front of the REST API, not a separate implementation. The server is
generated from the REST API's OpenAPI schema: one MCP tool per route, with the same
request and response shapes `docs/api-design.md` documents. A tool call runs against the
same FastAPI application in-process; no HTTP server needs to be running.

The one hand-written tool is `execute_graphql(query, variables)`, which runs a query
against the GraphQL schema `docs/graphql-design.md` describes and returns the standard
`{"data": ..., "errors": ...}` envelope. It exists because the `/graphql` route takes a
raw request body that cannot be described as a typed tool input, so it is excluded from
the automatic derivation and replaced by this.

## Tools

Ninety-seven tools in total:

| Group | Tools |
|---|---|
| Entities (14 × 5) | `create_<noun>`, `list_<plural>`, `show_<noun>`, `correct_<noun>`, `retract_<noun>`, e.g. `create_specimen`, `retract_sequencing_run` |
| Links | `link_derived_from`, `link_part_of`, `link_used`, `link_produced_by`, `link_characterizes`, `link_same_as`, `retract_link` |
| Facets | `attach_facet`, `list_facets`, `show_facet`, `correct_facet`, `retract_facet`, `register_facet_schema`, `list_facet_schemas`, `show_facet_schema` |
| DataPoints | `create_datapoint`, `list_datapoints`, `show_datapoint`, `correct_datapoint`, `retract_datapoint` |
| Events | `list_events`, `show_event`, `replay_events` |
| Batch | `batch`, `ingest_manifest` |
| Other | `health_check`, `execute_graphql` |

The noun in each name is the CLI's own (`sequencing_run`, `data_file_set`), so the tool
names match what a person already calls these things.

## Errors

A tool call that hits a 4xx or 5xx from the underlying route surfaces as a tool error
carrying the HTTP status and the API's `detail` message, for example
`HTTP error 409: Conflict - {'detail': "Subject with name ... already exists ..."}`. The
status-code conventions in `docs/api-design.md` apply unchanged.

## Running it

The same three environment variables as the CLI and the API:

```bash
export OPENNGS_ORG=acme-genomics
export OPENNGS_NAMESPACE=core-lab
export OPENNGS_DB_URL=sqlite:///openngs.db
make mcp
```

That serves over **stdio**, the way a local MCP client launches a server as a subprocess.
Point the client's configuration at:

```
uv run python -m openngs.mcp_server
```

run from this repository, with those three variables in its environment.

For **Streamable HTTP**, for a remote deployment or for testing with a plain HTTP client:

```bash
OPENNGS_MCP_TRANSPORT=http OPENNGS_MCP_HOST=127.0.0.1 OPENNGS_MCP_PORT=8001 make mcp
# serves at http://127.0.0.1:8001/mcp
```

`make compose-up` starts the MCP server over HTTP on port 8001 alongside Postgres and the
REST API, from the same container image. It depends only on Postgres, not on the API
container, since it holds its own in-process reference to the application.

The MCP server is a client of the REST API like any other, so once the API requires a
bearer token this has to present one: set `OPENNGS_MCP_TOKEN` to a token the API knows. Give
it a principal of its own rather than sharing a person's, so an event's `recorded_by` says
which door a write came through. On a deployment running with `OPENNGS_AUTH_MODE=none`
there is nothing to send.

An MCP client is trusted to the extent the MCP server is: this credential is the server's,
not the end user's, and OpenNGS cannot tell one agent's caller from another's. See
[docs/authentication.md](authentication.md).
