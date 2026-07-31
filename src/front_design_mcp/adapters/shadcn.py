"""shadcn/ui source adapter.

Ingest from https://ui.shadcn.com/r/index.json (MIT).
"""

from __future__ import annotations

from typing import Any

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import (
    fetch_json,
    find_by_id,
    load_fixture_list,
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

INDEX_URL = "https://ui.shadcn.com/r/index.json"


class ShadcnAdapter(SourceAdapter):
    """Ingest shadcn/ui registry index."""

    http_timeout: float = 30.0

    @property
    def source_id(self) -> str:
        return "shadcn"

    @property
    def source_ref(self) -> SourceRef:
        return SourceRef(
            source_id="shadcn",
            source_name="shadcn/ui",
            homepage_url="https://ui.shadcn.com",
            registry_url=INDEX_URL,
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

    def _load_index(self, *, offline: bool) -> list[dict[str, Any]]:
        if offline:
            data: object = load_fixture_list("shadcn", "index.json")
        else:
            data = fetch_json(INDEX_URL, timeout=self.http_timeout)
        if not isinstance(data, list):
            raise ValueError("Unexpected shadcn index shape (expected list)")
        return [i for i in data if isinstance(i, dict)]

    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        return self._load_index(offline=offline)

    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        return find_by_id(self.fetch_catalog(offline=offline), item_id, id_keys=("name",))

    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        name = sanitize_text(str(raw.get("name") or "unknown"), max_length=120)
        title = name.replace("-", " ").title()
        description = sanitize_text(
            str(raw.get("description") or f"shadcn/ui {title} component."),
            max_length=2000,
        )
        docs_url = raw.get("docs_url_hint") or f"https://ui.shadcn.com/docs/components/{name}"
        deps = raw.get("dependencies") or []
        tags = ["shadcn", "component", name]
        caps = [sanitize_text(str(d), max_length=64) for d in deps[:12]]

        return FrontendResource(
            id=f"shadcn:{name}",
            kind=ResourceKind.COMPONENT,
            name=title,
            description=description,
            source=self.source_ref,
            homepage_url=self.source_ref.homepage_url,
            docs_url=docs_url,
            install_command=f"npx shadcn@latest add {name}",
            license=self.license_info,
            supported_frameworks=["react", "next"],
            tags=tags,
            capabilities=caps,
            accessibility_notes=(
                "Built on accessible primitives (Radix / Base UI / React Aria variants)."
            ),
            performance_notes=None,
            last_indexed_at=utc_now(),
            attribution=self.source_ref.attribution,
            raw_refs={
                "registry_type": raw.get("type"),
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
            extra_summaries=[
                (
                    f"{resource.name} install",
                    (
                        f"Install with `{resource.install_command}`. "
                        f"Copy the component into your project and restyle with Tailwind."
                    ),
                )
            ],
        )
