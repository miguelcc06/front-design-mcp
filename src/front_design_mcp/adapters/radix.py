"""Radix Primitives source adapter — curated catalog + fixtures (MIT)."""

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
    "component": ResourceKind.COMPONENT,
    "pattern": ResourceKind.PATTERN,
}


class RadixAdapter(SourceAdapter):
    """Ingest Radix primitives catalog metadata."""

    http_timeout: float = 30.0

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

    def _load_catalog_doc(self, *, offline: bool) -> dict[str, Any]:
        _ = offline  # curated fixtures are source of truth for v1
        return load_fixture_json("radix", "catalog.json")

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
        raise KeyError(f"Radix item not found: {item_id!r}")

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        rid = sanitize_text(str(raw.get("id") or raw.get("name") or "unknown"), max_length=120)
        kind = _KIND_MAP.get(str(raw.get("kind", "component")), ResourceKind.COMPONENT)
        name = sanitize_text(str(raw.get("name") or rid), max_length=200)
        description = sanitize_text(str(raw.get("description") or ""), max_length=2000)
        package = raw.get("package")
        install = raw.get("install_command")
        if not install and package:
            install = f"npm install {package}"
        tags = [sanitize_text(str(t), max_length=64) for t in (raw.get("tags") or [])]
        caps = [sanitize_text(str(c), max_length=64) for c in (raw.get("capabilities") or [])]

        return FrontendResource(
            id=f"radix:{rid}",
            kind=kind,
            name=name,
            description=description,
            source=self.source_ref,
            homepage_url=raw.get("homepage_url") or self.source_ref.homepage_url,
            docs_url=raw.get("docs_url"),
            install_command=install,
            license=self.license_info,
            supported_frameworks=["react"],
            tags=tags,
            capabilities=caps,
            accessibility_notes=sanitize_text(
                "WAI-ARIA compliant unstyled primitive; compose with your design system.",
                max_length=500,
            ),
            performance_notes=None,
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={"fixture_id": rid, "package": package},
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
