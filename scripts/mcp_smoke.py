#!/usr/bin/env python3
"""Offline FastMCP Client smoke checks for front-design-mcp."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path


async def main() -> int:
    td = tempfile.mkdtemp(prefix="front-design-smoke-")
    os.environ["FRONT_DESIGN_DATA_DIR"] = td
    os.environ["FRONT_DESIGN_DB_PATH"] = str(Path(td) / "store" / "smoke.db")
    os.environ.setdefault("FRONT_DESIGN_ENABLE_NETWORK_INGEST", "false")

    from fastmcp import Client

    from front_design_mcp.server import mcp
    from front_design_mcp.tools.runtime import reset_runtime

    reset_runtime()
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        print("TOOLS", names)
        required = {
            "front_design_ping",
            "front_design_health",
            "discover_frontend_resources",
            "search_frontend_knowledge",
            "get_resource_details",
            "compare_frontend_options",
            "recommend_frontend_stack",
            "find_components",
            "find_animation_patterns",
            "build_frontend_brief",
        }
        missing = required - set(names)
        if missing:
            print("FAIL missing tools", sorted(missing))
            return 1

        ping = await client.call_tool("front_design_ping", {})
        assert ping.data is not None and ping.data.get("status") == "ok"

        health = await client.call_tool("front_design_health", {})
        health_data = health.data if hasattr(health, "data") else None
        if not isinstance(health_data, dict) or health_data.get("status") != "ok":
            print("FAIL front_design_health")
            return 1
        capabilities = health_data.get("capabilities") or {}
        print(
            "HEALTH",
            health_data.get("backend"),
            (health_data.get("search") or {}).get("effective_mode"),
            f"hybrid={capabilities.get('hybrid_search')}",
        )
        # The default offline configuration must not advertise vector or hybrid search.
        if capabilities.get("vector_search") or capabilities.get("hybrid_search"):
            print("FAIL health claims vector/hybrid search in the default SQLite mode")
            return 1
        if "front_design" in str(health_data) and "password" in str(health_data).lower():
            print("FAIL health output looks like it contains credentials")
            return 1

        compare = await client.call_tool(
            "compare_frontend_options",
            {
                "options": ["motion:motion-library", "gsap:gsap-library"],
                "criteria": ["license", "accessibility"],
            },
        )
        compare_data = compare.data if hasattr(compare, "data") else None
        print("COMPARE", compare_data.get("ok") if isinstance(compare_data, dict) else compare)
        if not isinstance(compare_data, dict) or not compare_data.get("ok"):
            print("FAIL compare_frontend_options")
            return 1
        if "facts" not in compare_data or "inferences" not in compare_data:
            print("FAIL compare missing facts/inferences")
            return 1

        details = await client.call_tool(
            "get_resource_details",
            {"id": "motion:motion-library"},
        )
        details_data = details.data if hasattr(details, "data") else None
        print(
            "DETAILS",
            details_data.get("ok") if isinstance(details_data, dict) else details,
        )
        if not isinstance(details_data, dict) or not details_data.get("ok"):
            print("FAIL get_resource_details(id=...)")
            return 1

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
