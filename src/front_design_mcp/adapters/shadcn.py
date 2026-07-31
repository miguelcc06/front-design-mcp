"""shadcn/ui source adapter — Package B.

Ingest from https://ui.shadcn.com/r/index.json (MIT).
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef

_PKG_B = (
    "ShadcnAdapter: implement in Package B "
    "(ingest https://ui.shadcn.com/r/index.json + offline fixtures)."
)


class ShadcnAdapter(SourceAdapter):
    """Ingest shadcn/ui registry index (Package B)."""

    @property
    def source_id(self) -> str:
        return "shadcn"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="shadcn",
            source_name="shadcn/ui",
            homepage_url="https://ui.shadcn.com",
            registry_url="https://ui.shadcn.com/r/index.json",
            attribution="https://ui.shadcn.com (MIT)",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id="MIT",
            name="MIT",
            url="https://github.com/shadcn-ui/ui/blob/main/LICENSE.md",
            redistributable=True,
            notes="Registry metadata; attribute shadcn/ui.",
        )

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError(_PKG_B)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        raise NotImplementedError(_PKG_B)

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        raise NotImplementedError(_PKG_B)
