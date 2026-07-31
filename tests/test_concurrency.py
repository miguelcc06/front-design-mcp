"""Basic thread-safety tests for SearchService, SqliteStore, and runtime."""

from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.search.service import SearchService
from front_design_mcp.store.sqlite_store import SqliteStore
from front_design_mcp.tools.runtime import ensure_ready, reset_runtime


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _seed(store: SqliteStore, n: int = 20) -> None:
    resources = [
        FrontendResource(
            id=f"r-{i}",
            kind=ResourceKind.LIBRARY,
            name=f"Resource {i}",
            description=f"accordion widget library {i}",
            source=SourceRef(source_id="src", source_name="src"),
            license=LicenseInfo(name="MIT", spdx_id="MIT"),
            tags=["ui"],
            last_indexed_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for i in range(n)
    ]
    chunks = [
        DocumentationChunk(
            id=f"c-{i}",
            resource_id=f"r-{i}",
            title=f"Accordion docs {i}",
            content=f"How to build an accordion component number {i} with keyboard support.",
            content_sha256=_sha(f"body-{i}"),
            tags=["docs"],
            last_indexed_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        for i in range(n)
    ]
    store.upsert_resources(resources)
    store.upsert_chunks(chunks)


def _run_pool(fn: Any, n: int = 8) -> list[Any]:
    errors: list[BaseException] = []
    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = [pool.submit(fn, i) for i in range(n)]
        for fut in as_completed(futures):
            try:
                results.append(fut.result())
            except BaseException as exc:  # noqa: BLE001 — collect all thread errors
                errors.append(exc)
    if errors:
        raise AssertionError(
            f"{len(errors)} thread(s) failed: " + "; ".join(repr(e) for e in errors)
        )
    return results


def test_concurrent_search_identical_results(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "search.db")
    try:
        _seed(store)
        svc = SearchService(store, search_mode="lexical")
        svc.rebuild()
        query = "accordion"

        def worker(_i: int) -> list[str]:
            hits = svc.search(query, limit=5)
            return [h.chunk.id if h.chunk else "" for h in hits]

        results = _run_pool(worker, n=8)
        assert len(results) == 8
        first = results[0]
        assert first  # non-empty
        for r in results[1:]:
            assert r == first
    finally:
        store.close()


def test_concurrent_reads_during_batched_writes(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "rw.db")
    try:
        _seed(store, n=10)
        stop = threading.Event()
        write_errors: list[BaseException] = []

        def writer() -> None:
            try:
                for batch in range(5):
                    with store.transaction():
                        resources = [
                            FrontendResource(
                                id=f"w-{batch}-{i}",
                                kind=ResourceKind.COMPONENT,
                                name=f"Write {batch}-{i}",
                                description="concurrent write",
                                source=SourceRef(source_id="w", source_name="w"),
                                tags=["w"],
                            )
                            for i in range(8)
                        ]
                        store.upsert_resources(resources)
                        store.upsert_chunks(
                            [
                                DocumentationChunk(
                                    id=f"wc-{batch}-{i}",
                                    resource_id=f"w-{batch}-{i}",
                                    title=f"W {batch}-{i}",
                                    content="written under transaction",
                                    content_sha256=_sha(f"w-{batch}-{i}"),
                                )
                                for i in range(8)
                            ]
                        )
            except BaseException as exc:  # noqa: BLE001
                write_errors.append(exc)
            finally:
                stop.set()

        def reader(_i: int) -> tuple[int, int]:
            seen_partial = 0
            loops = 0
            while not stop.is_set() or loops < 2:
                loops += 1
                # Must not raise sqlite3.ProgrammingError
                store.get_resource("r-0")
                store.list_chunks(limit=50)
                n = store.count_chunks()
                # Snapshot one batch under a single lock hold so we observe
                # transaction atomicity, not a torn multi-call read.
                for batch in range(5):
                    with store._lock:
                        present = sum(
                            1
                            for i in range(8)
                            if store._conn is not None
                            and store._conn.execute(
                                "SELECT 1 FROM resources WHERE id = ?",
                                (f"w-{batch}-{i}",),
                            ).fetchone()
                        )
                    if 0 < present < 8:
                        seen_partial += 1
                if loops > 200:
                    break
            return n, seen_partial

        write_thread = threading.Thread(target=writer)
        write_thread.start()
        read_results = _run_pool(reader, n=8)
        write_thread.join(timeout=30)
        assert not write_thread.is_alive()
        if write_errors:
            raise AssertionError(f"writer failed: {write_errors!r}")
        assert all(partial == 0 for _, partial in read_results)
        assert store.count_resources() >= 10 + 5 * 8
    finally:
        store.close()


def test_concurrent_ensure_ready_singleton(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reset_runtime()
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(tmp_path / "rt.db"))
    monkeypatch.setenv("FRONT_DESIGN_ENABLE_NETWORK_INGEST", "false")
    monkeypatch.setenv("FRONT_DESIGN_EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("FRONT_DESIGN_STORE_BACKEND", "sqlite")

    ingest_calls = {"n": 0}
    lock = threading.Lock()

    # Count ingest by wrapping run_ingest
    from front_design_mcp.tools import runtime as runtime_mod

    original_ingest = runtime_mod.run_ingest

    def counting_ingest(*args: Any, **kwargs: Any) -> Any:
        with lock:
            ingest_calls["n"] += 1
        return original_ingest(*args, **kwargs)

    monkeypatch.setattr(runtime_mod, "run_ingest", counting_ingest)

    def worker(_i: int) -> tuple[int, int]:
        store, search = ensure_ready()
        return id(store), id(search)

    try:
        results = _run_pool(worker, n=8)
        store_ids = {r[0] for r in results}
        search_ids = {r[1] for r in results}
        assert len(store_ids) == 1
        assert len(search_ids) == 1
        assert ingest_calls["n"] == 1
    finally:
        reset_runtime()
