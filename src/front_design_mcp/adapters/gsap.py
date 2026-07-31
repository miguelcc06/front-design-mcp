"""GSAP source adapter — Package B (catalog/metadata ONLY).

License: GSAP Standard No Charge License
https://gsap.com/community/standard-license/

Do NOT redistribute GSAP source. Always emit a license note with results.
Attribution: https://gsap.com
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef

_PKG_B = (
    "GsapAdapter: implement in Package B "
    "(catalog/metadata only — do not redistribute GSAP source; always emit license note)."
)

GSAP_LICENSE_NOTE = (
    "GSAP is distributed under the Standard No Charge License "
    "(https://gsap.com/community/standard-license/). "
    "This project indexes metadata/catalog entries only and does not redistribute GSAP source."
)


class GsapAdapter(SourceAdapter):
    """Ingest GSAP animation catalog metadata only (Package B)."""

    @property
    def source_id(self) -> str:
        return "gsap"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="gsap",
            source_name="GSAP",
            homepage_url="https://gsap.com",
            registry_url=None,
            attribution="https://gsap.com — Standard No Charge License (metadata only)",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id=None,
            name="GSAP Standard No Charge License",
            url="https://gsap.com/community/standard-license/",
            redistributable=False,
            notes=GSAP_LICENSE_NOTE,
        )

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError(_PKG_B)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        raise NotImplementedError(_PKG_B)

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        raise NotImplementedError(_PKG_B)
