"""GSAP source adapter — catalog/metadata ONLY.

License: GSAP Standard No Charge License
https://gsap.com/community/standard-license/

Do NOT redistribute GSAP source. Always emit a license note with results.
Attribution: https://gsap.com
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import (
    load_fixture_dict,
    make_chunks_for_resource,
    sanitize_text,
    utc_now,
)
from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)

GSAP_LICENSE_NOTE = (
    "GSAP is distributed under the Standard No Charge License "
    "(https://gsap.com/community/standard-license/). "
    "Free for most commercial use per Webflow/GSAP announcement; "
    "library source must not be redistributed. "
    "This project indexes metadata/catalog entries only."
)

_KIND_MAP = {
    "library": ResourceKind.LIBRARY,
    "animation": ResourceKind.ANIMATION,
    "pattern": ResourceKind.PATTERN,
}


class GsapAdapter(SourceAdapter):
    """Ingest GSAP animation catalog metadata only."""

    http_timeout: float = 30.0

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

    def _load_catalog_doc(self, *, offline: bool) -> dict[str, Any]:
        _ = offline
        return load_fixture_dict("gsap", "catalog.json")

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        doc = self._load_catalog_doc(offline=offline)
        items: list[dict[str, Any]] = []
        library = doc.get("library")
        if library:
            items.append({**library, "_role": "library"})
        for raw in doc.get("items") or []:
            items.append({**raw, "_role": "item"})
        return items

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        for item in self.fetch_catalog(offline=offline):
            if item.get("id") == item_id or item.get("name") == item_id:
                return item
        raise KeyError(f"GSAP item not found: {item_id!r}")

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        rid = sanitize_text(str(raw.get("id") or raw.get("name") or "unknown"), max_length=120)
        kind = _KIND_MAP.get(str(raw.get("kind", "pattern")), ResourceKind.PATTERN)
        name = sanitize_text(str(raw.get("name") or rid), max_length=200)
        description = sanitize_text(str(raw.get("description") or ""), max_length=2000)
        tags = [sanitize_text(str(t), max_length=64) for t in (raw.get("tags") or [])]
        tags = list(dict.fromkeys([*tags, "gsap", "metadata-only"]))
        caps = [sanitize_text(str(c), max_length=64) for c in (raw.get("capabilities") or [])]
        a11y = raw.get("accessibility_notes")

        return FrontendResource(
            id=f"gsap:{rid}",
            kind=kind,
            name=name,
            description=description,
            source=self.source_ref,
            homepage_url=raw.get("homepage_url") or self.source_ref.homepage_url,
            docs_url=raw.get("docs_url"),
            install_command=raw.get("install_command") or "npm install gsap",
            license=self.license_info,
            supported_frameworks=["javascript", "react", "vue"],
            tags=tags,
            capabilities=caps,
            accessibility_notes=sanitize_text(a11y, max_length=500) if a11y else None,
            performance_notes="High-performance tweens; respect reduced-motion via matchMedia.",
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={
                "fixture_id": rid,
                "redistributable": False,
                "license": "GSAP Standard No Charge License",
            },
        )

    def build_chunks(self, resource: FrontendResource) -> list[DocumentationChunk]:
        extras = [
            (
                f"{resource.name} license note",
                GSAP_LICENSE_NOTE,
            )
        ]
        return make_chunks_for_resource(
            resource_id=resource.id,
            name=resource.name,
            description=resource.description,
            docs_url=resource.docs_url,
            license_info=resource.license or self.license_info,
            tags=resource.tags,
            source_id=self.source_id,
            extra_summaries=extras,
        )
