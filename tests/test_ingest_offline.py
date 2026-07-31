"""Offline ingest pipeline tests — SQLite only, no network."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from front_design_mcp.adapters.base import SourceAdapter
from front_design_mcp.config import Settings
from front_design_mcp.ingest.pipeline import (
    clear_post_ingest_hooks,
    register_post_ingest_hook,
    run_ingest,
)
from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.store.base import SyncOutcome
from front_design_mcp.store.sqlite_store import SqliteStore


@pytest.fixture(autouse=True)
def _clear_hooks() -> None:
    clear_post_ingest_hooks()
    yield
    clear_post_ingest_hooks()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        db_path=tmp_path / "test.db",
        enable_network_ingest=False,
        store_backend="sqlite",
        embedding_provider="none",
    )


def test_ingest_offline_populates_store_success(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    report = run_ingest(sources=None, online=False, settings=settings, embed=False)

    assert report.outcome == SyncOutcome.SUCCESS
    assert report.ok is True
    assert report.backend == "sqlite"
    assert report.total_resources > 0
    assert report.total_chunks > 0
    assert report.chunks_written == report.total_chunks
    assert report.chunks_unchanged == 0

    store = SqliteStore(settings.resolve_db_path())
    try:
        assert store.count_resources() == report.total_resources
        assert store.count_chunks() == report.total_chunks
    finally:
        store.close()


def test_ingest_idempotent_second_run_writes_zero_chunks(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = run_ingest(sources=None, online=False, settings=settings, embed=False)
    assert first.chunks_written > 0

    store = SqliteStore(settings.resolve_db_path())
    try:
        resources_n = store.count_resources()
        chunks_n = store.count_chunks()
    finally:
        store.close()

    second = run_ingest(sources=None, online=False, settings=settings, embed=False)
    assert second.outcome == SyncOutcome.SUCCESS
    assert second.chunks_written == 0
    assert second.chunks_unchanged > 0
    assert second.chunks_unchanged == first.total_chunks

    store = SqliteStore(settings.resolve_db_path())
    try:
        assert store.count_resources() == resources_n
        assert store.count_chunks() == chunks_n
    finally:
        store.close()


def test_ingest_rewrites_only_changed_chunk_hash(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db_path = settings.resolve_db_path()
    run_ingest(sources=["curated"], online=False, settings=settings, embed=False)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT id, content_sha256 FROM chunks LIMIT 1").fetchone()
        assert row is not None
        target_id = str(row[0])
        conn.execute(
            "UPDATE chunks SET content_sha256 = ? WHERE id = ?",
            ("mutated-sha-for-test", target_id),
        )
        conn.commit()
    finally:
        conn.close()

    report = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    assert report.chunks_written == 1
    assert report.chunks_unchanged == report.total_chunks - 1

    store = SqliteStore(db_path)
    try:
        chunk = store.get_chunk(target_id)
        assert chunk is not None
        assert chunk.content_sha256 != "mutated-sha-for-test"
    finally:
        store.close()


def test_ingest_prunes_orphan_resource_and_chunk(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db_path = settings.resolve_db_path()
    first = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    assert first.outcome == SyncOutcome.SUCCESS

    store = SqliteStore(db_path)
    try:
        orphan = FrontendResource(
            id="curated:orphan-test-resource",
            kind=ResourceKind.PATTERN,
            name="Orphan",
            description="Should be pruned",
            source=SourceRef(
                source_id="curated",
                source_name="Curated",
                homepage_url="https://example.com",
                registry_url=None,
                attribution="test",
            ),
            last_indexed_at=datetime.now(UTC),
        )
        orphan_chunk = DocumentationChunk(
            id="curated:orphan-test-chunk",
            resource_id=orphan.id,
            title="Orphan chunk",
            content="gone",
            content_sha256="orphan-sha",
            last_indexed_at=datetime.now(UTC),
        )
        store.upsert_resources([orphan])
        store.upsert_chunks([orphan_chunk])
        assert store.get_resource(orphan.id) is not None
        assert store.get_chunk(orphan_chunk.id) is not None
    finally:
        store.close()

    report = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    assert report.resources_deleted >= 1
    assert report.chunks_deleted >= 1
    curated = next(s for s in report.sources if s.source_id == "curated")
    assert curated.pruned is True

    store = SqliteStore(db_path)
    try:
        assert store.get_resource("curated:orphan-test-resource") is None
        assert store.get_chunk("curated:orphan-test-chunk") is None
    finally:
        store.close()


def test_ingest_no_prune_when_adapter_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    db_path = settings.resolve_db_path()
    first = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    assert first.total_resources > 0

    store = SqliteStore(db_path)
    try:
        before_resources = store.count_resources(source_id="curated")
        before_chunks = store.count_chunks(source_id="curated")
        sample_ids = store.list_resource_ids(source_id="curated")
    finally:
        store.close()

    def _boom(self: SourceAdapter, *, offline: bool = True) -> list[dict[str, Any]]:
        raise RuntimeError("simulated fetch failure")

    monkeypatch.setattr(
        "front_design_mcp.adapters.curated.CuratedAdapter.fetch_catalog",
        _boom,
    )

    report = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    curated = report.sources[0]
    assert curated.error is not None
    assert curated.pruned is False
    # Single-source error → every requested source errored → FAILED.
    assert report.outcome == SyncOutcome.FAILED

    store = SqliteStore(db_path)
    try:
        assert store.count_resources(source_id="curated") == before_resources
        assert store.count_chunks(source_id="curated") == before_chunks
        assert store.list_resource_ids(source_id="curated") == sample_ids
    finally:
        store.close()


def test_ingest_transaction_rollback_on_write_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    db_path = settings.resolve_db_path()
    # Seed a different source so the store is non-empty.
    run_ingest(sources=["gsap"], online=False, settings=settings, embed=False)

    store = SqliteStore(db_path)
    try:
        before_curated_r = store.count_resources(source_id="curated")
        before_curated_c = store.count_chunks(source_id="curated")
        assert before_curated_r == 0

        def _fail_chunks(chunks: Any) -> None:
            raise RuntimeError("forced upsert_chunks failure")

        monkeypatch.setattr(store, "upsert_chunks", _fail_chunks)

        report = run_ingest(
            sources=["curated"],
            online=False,
            settings=settings,
            store=store,
            embed=False,
        )
        assert report.sources[0].error is not None
        assert "forced upsert_chunks failure" in (report.sources[0].error or "")
        assert store.count_resources(source_id="curated") == before_curated_r
        assert store.count_chunks(source_id="curated") == before_curated_c
    finally:
        store.close()


def test_ingest_report_to_dict_json_serialisable_no_password(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    report = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    payload = report.to_dict()
    dumped = json.dumps(payload)
    assert "postgresql://" not in dumped
    assert payload["outcome"] == "success"
    assert payload["ok"] is True
    assert "chunks_written" in payload
    assert "embeddings_written" in payload


def test_post_ingest_hooks_fire_and_raising_hook_is_swallowed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    seen: list[str] = []

    def ok_hook(report: Any) -> None:
        seen.append(report.outcome.value)

    def bad_hook(report: Any) -> None:
        seen.append("bad")
        raise RuntimeError("hook boom")

    register_post_ingest_hook(bad_hook)
    register_post_ingest_hook(ok_hook)

    report = run_ingest(sources=["curated"], online=False, settings=settings, embed=False)
    assert report.outcome == SyncOutcome.SUCCESS
    assert "bad" in seen
    assert SyncOutcome.SUCCESS.value in seen
