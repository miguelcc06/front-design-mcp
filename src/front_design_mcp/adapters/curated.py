"""Curated pattern/template adapter — local fixtures linking to upstream docs.

Attribution: front-design-mcp curated patterns linking to upstream docs (MIT/internal).
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import (
    find_by_id,
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
    "pattern": ResourceKind.PATTERN,
    "template": ResourceKind.TEMPLATE,
    "component": ResourceKind.COMPONENT,
    "animation": ResourceKind.ANIMATION,
}


class CuratedAdapter(SourceAdapter):
    """Ingest curated UI/UX patterns designed for intent coverage (hero, pricing, …)."""

    http_timeout: float = 30.0

    @property
    def source_id(self) -> str:
        return "curated"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="curated",
            source_name="front-design-mcp curated patterns",
            homepage_url="https://github.com/miguelcc06/front-design-mcp",
            registry_url=None,
            attribution="front-design-mcp curated patterns linking to upstream docs",
        )

    @property
    def license_info(self) -> LicenseInfo:
        return LicenseInfo(
            spdx_id="MIT",
            name="MIT (internal curated metadata)",
            url=None,
            redistributable=True,
            notes=(
                "Curated pattern/template metadata maintained by front-design-mcp. "
                "Links to upstream docs; respect each upstream license when adopting code."
            ),
        )

    def _load_doc(self, *, offline: bool) -> dict[str, Any]:
        _ = offline  # fixtures-only source
        return load_fixture_json("curated", "patterns.json")

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        doc = self._load_doc(offline=offline)
        items = doc.get("items") or []
        return [i for i in items if isinstance(i, dict)]

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        return find_by_id(
            self.fetch_catalog(offline=offline),
            item_id,
            id_keys=("id", "name"),
        )

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        rid = sanitize_text(str(raw.get("id") or raw.get("name") or "unknown"), max_length=120)
        kind = _KIND_MAP.get(str(raw.get("kind", "pattern")), ResourceKind.PATTERN)
        name = sanitize_text(str(raw.get("name") or rid), max_length=200)
        description = sanitize_text(str(raw.get("description") or ""), max_length=2000)
        tags = [sanitize_text(str(t), max_length=64) for t in (raw.get("tags") or [])]
        style_tags = [
            sanitize_text(str(t), max_length=64) for t in (raw.get("style_tags") or [])
        ]
        for st in style_tags:
            if st and st not in tags:
                tags.append(st)
        maturity = sanitize_text(str(raw.get("maturity") or "stable"), max_length=32)
        if maturity and maturity not in tags:
            tags.append(maturity)
        if raw.get("animation") and "animation" not in tags:
            tags.append("animation")

        caps = [sanitize_text(str(c), max_length=64) for c in (raw.get("capabilities") or [])]
        frameworks = [
            sanitize_text(str(f), max_length=32)
            for f in (raw.get("supported_frameworks") or ["react"])
        ]
        a11y = raw.get("accessibility_notes")
        perf = raw.get("performance_notes")
        docs_url = raw.get("docs_url")

        return FrontendResource(
            id=f"curated:{rid}",
            kind=kind,
            name=name,
            description=description,
            source=self.source_ref,
            homepage_url=self.source_ref.homepage_url,
            docs_url=docs_url,
            install_command=None,
            license=self.license_info,
            supported_frameworks=frameworks,
            tags=tags,
            capabilities=caps,
            accessibility_notes=sanitize_text(a11y, max_length=800) if a11y else None,
            performance_notes=sanitize_text(perf, max_length=800) if perf else None,
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={
                "fixture_id": rid,
                "style_tags": style_tags,
                "maturity": maturity,
                "animation": bool(raw.get("animation")),
                "upstream_refs": raw.get("upstream_refs") or [],
                "related_sources": raw.get("related_sources") or [],
            },
        )

    def build_chunks(self, resource: FrontendResource) -> list[DocumentationChunk]:
        extras: list[tuple[str, str]] = []
        a11y = resource.accessibility_notes
        perf = resource.performance_notes
        if a11y or perf:
            body_parts = []
            if a11y:
                body_parts.append(f"Accessibility: {a11y}")
            if perf:
                body_parts.append(f"Performance / cost: {perf}")
            extras.append((f"{resource.name} a11y and cost notes", " ".join(body_parts)))
        upstream = resource.raw_refs.get("upstream_refs") or []
        if upstream:
            extras.append(
                (
                    f"{resource.name} upstream docs",
                    "Upstream references: " + "; ".join(str(u) for u in upstream[:6]),
                )
            )
        return make_chunks_for_resource(
            resource_id=resource.id,
            name=resource.name,
            description=resource.description,
            docs_url=resource.docs_url,
            license_info=resource.license or self.license_info,
            tags=resource.tags,
            extra_summaries=extras or None,
            source_id=self.source_id,
        )
