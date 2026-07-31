"""Motion (motion.dev) source adapter — Package B.

Attribution: https://motion.dev / https://github.com/motiondivision/motion (MIT).
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef

_PKG_B = "MotionAdapter: implement in Package B (curated animation patterns + npm/docs metadata)."


class MotionAdapter(SourceAdapter):
    """Ingest Motion animation patterns and docs metadata (Package B)."""

    @property
    def source_id(self) -> str:
        return "motion"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="motion",
            source_name="Motion",
            homepage_url="https://motion.dev",
            registry_url=None,
            attribution="https://motion.dev / https://github.com/motiondivision/motion",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id="MIT",
            name="MIT",
            url="https://github.com/motiondivision/motion/blob/main/LICENSE",
            redistributable=True,
            notes="Curated patterns + metadata; attribute Motion.",
        )

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError(_PKG_B)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        raise NotImplementedError(_PKG_B)

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        raise NotImplementedError(_PKG_B)
