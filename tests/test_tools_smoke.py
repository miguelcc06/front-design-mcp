"""Smoke tests for MCP tool surface via FastMCP in-process Client."""

from __future__ import annotations

import pytest
from fastmcp import Client

from front_design_mcp.server import mcp
from front_design_mcp.tools.runtime import reset_runtime


@pytest.fixture(autouse=True)
def _ready_runtime(tmp_path, monkeypatch):
    """Point tools at a fresh temp DB and auto-ingest fixtures."""
    reset_runtime()
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(tmp_path / "store" / "test.db"))
    # Clear settings cache if any — Settings() reads env each call
    yield
    reset_runtime()


@pytest.mark.asyncio
async def test_list_tools_and_core_calls() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        required = {
            "front_design_ping",
            "discover_frontend_resources",
            "search_frontend_knowledge",
            "get_resource_details",
            "compare_frontend_options",
            "recommend_frontend_stack",
            "find_components",
            "find_animation_patterns",
            "build_frontend_brief",
        }
        assert required.issubset(set(names))

        ping = await client.call_tool("front_design_ping", {})
        assert ping.data is not None
        assert ping.data.get("status") == "ok"

        discover = await client.call_tool(
            "discover_frontend_resources",
            {"limit": 5},
        )
        assert discover.data is not None
        assert discover.data.get("total_count", 0) >= 1

        search = await client.call_tool(
            "search_frontend_knowledge",
            {"query": "accordion", "limit": 3},
        )
        assert search.data is not None
        hits = search.data.get("hits") or []
        assert len(hits) >= 1

        pricing = await client.call_tool(
            "find_components",
            {"intent": "pricing", "limit": 3},
        )
        assert pricing.data is not None
        items = pricing.data.get("items") or []
        assert len(items) >= 1
