"""Run the MCP server over stdio."""

from __future__ import annotations

from front_design_mcp.config import get_settings
from front_design_mcp.logging_utils import configure_logging
from front_design_mcp.server import mcp


def main() -> None:
    """Entry point for ``front-design-mcp`` and ``python -m front_design_mcp``."""
    settings = get_settings()
    configure_logging(settings.log_level)
    mcp.run()


if __name__ == "__main__":
    main()
