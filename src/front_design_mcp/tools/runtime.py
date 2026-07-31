"""Shared runtime for MCP tools — store/search construction and serialization.

The runtime resolves the backend through :func:`create_store` and the embedding
provider through :func:`create_embedding_provider`, so the tool layer never
depends on SQLite or PostgreSQL specifics.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

from mcp.types import ToolAnnotations

from front_design_mcp.config import Settings, get_settings
from front_design_mcp.embeddings.base import EmbeddingConfigError, EmbeddingProvider
from front_design_mcp.embeddings.factory import create_embedding_provider, describe_provider
from front_design_mcp.frameworks import resource_matches_framework
from front_design_mcp.ingest.pipeline import register_post_ingest_hook, run_ingest
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import Citation, DocumentationChunk, FrontendResource, SearchHit
from front_design_mcp.search.service import SearchService
from front_design_mcp.store.base import Store
from front_design_mcp.store.factory import create_store

log = get_logger("tools.runtime")

_lock = threading.Lock()
_store: Store | None = None
_search: SearchService | None = None
_settings: Settings | None = None
_embedder: EmbeddingProvider | None = None
_ready = False

READONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    openWorldHint=False,
    idempotentHint=True,
)


def _rebuild_after_ingest(_report: Any) -> None:
    """Refresh the in-process index when ingest ran inside this process."""
    if _search is not None:
        count = _search.rebuild()
        log.info("search_index_refreshed", chunks=count)


register_post_ingest_hook(_rebuild_after_ingest)


def reset_runtime() -> None:
    """Test helper — drop cached store/search (does not delete DB files)."""
    global _store, _search, _settings, _embedder, _ready
    with _lock:
        if _store is not None:
            with contextlib.suppress(Exception):
                _store.close()
        _store = None
        _search = None
        _settings = None
        _embedder = None
        _ready = False


def _build_embedder(cfg: Settings) -> EmbeddingProvider:
    """Never let a misconfigured provider block startup — degrade to lexical."""
    try:
        return create_embedding_provider(cfg)
    except EmbeddingConfigError as exc:
        log.warning(
            "embedding_provider_unavailable",
            provider=cfg.embedding_provider,
            error=str(exc),
        )
        from front_design_mcp.embeddings.base import NullEmbeddingProvider

        return NullEmbeddingProvider()


def ensure_ready(*, settings: Settings | None = None) -> tuple[Store, SearchService]:
    """Open the configured store; auto-ingest offline fixtures when it is empty."""
    global _store, _search, _settings, _embedder, _ready
    with _lock:
        if _ready and _store is not None and _search is not None:
            return _store, _search

        cfg = settings or get_settings()
        _settings = cfg
        store = create_store(cfg)
        store.open()
        embedder = _build_embedder(cfg)

        if store.count_resources() == 0:
            log.info("auto_ingest_offline", reason="empty_store", backend=store.backend)
            report = run_ingest(
                sources=None,
                online=False,
                settings=cfg,
                store=store,
                embedder=embedder,
            )
            log.info(
                "auto_ingest_done",
                outcome=report.outcome.value,
                resources=report.total_resources,
                chunks=report.total_chunks,
            )

        search = SearchService(
            store,
            embedder=embedder,
            search_mode=cfg.search_mode,
            rrf_k=cfg.rrf_k,
            rrf_lexical_weight=cfg.rrf_lexical_weight,
            rrf_vector_weight=cfg.rrf_vector_weight,
            candidates=cfg.search_candidates,
        )
        search.rebuild()
        _store = store
        _search = search
        _embedder = embedder
        _ready = True
        return store, search


def runtime_health() -> dict[str, Any]:
    """Backend, retrieval mode, provider, and index counts. Never leaks secrets."""
    cfg = _settings or get_settings()
    store, search = ensure_ready(settings=cfg)
    capabilities = store.capabilities()
    return {
        "status": "ok",
        "ready": True,
        "backend": capabilities.backend,
        "database": cfg.redacted_database_url()
        if capabilities.backend == "postgres"
        else str(cfg.resolve_db_path()),
        "search": search.describe(),
        "embedding": describe_provider(_embedder) if _embedder is not None else None,
        "store": store.stats(),
        "capabilities": {
            "lexical_search": capabilities.lexical_search,
            "vector_search": capabilities.vector_search,
            "hybrid_search": search.resolve_mode().value == "hybrid",
        },
        "network_ingest_enabled": cfg.enable_network_ingest,
    }


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
        "retrieval": {
            "mode": hit.mode.value if hit.mode else None,
            "backend": hit.backend,
            "lexical_rank": hit.lexical_rank,
            "vector_rank": hit.vector_rank,
            "lexical_score": hit.lexical_score,
            "vector_score": hit.vector_score,
        },
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


__all__ = [
    "READONLY_ANNOTATIONS",
    "chunk_to_dict",
    "citation_to_dict",
    "empty_results_hint",
    "ensure_ready",
    "hit_to_dict",
    "provenance_from_resource",
    "reset_runtime",
    "resource_matches_framework",
    "resource_text_blob",
    "resource_to_dict",
    "runtime_health",
    "unknown_id_hint",
]
