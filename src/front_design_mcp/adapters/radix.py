"""Radix Primitives source adapter — Package B.

Curated primitives catalog from official docs URLs + fixtures (MIT).
https://www.radix-ui.com / https://github.com/radix-ui/primitives
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef

_PKG_B = (
    "RadixAdapter: implement in Package B "
    "(curated primitives catalog from official docs + fixtures)."
)


class RadixAdapter(SourceAdapter):
    """Ingest Radix primitives catalog metadata (Package B)."""

    @property
    def source_id(self) -> str:
        return "radix"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="radix",
            source_name="Radix Primitives",
            homepage_url="https://www.radix-ui.com",
            registry_url=None,
            attribution="https://www.radix-ui.com / https://github.com/radix-ui/primitives",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id="MIT",
            name="MIT",
            url="https://github.com/radix-ui/primitives/blob/main/LICENSE",
            redistributable=True,
            notes="Curated catalog metadata; attribute Radix.",
        )

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError(_PKG_B)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        raise NotImplementedError(_PKG_B)

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        raise NotImplementedError(_PKG_B)
