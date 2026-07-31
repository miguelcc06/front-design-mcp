"""FastMCP server entry — front_design_mcp.

Package C will register the full tool surface. Package A ships a health ping only.
"""

from __future__ import annotations

from fastmcp import FastMCP

from front_design_mcp import __version__
from front_design_mcp.config import get_settings

# Tools planned for Package C (exact product-brief names — not implemented here):
# 1. discover_frontend_resources
# 2. search_frontend_knowledge
# 3. get_resource_details
# 4. compare_frontend_options
# 5. recommend_frontend_stack
# 6. find_components
# 7. find_animation_patterns
# 8. build_frontend_brief
# Plus keep: front_design_ping

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
