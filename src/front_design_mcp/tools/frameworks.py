"""Backwards-compatible re-export of framework helpers.

The implementation moved to :mod:`front_design_mcp.frameworks` so retrieval code
can import it without pulling in the MCP tool surface.
"""

from __future__ import annotations

from front_design_mcp.frameworks import normalize_framework_token, resource_matches_framework

__all__ = ["normalize_framework_token", "resource_matches_framework"]
