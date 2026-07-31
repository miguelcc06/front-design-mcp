"""Magic UI source adapter.

Ingest from official registry https://magicui.design/r/registry.json (MIT).
Offline fixtures preferred when network ingest is disabled.
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import (
    fetch_json,
    find_by_id,
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

REGISTRY_URL = "https://magicui.design/r/registry.json"


class MagicUIAdapter(SourceAdapter):
    """Ingest Magic UI registry components."""

    http_timeout: float = 30.0

    @property
    def source_id(self) -> str:
        return "magicui"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="magicui",
            source_name="Magic UI",
            homepage_url="https://magicui.design",
            registry_url=REGISTRY_URL,
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

    def _load_registry(self, *, offline: bool) -> dict[str, Any]:
        if offline:
            return load_fixture_dict("magicui", "registry.json")
        data = fetch_json(REGISTRY_URL, timeout=self.http_timeout)
        if not isinstance(data, dict) or "items" not in data:
            raise ValueError("Unexpected Magic UI registry shape")
        return data

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        registry = self._load_registry(offline=offline)
        items = registry.get("items") or []
        homepage = registry.get("homepage") or self.source_ref.homepage_url
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            enriched = dict(item)
            enriched["_registry_homepage"] = homepage
            out.append(enriched)
        return out

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        return find_by_id(self.fetch_catalog(offline=offline), item_id, id_keys=("name",))

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        name = sanitize_text(str(raw.get("name") or "unknown"), max_length=120)
        title = sanitize_text(str(raw.get("title") or name), max_length=200)
        description = sanitize_text(str(raw.get("description") or ""), max_length=2000)
        rtype = str(raw.get("type") or "registry:ui")
        tags = ["magicui"]
        if rtype == "registry:ui":
            kind = ResourceKind.COMPONENT
            tags.append("component")
        elif rtype == "registry:example":
            kind = ResourceKind.PATTERN
            tags.extend(["pattern", "example"])
        else:
            kind = ResourceKind.PATTERN
            tags.append(rtype.replace("registry:", ""))

        docs_url = f"https://magicui.design/docs/components/{name}"
        if rtype == "registry:example":
            # examples often mirror a component name with -demo suffix
            base = name.removesuffix("-demo")
            docs_url = f"https://magicui.design/docs/components/{base}"

        deps = raw.get("dependencies") or []
        caps = [sanitize_text(str(d), max_length=64) for d in deps[:12]]
        homepage = raw.get("_registry_homepage") or self.source_ref.homepage_url

        return FrontendResource(
            id=f"magicui:{name}",
            kind=kind,
            name=title,
            description=description,
            source=self.source_ref,
            homepage_url=homepage,
            docs_url=docs_url,
            install_command=f"npx shadcn@latest add @magicui/{name}",
            license=self.license_info,
            supported_frameworks=["react", "next"],
            tags=tags,
            capabilities=caps,
            accessibility_notes=None,
            performance_notes=None,
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={
                "registry_type": rtype,
                "name": name,
                "registryDependencies": raw.get("registryDependencies") or [],
            },
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
