"""Ingest pipeline: adapters → Store (batched, incremental, optional embeddings)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from front_design_mcp.adapters import ADAPTER_SOURCE_IDS, get_adapter_class
from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import make_chunks_for_resource
from front_design_mcp.config import Settings, get_settings
from front_design_mcp.embeddings.base import EmbeddingProvider
from front_design_mcp.embeddings.factory import create_embedding_provider, describe_provider
from front_design_mcp.ingest.embedding_sync import sync_embeddings
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import DocumentationChunk, FrontendResource
from front_design_mcp.store.base import Store, SyncOutcome
from front_design_mcp.store.factory import create_store

log = get_logger("ingest.pipeline")

_PostIngestHook = Callable[["IngestReport"], None]
_post_ingest_hooks: list[_PostIngestHook] = []


def register_post_ingest_hook(hook: Callable[[IngestReport], None]) -> None:
    """Register a callback invoked just before ``run_ingest`` returns.

    Each hook is wrapped so exceptions are logged as warnings and never fail the
    ingest. Used by the MCP runtime to rebuild the in-memory BM25 index.
    """
    _post_ingest_hooks.append(hook)


def clear_post_ingest_hooks() -> None:
    """Remove all post-ingest hooks (for tests)."""
    _post_ingest_hooks.clear()


@dataclass
class SourceIngestStats:
    source_id: str
    resources: int = 0
    resources_written: int = 0
    resources_deleted: int = 0
    chunks: int = 0
    chunks_written: int = 0
    chunks_unchanged: int = 0
    chunks_deleted: int = 0
    embeddings_written: int = 0
    embeddings_reused: int = 0
    item_errors: int = 0
    pruned: bool = False
    prune_skipped_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestReport:
    ok: bool
    outcome: SyncOutcome
    mode: str
    started_at: str
    finished_at: str
    db_path: str
    backend: str
    sources: list[SourceIngestStats] = field(default_factory=list)
    total_resources: int = 0
    total_chunks: int = 0
    resources_written: int = 0
    resources_deleted: int = 0
    chunks_written: int = 0
    chunks_unchanged: int = 0
    chunks_deleted: int = 0
    embeddings_written: int = 0
    embeddings_reused: int = 0
    item_errors: int = 0
    embedding: dict[str, object] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "outcome": self.outcome.value,
            "mode": self.mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "db_path": self.db_path,
            "backend": self.backend,
            "sources": [s.to_dict() for s in self.sources],
            "total_resources": self.total_resources,
            "total_chunks": self.total_chunks,
            "resources_written": self.resources_written,
            "resources_deleted": self.resources_deleted,
            "chunks_written": self.chunks_written,
            "chunks_unchanged": self.chunks_unchanged,
            "chunks_deleted": self.chunks_deleted,
            "embeddings_written": self.embeddings_written,
            "embeddings_reused": self.embeddings_reused,
            "item_errors": self.item_errors,
            "embedding": self.embedding,
        }


def _adapter_chunks(adapter: SourceAdapter, resource: FrontendResource) -> list[DocumentationChunk]:
    """Prefer adapter.build_chunks when present; else shared curated summaries."""
    build = getattr(adapter, "build_chunks", None)
    if callable(build):
        chunks = build(resource)
        if chunks:
            return list(chunks)
    return make_chunks_for_resource(
        resource_id=resource.id,
        name=resource.name,
        description=resource.description,
        docs_url=resource.docs_url,
        license_info=resource.license or adapter.license_info,
        tags=resource.tags,
        source_id=adapter.source_id,
    )


def _license_signature(chunk: DocumentationChunk) -> object:
    if chunk.license is None:
        return None
    return chunk.license.model_dump(mode="json")


def chunk_needs_persist(
    existing: DocumentationChunk | None, new: DocumentationChunk
) -> bool:
    """True when any *persisted* chunk field differs (excluding last_indexed_at).

    Adapters stamp ``last_indexed_at`` with ``utc_now()`` on every run, so comparing
    that field would force a full rewrite. Title, tags, URL, version, licence, and
    content must still trigger an upsert when they change.
    """
    if existing is None:
        return True
    return (
        existing.resource_id != new.resource_id
        or existing.title != new.title
        or existing.content != new.content
        or existing.source_url != new.source_url
        or existing.version != new.version
        or _license_signature(existing) != _license_signature(new)
        or list(existing.tags) != list(new.tags)
        or existing.content_sha256 != new.content_sha256
    )


def _collect_source(
    adapter: SourceAdapter,
    *,
    offline: bool,
) -> tuple[list[FrontendResource], list[DocumentationChunk], int, str | None]:
    """Fetch + normalize one source. Returns (resources, chunks, item_errors, error)."""
    resources: list[FrontendResource] = []
    chunks: list[DocumentationChunk] = []
    item_errors = 0
    try:
        catalog = adapter.fetch_catalog(offline=offline)
    except Exception as exc:  # noqa: BLE001 — isolate per-adapter failures
        log.error("ingest_source_failed", source_id=adapter.source_id, error=str(exc))
        return [], [], 0, str(exc)

    for raw in catalog:
        try:
            resource = adapter.normalize(raw)
            resources.append(resource)
            chunks.extend(_adapter_chunks(adapter, resource))
        except Exception as item_exc:  # noqa: BLE001 — isolate per-item failures
            item_errors += 1
            log.warning(
                "ingest_item_failed",
                source_id=adapter.source_id,
                error=str(item_exc),
            )
    return resources, chunks, item_errors, None


def _ingest_one_source(
    adapter: SourceAdapter,
    store: Store,
    *,
    offline: bool,
    prune: bool,
    embed: bool,
    embedder: EmbeddingProvider | None,
    batch_size: int,
) -> SourceIngestStats:
    stats = SourceIngestStats(source_id=adapter.source_id)
    resources, chunks, item_errors, fetch_error = _collect_source(adapter, offline=offline)
    stats.item_errors = item_errors
    stats.resources = len(resources)
    stats.chunks = len(chunks)

    if fetch_error is not None:
        stats.error = fetch_error
        # Never prune a source whose adapter raised — empty is not authoritative.
        stats.pruned = False
        stats.prune_skipped_reason = "adapter_error"
        log.warning(
            "ingest_prune_skipped_after_error",
            source_id=adapter.source_id,
            error=fetch_error,
        )
        return stats

    produced_resource_ids = {r.id for r in resources}
    produced_chunk_ids = {c.id for c in chunks}
    existing_chunks = {
        c.id: c
        for c in store.list_chunks(source_id=adapter.source_id, limit=1_000_000)
    }

    # Persistence change detection covers metadata, not only content_sha256.
    # Embedding invalidation uses the embedded-text fingerprint separately.
    chunks_to_write = [
        c for c in chunks if chunk_needs_persist(existing_chunks.get(c.id), c)
    ]
    stats.chunks_written = len(chunks_to_write)
    stats.chunks_unchanged = len(chunks) - len(chunks_to_write)
    stats.resources_written = len(resources)

    # Item-level normalization failures omit ids from the produced set. Pruning
    # against that incomplete manifest would delete previously valid rows.
    allow_prune = prune and item_errors == 0
    if prune and item_errors > 0:
        stats.prune_skipped_reason = "item_errors"
        log.warning(
            "ingest_prune_skipped_after_item_errors",
            source_id=adapter.source_id,
            item_errors=item_errors,
        )

    try:
        with store.transaction():
            if resources:
                store.upsert_resources(resources)
            if chunks_to_write:
                store.upsert_chunks(chunks_to_write)

            if allow_prune:
                stored_resource_ids = store.list_resource_ids(source_id=adapter.source_id)
                stale_resources = sorted(stored_resource_ids - produced_resource_ids)
                # Fingerprints after upserts: anything not produced this run is stale
                # (includes chunks under resources we are about to delete).
                post_write_fps = store.list_chunk_fingerprints(source_id=adapter.source_id)
                stale_chunk_ids = set(post_write_fps) - produced_chunk_ids
                if stale_resources:
                    stats.resources_deleted = store.delete_resources(stale_resources)
                # Cascade may have removed some; delete leftovers on kept resources.
                remaining = store.list_chunk_fingerprints(source_id=adapter.source_id)
                leftover = sorted(set(remaining) - produced_chunk_ids)
                if leftover:
                    store.delete_chunks(leftover)
                stats.chunks_deleted = len(stale_chunk_ids)
                stats.pruned = True
            else:
                stats.pruned = False
    except Exception as exc:  # noqa: BLE001 — source-level write failure
        stats.error = str(exc)
        stats.pruned = False
        stats.prune_skipped_reason = "write_error"
        # Roll back undoes in-txn writes; reset write counters for honesty.
        stats.resources_written = 0
        stats.chunks_written = 0
        stats.resources_deleted = 0
        stats.chunks_deleted = 0
        log.error("ingest_source_write_failed", source_id=adapter.source_id, error=str(exc))
        return stats

    if embed and embedder is not None and chunks:
        emb = sync_embeddings(store, embedder, chunks, batch_size=batch_size)
        stats.embeddings_written = emb.written
        stats.embeddings_reused = emb.reused
        stats.item_errors += emb.errors

    return stats


def _classify_outcome(
    sources: list[SourceIngestStats],
    *,
    store_resource_count: int,
) -> SyncOutcome:
    any_ok = any(s.error is None for s in sources)
    any_err = any(s.error is not None for s in sources)
    any_item_err = any(s.item_errors > 0 for s in sources)

    if not sources or not any_ok or store_resource_count == 0:
        return SyncOutcome.FAILED
    if any_err or any_item_err:
        return SyncOutcome.PARTIAL
    return SyncOutcome.SUCCESS


def _db_path_for_report(cfg: Settings, store: Store) -> str:
    backend = store.capabilities().backend
    if backend == "postgres":
        return cfg.redacted_database_url() or "postgres"
    return str(cfg.resolve_db_path())


def run_ingest(
    sources: list[str] | None = None,
    online: bool = False,
    *,
    settings: Settings | None = None,
    store: Store | None = None,
    embedder: EmbeddingProvider | None = None,
    prune: bool = True,
    embed: bool = True,
) -> IngestReport:
    """Run ingest for selected sources into the configured store.

    Offline (default): load committed fixtures.
    Online: requires ``FRONT_DESIGN_ENABLE_NETWORK_INGEST``; adapters fetch registries.

    One transaction per source. Incremental chunk writes when any persisted field
    changes (not only ``content_sha256``). Pruning is skipped when the source
    adapter errors or any item fails normalization — a partial catalog is not
    authoritative. Embedding sync uses the embedded-text fingerprint separately.
    """
    cfg = settings or get_settings()
    offline = not online
    if online and not cfg.enable_network_ingest:
        raise RuntimeError(
            "Network ingest disabled (FRONT_DESIGN_ENABLE_NETWORK_INGEST=false). "
            "Use offline=True/--offline or enable the flag."
        )

    started = datetime.now(UTC)
    source_ids = list(sources) if sources else list(ADAPTER_SOURCE_IDS)
    for sid in source_ids:
        if sid not in ADAPTER_SOURCE_IDS:
            raise KeyError(f"Unknown source: {sid!r}")

    owns_store = store is None
    db = store if store is not None else create_store(cfg)
    if owns_store:
        db.open()

    active_embedder: EmbeddingProvider | None = None
    embedding_info: dict[str, object] | None = None
    if embed:
        active_embedder = embedder if embedder is not None else create_embedding_provider(cfg)
        embedding_info = describe_provider(active_embedder)

    report_sources: list[SourceIngestStats] = []
    store_count = 0
    backend = db.capabilities().backend
    db_path = _db_path_for_report(cfg, db)
    try:
        for sid in source_ids:
            adapter_cls = get_adapter_class(sid)
            adapter = adapter_cls()
            if hasattr(adapter, "http_timeout"):
                cast(Any, adapter).http_timeout = cfg.http_timeout
            stats = _ingest_one_source(
                adapter,
                db,
                offline=offline,
                prune=prune,
                embed=embed,
                embedder=active_embedder,
                batch_size=cfg.embedding_batch_size,
            )
            report_sources.append(stats)

        store_count = db.count_resources()
        backend = db.capabilities().backend
        db_path = _db_path_for_report(cfg, db)
    finally:
        if owns_store:
            db.close()

    finished = datetime.now(UTC)
    outcome = _classify_outcome(report_sources, store_resource_count=store_count)
    report = IngestReport(
        ok=outcome == SyncOutcome.SUCCESS,
        outcome=outcome,
        mode="online" if online else "offline",
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        db_path=db_path,
        backend=backend,
        sources=report_sources,
        total_resources=sum(s.resources for s in report_sources),
        total_chunks=sum(s.chunks for s in report_sources),
        resources_written=sum(s.resources_written for s in report_sources),
        resources_deleted=sum(s.resources_deleted for s in report_sources),
        chunks_written=sum(s.chunks_written for s in report_sources),
        chunks_unchanged=sum(s.chunks_unchanged for s in report_sources),
        chunks_deleted=sum(s.chunks_deleted for s in report_sources),
        embeddings_written=sum(s.embeddings_written for s in report_sources),
        embeddings_reused=sum(s.embeddings_reused for s in report_sources),
        item_errors=sum(s.item_errors for s in report_sources),
        embedding=embedding_info,
    )

    # Hooks see the final report; failures are logged and swallowed.
    for hook in list(_post_ingest_hooks):
        try:
            hook(report)
        except Exception as exc:  # noqa: BLE001 — never fail ingest on hooks
            log.warning("post_ingest_hook_failed", error=str(exc))

    return report


__all__ = [
    "IngestReport",
    "SourceIngestStats",
    "chunk_needs_persist",
    "clear_post_ingest_hooks",
    "register_post_ingest_hook",
    "run_ingest",
]
