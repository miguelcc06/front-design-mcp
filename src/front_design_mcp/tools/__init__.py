"""MCP tools package — register product-brief tool surface on FastMCP."""

from __future__ import annotations

from typing import TYPE_CHECKING

from front_design_mcp.tools import handlers
from front_design_mcp.tools.runtime import READONLY_ANNOTATIONS

if TYPE_CHECKING:
    from fastmcp import FastMCP

_ANNOTATIONS = READONLY_ANNOTATIONS


def register_tools(mcp: FastMCP) -> None:
    """Register all Package C tools (exact product-brief names) on ``mcp``."""

    mcp.tool(
        handlers.discover_frontend_resources,
        name="discover_frontend_resources",
        annotations=_ANNOTATIONS,
        description=(
            "Browse and filter indexed frontend resources (components, patterns, libraries). "
            "Supports category/kind, framework, style/tags, license, accessibility, animation, "
            "maturity, source_id, limit, and offset. Returns paginated items with provenance."
        ),
    )
    mcp.tool(
        handlers.search_frontend_knowledge,
        name="search_frontend_knowledge",
        annotations=_ANNOTATIONS,
        description=(
            "BM25 search over frontend knowledge chunks. Pass query plus optional filters, "
            "limit, and detail_level (brief|standard|full). Returns scores, citations, provenance."
        ),
    )
    mcp.tool(
        handlers.get_resource_details,
        name="get_resource_details",
        annotations=_ANNOTATIONS,
        description=(
            "Fetch a normalized FrontendResource by id (resource id string, e.g. "
            "motion:motion-library), related sanitized documentation chunks, and "
            "license/attribution. Parameter name is `id`."
        ),
    )
    mcp.tool(
        handlers.compare_frontend_options,
        name="compare_frontend_options",
        annotations=_ANNOTATIONS,
        description=(
            "Compare frontend options by id or name. Primary parameter: `options` "
            "(list of ids/names). Deprecated alias: `resources`. Separates facts from "
            "inferences; never claims unverified compatibility."
        ),
    )
    mcp.tool(
        handlers.recommend_frontend_stack,
        name="recommend_frontend_stack",
        annotations=_ANNOTATIONS,
        description=(
            "Recommend a frontend stack from requirements, target_framework, constraints, "
            "aesthetics, accessibility, and performance. Returns recommendation, trade-offs, "
            "incompatibilities, plan, sources, with facts vs inferences."
        ),
    )
    mcp.tool(
        handlers.find_components,
        name="find_components",
        annotations=_ANNOTATIONS,
        description=(
            "Find components/patterns for an intent string "
            "(hero, pricing, navbar, dashboard, onboarding, microinteraction, scroll animation, …) "
            "with optional framework filter."
        ),
    )
    mcp.tool(
        handlers.find_animation_patterns,
        name="find_animation_patterns",
        annotations=_ANNOTATIONS,
        description=(
            "Find animation patterns for a query/use-case. Includes cost notes, accessibility, "
            "and prefers-reduced-motion support when known from indexed notes; cites sources."
        ),
    )
    mcp.tool(
        handlers.build_frontend_brief,
        name="build_frontend_brief",
        annotations=_ANNOTATIONS,
        description=(
            "Build an implementation brief from product_description + constraints: stack, "
            "components, motion system, suggested design tokens, responsive behavior, "
            "and acceptance criteria. Inferences are marked clearly."
        ),
    )


__all__ = ["register_tools", "handlers"]
