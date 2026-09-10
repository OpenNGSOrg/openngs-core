"""End-to-end tests for the FastMCP server (docs/mcp-design.md) - every tool is auto-derived
from api.py's OpenAPI schema, so this is mostly a test that the derivation itself produces
the right tools with the right names, and that a couple of representative calls (a create, a
link, a show, an error case) come back correctly through the MCP protocol layer."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from openngs.mcp_server import mcp


@pytest.fixture
def anyio_backend() -> str:
    """asyncio only - trio isn't a project dependency, so don't let anyio's pytest plugin
    try to parametrize these tests over it too."""
    return "asyncio"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENNGS_ORG", "acme-genomics")
    monkeypatch.setenv("OPENNGS_NAMESPACE", "core-lab")
    monkeypatch.setenv("OPENNGS_DB_URL", f"sqlite:///{db_path}")


@pytest.mark.anyio
async def test_lists_one_tool_per_route(env: None) -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
    names = {t.name for t in tools}
    # One per entity noun (create/list/show), plus link/facet/facet-schema/datapoint/event -
    # the full REST surface, not a subset.
    assert "create_subject" in names
    assert "list_specimens" in names
    assert "show_data_file" in names
    assert "link_used" in names
    assert "link_same_as" in names
    assert "attach_facet" in names
    assert "register_facet_schema" in names
    assert "create_datapoint" in names
    assert "replay_events" in names
    assert "health_check" in names
    # /graphql's auto-derived tools are excluded (empty input schema - Strawberry's route
    # takes a raw Request, not a typed body - always 400s, see mcp_server.py's docstring);
    # execute_graphql, the one hand-written tool, takes their place.
    assert "handle_http_get_graphql_get" not in names
    assert "handle_http_post_graphql_post" not in names
    assert "execute_graphql" in names
    assert len(names) == len(tools)  # no accidental name collisions


@pytest.mark.anyio
async def test_create_and_show_round_trip(env: None) -> None:
    async with Client(mcp) as client:
        created = await client.call_tool("create_subject", {"local_id": "SUBJ-001"})
        assert created.data["type"] == "Subject"
        internal_id = created.data["internal_id"]

        shown = await client.call_tool("show_subject", {"ref": "SUBJ-001"})
        assert shown.data["internal_id"] == internal_id
        assert shown.data["name"] == "openngs://acme-genomics/core-lab/subject/SUBJ-001"


@pytest.mark.anyio
async def test_full_lineage_across_tool_calls(env: None) -> None:
    async with Client(mcp) as client:
        subject = await client.call_tool("create_subject", {"local_id": "SUBJ-001"})
        await client.call_tool("create_specimen", {"local_id": "SPEC-001", "subject": "SUBJ-001"})
        await client.call_tool("create_actor", {"local_id": "ACTOR-1"})
        link = await client.call_tool("link_used", {"from": "SPEC-001", "to": "ACTOR-1"})
        assert link.data["predicate"] == "used"

        shown = await client.call_tool("show_specimen", {"ref": "SPEC-001"})
        predicates = {e["predicate"] for e in shown.data["outgoing"]}
        assert predicates == {"derived_from", "used"}

        events = await client.call_tool("show_subject", {"ref": "SUBJ-001", "events": True})
        assert events.data["events"][0]["type"] == "entity_created"
        assert events.data["events"][0]["source"] == "openngs-api"
        _ = subject  # created, only used for lineage setup above


@pytest.mark.anyio
async def test_error_response_raises_tool_error(env: None) -> None:
    async with Client(mcp) as client:
        await client.call_tool("create_subject", {"local_id": "SUBJ-001"})
        with pytest.raises(ToolError, match="409"):
            await client.call_tool("create_subject", {"local_id": "SUBJ-001"})


@pytest.mark.anyio
async def test_error_response_without_raising(env: None) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("show_subject", {"ref": "NOPE"}, raise_on_error=False)
    assert result.is_error


@pytest.mark.anyio
async def test_execute_graphql_runs_a_traversal_query(env: None) -> None:
    async with Client(mcp) as client:
        await client.call_tool("create_subject", {"local_id": "SUBJ-001"})
        await client.call_tool("create_specimen", {"local_id": "SPEC-001", "subject": "SUBJ-001"})

        result = await client.call_tool(
            "execute_graphql",
            {
                "query": '{ specimen(ref: "SPEC-001") { internalId '
                "outgoing { predicate other { name } } } }"
            },
        )
        assert result.data["errors"] is None
        specimen = result.data["data"]["specimen"]
        assert specimen["outgoing"][0]["predicate"] == "derived_from"
        assert specimen["outgoing"][0]["other"]["name"].endswith("SUBJ-001")


@pytest.mark.anyio
async def test_execute_graphql_returns_errors_without_raising(env: None) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("execute_graphql", {"query": "{ nope }"})
    assert result.data["data"] is None
    assert "nope" in result.data["errors"][0]["message"]


@pytest.mark.anyio
async def test_replay_requires_confirmation(env: None) -> None:
    async with Client(mcp) as client:
        await client.call_tool("create_subject", {"local_id": "SUBJ-001"})
        with pytest.raises(ToolError, match="400"):
            await client.call_tool("replay_events", {})

        before = await client.call_tool("show_subject", {"ref": "SUBJ-001"})
        replayed = await client.call_tool("replay_events", {"yes": True})
        assert replayed.data["replayed"] >= 1
        after = await client.call_tool("show_subject", {"ref": "SUBJ-001"})
        assert after.data == before.data
