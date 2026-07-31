"""Offline ingest → store → BM25 search integration test."""

from __future__ import annotations

from pathlib import Path

from front_design_mcp.config import Settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.search.service import SearchService
from front_design_mcp.store.sqlite_store import SqliteStore


def test_ingest_offline_populates_store_and_bm25(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    settings = Settings(data_dir=tmp_path, db_path=db_path, enable_network_ingest=False)

    report = run_ingest(sources=None, online=False, settings=settings)
    assert report.ok
    assert report.total_resources > 0
    assert report.total_chunks > 0

    store = SqliteStore(db_path)
    resources = store.list_resources()
    chunks = store.list_chunks()
    assert len(resources) > 0
    assert len(chunks) > 0
    assert len(resources) == report.total_resources

    service = SearchService(store)
    service.rebuild()

    hits = []
    for query in ("hero", "accordion", "scroll"):
        hits = service.search(query, limit=5)
        if hits:
            break
    assert hits, "Expected BM25 hit for hero|accordion|scroll"
    assert hits[0].score > 0
    assert hits[0].chunk is not None
    assert hits[0].citation is not None

    store.close()
