"""Shared runtime for MCP tools — store, search, auto-ingest, serialization."""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from mcp.types import ToolAnnotations

from front_design_mcp.config import Settings, get_settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import Citation, DocumentationChunk, FrontendResource, SearchHit
from front_design_mcp.search.service import SearchService
from front_design_mcp.store.sqlite_store import SqliteStore
from front_design_mcp.tools.frameworks import normalize_framework_token

log = get_logger("tools.runtime")

_lock = threading.Lock()
_store: SqliteStore | None = None
_search: SearchService | None = None
_settings: Settings | None = None
_ready = False

READONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    idempotentHint=True,
)


def reset_runtime() -> None:
    """Test helper — drop cached store/search (does not delete DB files)."""
    global _store, _search, _settings, _ready
    with _lock:
        if _store is not None:
            with contextlib.suppress(Exception):
                _store.close()
        _store = None
        _search = None
        _settings = None
        _ready = False


def ensure_ready(*, settings: Settings | None = None) -> tuple[SqliteStore, SearchService]:
    """Open SQLite store; auto-ingest offline fixtures when empty."""
    global _store, _search, _settings, _ready
    with _lock:
        if _ready and _store is not None and _search is not None:
            return _store, _search

        cfg = settings or get_settings()
        _settings = cfg
        db_path = cfg.resolve_db_path()
        store = SqliteStore(db_path)
        store.open()

        if store.count_resources() == 0:
            log.info(
                "auto_ingest_offline",
                reason="empty_db",
                db_path=str(db_path),
            )
            report = run_ingest(sources=None, online=False, settings=cfg, store=store)
            log.info(
                "auto_ingest_done",
                ok=report.ok,
                resources=report.total_resources,
                chunks=report.total_chunks,
            )

        search = SearchService(store)
        search.rebuild()
        _store = store
        _search = search
        _ready = True
        return store, search


def resource_to_dict(resource: FrontendResource) -> dict[str, Any]:
    return resource.model_dump(mode="json")


def chunk_to_dict(chunk: DocumentationChunk, *, sanitize: bool = True) -> dict[str, Any]:
    data = chunk.model_dump(mode="json")
    if sanitize and data.get("content"):
        # Chunks are already sanitized at ingest; reaffirm untrusted marker for agents.
        content = str(data["content"])
        if not content.startswith("[UNTRUSTED"):
            data["content"] = f"[UNTRUSTED SOURCE DATA] {content}"
        data["untrusted"] = True
    return data


def citation_to_dict(citation: Citation | None) -> dict[str, Any] | None:
    if citation is None:
        return None
    return citation.model_dump(mode="json")


def provenance_from_resource(resource: FrontendResource) -> dict[str, Any]:
    license_note = None
    if resource.license:
        parts: list[str] = []
        if resource.license.spdx_id:
            parts.append(resource.license.spdx_id)
        elif resource.license.name:
            parts.append(resource.license.name)
        if resource.license.name and resource.license.spdx_id and (
            resource.license.spdx_id not in resource.license.name
        ):
            parts.append(f"({resource.license.name})")
        if resource.license.notes:
            parts.append(resource.license.notes)
        license_note = " — ".join(parts) if parts else None
    return {
        "source_id": resource.source.source_id,
        "source_name": resource.source.source_name,
        "url": resource.docs_url or resource.homepage_url,
        "license_note": license_note,
        "attribution": resource.attribution or resource.source.attribution,
    }


def hit_to_dict(hit: SearchHit, *, detail: str = "standard") -> dict[str, Any]:
    resource = hit.resource
    chunk = hit.chunk
    out: dict[str, Any] = {
        "score": hit.score,
        "facts": list(hit.facts),
        "inferences": list(hit.inferences),
        "citation": citation_to_dict(hit.citation),
        "provenance": provenance_from_resource(resource) if resource else None,
    }
    if resource is not None:
        if detail == "brief":
            out["resource"] = {
                "id": resource.id,
                "name": resource.name,
                "kind": resource.kind.value,
                "source_id": resource.source.source_id,
                "tags": resource.tags[:8],
            }
        elif detail == "full":
            out["resource"] = resource_to_dict(resource)
            if chunk is not None:
                out["chunk"] = chunk_to_dict(chunk)
        else:
            out["resource"] = {
                "id": resource.id,
                "name": resource.name,
                "kind": resource.kind.value,
                "description": resource.description[:400],
                "source_id": resource.source.source_id,
                "tags": resource.tags,
                "supported_frameworks": resource.supported_frameworks,
                "docs_url": resource.docs_url,
                "install_command": resource.install_command,
            }
            if chunk is not None:
                out["chunk"] = {
                    "id": chunk.id,
                    "title": chunk.title,
                    "excerpt": chunk.content[:280] if chunk.content else None,
                    "source_url": chunk.source_url,
                }
    return out


def empty_results_hint(query: str | None = None) -> str:
    base = (
        "No matches. Try a broader query, drop filters, or call "
        "discover_frontend_resources / search_frontend_knowledge."
    )
    if query:
        return f"{base} Original query: {query!r}."
    return base


def unknown_id_hint(resource_id: str) -> str:
    return (
        f"Unknown resource id {resource_id!r}. "
        "Use discover_frontend_resources or search_frontend_knowledge to find valid ids."
    )


def resource_matches_framework(resource: FrontendResource, framework: str | None) -> bool:
    """True when target framework aliases intersect resource frameworks.

    Empty ``supported_frameworks`` does **not** exclude the resource
    (unknown ≠ incompatible). Callers should add an inference note when
    recommending such resources against a target framework.
    """
    if not framework:
        return True
    target = normalize_framework_token(framework)
    if not target:
        return True
    if not resource.supported_frameworks:
        return True
    resource_tokens: set[str] = set()
    for labeled in resource.supported_frameworks:
        resource_tokens |= normalize_framework_token(labeled)
    return bool(target & resource_tokens)


def resource_text_blob(resource: FrontendResource) -> str:
    return " ".join(
        [
            resource.id,
            resource.name,
            resource.description,
            " ".join(resource.tags),
            " ".join(resource.capabilities),
            resource.accessibility_notes or "",
            resource.performance_notes or "",
        ]
    ).lower()
