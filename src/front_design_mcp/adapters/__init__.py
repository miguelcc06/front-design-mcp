"""Adapter registry — maps source_id → adapter class (lazy import)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from front_design_mcp.adapters.base import SourceAdapter

ADAPTER_SOURCE_IDS: tuple[str, ...] = (
    "motion",
    "magicui",
    "shadcn",
    "radix",
    "gsap",
)


def get_adapter_class(source_id: str) -> type[SourceAdapter]:
    """Lazily import and return the adapter class for ``source_id``."""
    if source_id == "motion":
        from front_design_mcp.adapters.motion import MotionAdapter

        return MotionAdapter
    if source_id == "magicui":
        from front_design_mcp.adapters.magicui import MagicUIAdapter

        return MagicUIAdapter
    if source_id == "shadcn":
        from front_design_mcp.adapters.shadcn import ShadcnAdapter

        return ShadcnAdapter
    if source_id == "radix":
        from front_design_mcp.adapters.radix import RadixAdapter

        return RadixAdapter
    if source_id == "gsap":
        from front_design_mcp.adapters.gsap import GsapAdapter

        return GsapAdapter
    raise KeyError(f"Unknown source adapter: {source_id!r}")


def list_adapters() -> dict[str, type[SourceAdapter]]:
    """Return a dict of all registered adapter classes."""
    return {sid: get_adapter_class(sid) for sid in ADAPTER_SOURCE_IDS}


__all__ = [
    "ADAPTER_SOURCE_IDS",
    "get_adapter_class",
    "list_adapters",
]
