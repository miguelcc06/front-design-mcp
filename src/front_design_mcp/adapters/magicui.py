"""Magic UI source adapter — Package B.

Ingest from official registry https://magicui.design/r/registry.json (MIT).
Offline fixtures also supported.
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef

_PKG_B = (
    "MagicUIAdapter: implement in Package B "
    "(ingest https://magicui.design/r/registry.json + offline fixtures)."
)


class MagicUIAdapter(SourceAdapter):
    """Ingest Magic UI registry components (Package B)."""

    @property
    def source_id(self) -> str:
        return "magicui"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="magicui",
            source_name="Magic UI",
            homepage_url="https://magicui.design",
            registry_url="https://magicui.design/r/registry.json",
            attribution="https://magicui.design (MIT)",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id="MIT",
            name="MIT",
            url="https://github.com/magicuidesign/magicui/blob/main/LICENSE.md",
            redistributable=True,
            notes="Registry metadata and component docs; attribute Magic UI.",
        )

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError(_PKG_B)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        raise NotImplementedError(_PKG_B)

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        raise NotImplementedError(_PKG_B)
