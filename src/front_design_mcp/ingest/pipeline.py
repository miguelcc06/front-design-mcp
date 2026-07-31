"""Ingest pipeline: adapters → SqliteStore (+ BM25 rebuild at search time)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from front_design_mcp.adapters import ADAPTER_SOURCE_IDS, get_adapter_class
from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.adapters.common import make_chunks_for_resource
from front_design_mcp.config import Settings, get_settings
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import DocumentationChunk, FrontendResource
from front_design_mcp.store.sqlite_store import SqliteStore

log = get_logger("ingest.pipeline")


@dataclass
class SourceIngestStats:
    source_id: str
    resources: int = 0
    chunks: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IngestReport:
    ok: bool
    mode: str
    started_at: str
    finished_at: str
    db_path: str
    sources: list[SourceIngestStats] = field(default_factory=list)
    total_resources: int = 0
    total_chunks: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "db_path": self.db_path,
            "sources": [s.to_dict() for s in self.sources],
            "total_resources": self.total_resources,
            "total_chunks": self.total_chunks,
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


def _ingest_one(
    adapter: SourceAdapter,
    store: SqliteStore,
    *,
    offline: bool,
) -> SourceIngestStats:
    stats = SourceIngestStats(source_id=adapter.source_id)
    try:
        catalog = adapter.fetch_catalog(offline=offline)
        for raw in catalog:
            try:
                resource = adapter.normalize(raw)
                store.upsert_resource(resource)
                stats.resources += 1
                for chunk in _adapter_chunks(adapter, resource):
                    store.upsert_chunk(chunk)
                    stats.chunks += 1
            except Exception as item_exc:  # noqa: BLE001 — isolate per-item failures
                log.warning(
                    "ingest_item_failed",
                    source_id=adapter.source_id,
                    error=str(item_exc),
                )
    except Exception as exc:  # noqa: BLE001 — isolate per-adapter failures
        stats.error = str(exc)
        log.error("ingest_source_failed", source_id=adapter.source_id, error=str(exc))
    return stats


def run_ingest(
    sources: list[str] | None = None,
    online: bool = False,
    *,
    settings: Settings | None = None,
    store: SqliteStore | None = None,
) -> IngestReport:
    """Run ingest for selected sources into SQLite.

    Offline (default): load committed fixtures.
    Online: requires ``FRONT_DESIGN_ENABLE_NETWORK_INGEST``; adapters fetch registries.
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

    db_path = cfg.resolve_db_path()
    owns_store = store is None
    db = store or SqliteStore(db_path)
    if owns_store:
        db.open()

    report_sources: list[SourceIngestStats] = []
    try:
        for sid in source_ids:
            adapter_cls = get_adapter_class(sid)
            adapter = adapter_cls()
            # Allow adapters to read timeout from settings when present
            if hasattr(adapter, "http_timeout"):
                adapter.http_timeout = cfg.http_timeout  # type: ignore[attr-defined]
            stats = _ingest_one(adapter, db, offline=offline)
            report_sources.append(stats)
    finally:
        if owns_store:
            db.close()

    finished = datetime.now(UTC)
    total_r = sum(s.resources for s in report_sources)
    total_c = sum(s.chunks for s in report_sources)
    ok = all(s.error is None for s in report_sources) and total_r > 0
    return IngestReport(
        ok=ok,
        mode="online" if online else "offline",
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        db_path=str(db_path),
        sources=report_sources,
        total_resources=total_r,
        total_chunks=total_c,
    )
