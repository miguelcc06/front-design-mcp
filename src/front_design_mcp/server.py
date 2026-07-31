"""FastMCP server entry — front_design_mcp.

Package C will register the full tool surface. Package A ships a health ping only.
"""

from __future__ import annotations

from fastmcp import FastMCP

from front_design_mcp import __version__
from front_design_mcp.config import get_settings

# Tools planned for Package C (not implemented here):
# 1. front_design_search          — hybrid lexical (+ optional embedding) search
# 2. front_design_get_resource    — fetch resource by id with citations
# 3. front_design_list_sources    — list adapter sources + license notes
# 4. front_design_compare         — compare resources across dimensions
# 5. front_design_recommend       — recommend components/patterns for a brief
# 6. front_design_get_docs_chunk  — fetch documentation chunk by id
# 7. front_design_brief           — structure a FrontendBrief from free text
# 8. front_design_attribution     — emit attribution / license notes for results

mcp = FastMCP("front_design_mcp")


@mcp.tool
def front_design_ping() -> dict[str, str]:
    """Health check — returns package version and runtime mode."""
    settings = get_settings()
    mode = "offline"
    if settings.enable_network_ingest:
        mode = "online-ingest-enabled"
    return {
        "name": "front_design_mcp",
        "version": __version__,
        "mode": mode,
        "embedding_provider": settings.embedding_provider,
        "status": "ok",
    }
