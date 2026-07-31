"""Motion (motion.dev) source adapter — curated catalog + fixtures.

Attribution: https://motion.dev / https://github.com/motiondivision/motion (MIT).
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import (
    load_fixture_json,
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

_KIND_MAP = {
    "library": ResourceKind.LIBRARY,
    "animation": ResourceKind.ANIMATION,
    "pattern": ResourceKind.PATTERN,
    "component": ResourceKind.COMPONENT,
}


class MotionAdapter(SourceAdapter):
    """Ingest Motion animation patterns and docs metadata from curated fixtures."""

    http_timeout: float = 30.0

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

    def _load_catalog_doc(self, *, offline: bool) -> dict[str, Any]:
        # Curated catalog only — no fragile HTML scrape (online == fixtures for v1).
        _ = offline
        return load_fixture_json("motion", "catalog.json")

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
        raise KeyError(f"Motion item not found: {item_id!r}")

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        rid = sanitize_text(str(raw.get("id") or raw.get("name") or "unknown"), max_length=120)
        kind = _KIND_MAP.get(str(raw.get("kind", "pattern")), ResourceKind.PATTERN)
        name = sanitize_text(str(raw.get("name") or rid), max_length=200)
        description = sanitize_text(str(raw.get("description") or ""), max_length=2000)
        docs_url = raw.get("docs_url")
        homepage = raw.get("homepage_url") or self.source_ref.homepage_url
        install = raw.get("install_command") or "npm install motion"
        tags = [sanitize_text(str(t), max_length=64) for t in (raw.get("tags") or [])]
        caps = [sanitize_text(str(c), max_length=64) for c in (raw.get("capabilities") or [])]
        a11y = raw.get("accessibility_notes")
        return FrontendResource(
            id=f"motion:{rid}",
            kind=kind,
            name=name,
            description=description,
            source=self.source_ref,
            homepage_url=homepage,
            docs_url=docs_url,
            install_command=install,
            license=self.license_info,
            supported_frameworks=["react", "javascript", "vue"],
            tags=tags,
            capabilities=caps,
            accessibility_notes=sanitize_text(a11y, max_length=500) if a11y else None,
            performance_notes=None,
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={"fixture_id": rid, "role": raw.get("_role")},
        )

    def build_chunks(self, resource: FrontendResource) -> list[DocumentationChunk]:
        return make_chunks_for_resource(
            resource_id=resource.id,
            name=resource.name,
            description=resource.description,
            docs_url=resource.docs_url,
            license_info=resource.license or self.license_info,
            tags=resource.tags,
            source_id=self.source_id,
        )
