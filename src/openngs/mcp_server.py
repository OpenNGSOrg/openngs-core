"""FastMCP server wrapping the REST API - see docs/mcp-design.md. Every MCP tool but one is
auto-derived from api.py's OpenAPI schema (`FastMCP.from_fastapi`), one per route
(`create_subject`, `link_used`, `attach_facet`, `replay_events`, ...) - not a fourth
hand-written client of the store layer, just a protocol adapter in front of the third one
(the REST API). Tool calls run against `api.app` via an in-process ASGI transport, no real
HTTP hop and no separate `make api` server needed to run this.

Needs the same `OPENNGS_ORG`/`OPENNGS_NAMESPACE`/`OPENNGS_DB_URL` env vars api.py already
reads - there is no MCP-specific configuration.

**The one hand-written exception: `execute_graphql`.** `/graphql` is a normal
FastAPI route, so `from_fastapi` finds it and would generate `handle_http_post_graphql_get`/
`_post` tools same as any other - except Strawberry's `GraphQLRouter` takes a raw Starlette
`Request`, not a typed Pydantic model, so it has no request-body schema in the OpenAPI
document at all. The auto-derived tools end up with an *empty* input schema - no way for a
client to supply `query`/`variables` - and calling one 400s ("Unsupported content type"),
confirmed by hand before writing this. `/graphql` is excluded from the auto-derivation
below (`route_maps`) and `execute_graphql` takes its place: not a new client of the store
layer, or even of a new execution path - it calls the exact same `graphql_schema.schema`
the REST route already runs requests through, just reached directly instead of via an HTTP
request FastMCP can't construct. See docs/mcp-design.md and docs/graphql-design.md.
"""

from __future__ import annotations

import os
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap

from openngs.api import app as fastapi_app
from openngs.auth import authenticate
from openngs.context import get_settings, get_validated_settings
from openngs.graphql_schema import get_graphql_context, schema


def _auth_headers() -> dict[str, str]:
    """The credential this server presents to the API it wraps.

    The MCP server is a client of the REST API like any other, so once the API requires a
    bearer token this has to carry one: set OPENNGS_MCP_TOKEN to a token the API knows.
    Give it a principal of its own rather than sharing a human's, so `recorded_by` says
    which door a write came through. On a deployment running with authentication disabled
    there is nothing to send.
    """
    token = os.environ.get("OPENNGS_MCP_TOKEN")
    return {"Authorization": f"Bearer {token}"} if token else {}


mcp: FastMCP = FastMCP.from_fastapi(
    app=fastapi_app,
    name="OpenNGS",
    route_maps=[RouteMap(pattern=r"^/graphql$", mcp_type=MCPType.EXCLUDE)],
    httpx_client_kwargs={"headers": _auth_headers()},
)


@mcp.tool
async def execute_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run a GraphQL query against the same schema /graphql serves (docs/graphql-design.md)
    - traversal-shaped questions (walk derived_from/part_of/etc. from an arbitrary starting
    entity) in one round trip, the thing none of the other tools here can do individually.
    Returns the standard GraphQL response shape: {"data": ..., "errors": [...] | None}."""
    # This tool reaches the schema directly rather than over HTTP, so it authenticates
    # here with the same token the generated tools send in a header.
    principal = authenticate("GET", _auth_headers().get("Authorization"))
    context = get_graphql_context(get_validated_settings(get_settings()), principal)
    result = await schema.execute(query, variable_values=variables, context_value=context)
    return {
        "data": result.data,
        "errors": [e.formatted for e in result.errors] if result.errors else None,
    }


def main() -> None:
    """stdio by default - how MCP clients (Claude Desktop, etc.) normally launch a local
    server, spawning this as a subprocess and talking to it over stdin/stdout. Set
    OPENNGS_MCP_TRANSPORT=http (plus OPENNGS_MCP_HOST/OPENNGS_MCP_PORT) to instead serve
    over Streamable HTTP - useful for a remote deployment, or for `curl`-ing/testing it
    directly."""
    transport = os.environ.get("OPENNGS_MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(
            transport="http",
            host=os.environ.get("OPENNGS_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("OPENNGS_MCP_PORT", "8001")),
        )


if __name__ == "__main__":
    main()
