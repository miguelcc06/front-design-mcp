"""Embedding sync + ingest embedding cache tests."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

from front_design_mcp.config import Settings
from front_design_mcp.embeddings.base import (
    EmbeddingError,
    EmbeddingProvider,
    NullEmbeddingProvider,
)
from front_design_mcp.ingest.embedding_sync import sync_embeddings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.store.base import (
    EmbeddingModelRef,
    EmbeddingRecord,
    Store,
    StoreCapabilities,
)
from front_design_mcp.store.factory import create_store
from front_design_mcp.store.sqlite_store import SqliteStore

_EMBED_DIM = 8
_REPO_ROOT = Path(__file__).resolve().parents[1]
_TEST_DSN = os.environ.get("FRONT_DESIGN_TEST_DATABASE_URL", "").strip()


def _postgres_reachable(dsn: str) -> bool:
    if not dsn:
        return False
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


class FakeEmbeddingProvider(EmbeddingProvider):
    """Deterministic in-process vectors (dim 8) derived from a hash of the text."""

    name = "fake"

    def __init__(
        self,
        *,
        dim: int = _EMBED_DIM,
        pipeline_version: int = 1,
        fail_batches: set[int] | None = None,
    ) -> None:
        self._dim = dim
        self._pipeline_version = pipeline_version
        self._fail_batches = fail_batches or set()
        self._batch_calls = 0

    @property
    def enabled(self) -> bool:
        return True

    @property
    def model_ref(self) -> EmbeddingModelRef:
        return EmbeddingModelRef(
            provider="fake",
            model="fake-hash-v1",
            dim=self._dim,
            pipeline_version=self._pipeline_version,
        )

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        idx = self._batch_calls
        self._batch_calls += 1
        if idx in self._fail_batches:
            raise EmbeddingError("simulated embedding batch failure")
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def _vec(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [((digest[i % len(digest)] / 255.0) * 2.0) - 1.0 for i in range(self._dim)]


def _enable_vector_search(store: SqliteStore) -> None:
    """SQLite persists vectors but reports vector_search=False; force True for cache tests."""

    def _caps() -> StoreCapabilities:
        return StoreCapabilities(
            backend="sqlite",
            lexical_search=True,
            vector_search=True,
            embedding_dim=_EMBED_DIM,
        )

    store.capabilities = _caps  # type: ignore[method-assign]  # test double


def _resource() -> FrontendResource:
    return FrontendResource(
        id="res-1",
        kind=ResourceKind.LIBRARY,
        name="Res",
        description="d",
        source=SourceRef(source_id="test", source_name="Test"),
        last_indexed_at=datetime.now(UTC),
    )


def _chunk(cid: str, *, title: str = "Title", content: str = "Body") -> DocumentationChunk:
    text = f"{title}\n\n{content}"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return DocumentationChunk(
        id=cid,
        resource_id="res-1",
        title=title,
        content=content,
        content_sha256=sha,
    )


def test_sync_embeddings_null_provider_writes_nothing(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "null.db")
    try:
        _enable_vector_search(store)
        stats = sync_embeddings(store, NullEmbeddingProvider(), [_chunk("c1")])
        assert stats.written == 0
        assert stats.reused == 0
        assert stats.skipped == 0
        assert stats.errors == 0
        assert store.count_embeddings() == 0
    finally:
        store.close()


def test_sync_embeddings_skips_when_no_vector_search(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "novec.db")
    try:
        assert store.capabilities().vector_search is False
        chunks = [_chunk("c1"), _chunk("c2", content="other")]
        stats = sync_embeddings(store, FakeEmbeddingProvider(), chunks)
        assert stats.skipped == 2
        assert stats.written == 0
        assert store.count_embeddings() == 0
    finally:
        store.close()


def test_embedding_cache_reuse_and_invalidation(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "cache.db")
    try:
        _enable_vector_search(store)
        chunks = [
            _chunk("c1", title="A", content="alpha"),
            _chunk("c2", title="B", content="beta"),
            _chunk("c3", title="C", content="gamma"),
        ]
        store.upsert_resources([_resource()])
        store.upsert_chunks(chunks)

        provider = FakeEmbeddingProvider()
        first = sync_embeddings(store, provider, chunks, batch_size=2)
        assert first.written == 3
        assert first.reused == 0
        assert store.count_embeddings() == 3

        second = sync_embeddings(store, provider, chunks, batch_size=2)
        assert second.written == 0
        assert second.reused == 3

        changed = _chunk("c2", title="B", content="beta-CHANGED")
        store.upsert_chunks([changed])
        updated = [chunks[0], changed, chunks[2]]
        third = sync_embeddings(store, provider, updated, batch_size=2)
        assert third.written == 1
        assert third.reused == 2

        bumped = FakeEmbeddingProvider(pipeline_version=2)
        fourth = sync_embeddings(store, bumped, updated, batch_size=2)
        assert fourth.written == 3
        assert fourth.reused == 0
    finally:
        store.close()


def test_sync_embeddings_batch_error_continues(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "err.db")
    try:
        _enable_vector_search(store)
        store.upsert_resources([_resource()])
        chunks = [_chunk(f"c{i}", content=f"body-{i}") for i in range(4)]
        store.upsert_chunks(chunks)

        provider = FakeEmbeddingProvider(fail_batches={0})
        stats = sync_embeddings(store, provider, chunks, batch_size=2)
        assert stats.errors == 2
        assert stats.written == 2
        assert store.count_embeddings() == 2
    finally:
        store.close()


def test_sync_embeddings_dimension_mismatch_propagates(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "dim.db")
    try:
        _enable_vector_search(store)
        store.upsert_resources([_resource()])
        chunk = _chunk("c1")
        store.upsert_chunks([chunk])

        store.upsert_embeddings(
            [
                EmbeddingRecord(
                    chunk_id=chunk.id,
                    vector=[0.0] * _EMBED_DIM,
                    content_sha256="stale",
                    model=EmbeddingModelRef(
                        provider="fake", model="fake-hash-v1", dim=_EMBED_DIM
                    ),
                )
            ]
        )

        bad = FakeEmbeddingProvider(dim=4)
        with pytest.raises(ValueError, match="dimension"):
            sync_embeddings(store, bad, [chunk])
    finally:
        store.close()


# ---------------------------------------------------------------------------
# PostgreSQL integration (skipped without FRONT_DESIGN_TEST_DATABASE_URL)
# ---------------------------------------------------------------------------


def _admin_dsn(dsn: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path="/postgres"))


def _scratch_dsn(dsn: str, db_name: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{db_name}"))


@pytest.fixture(scope="module")
def ingest_scratch_database_url() -> Iterator[str]:
    """Create a dedicated DB, migrate with dim=8, drop on teardown."""
    if not _postgres_reachable(_TEST_DSN):
        pytest.skip("FRONT_DESIGN_TEST_DATABASE_URL unset or PostgreSQL unreachable")

    import psycopg
    from alembic import command
    from alembic.config import Config

    assert _TEST_DSN
    db_name = f"front_design_ingest_{os.getpid()}"
    admin = _admin_dsn(_TEST_DSN)
    scratch = _scratch_dsn(_TEST_DSN, db_name)

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')

    prev_url = os.environ.get("FRONT_DESIGN_DATABASE_URL")
    prev_dim = os.environ.get("FRONT_DESIGN_EMBEDDING_DIMENSIONS")
    os.environ["FRONT_DESIGN_DATABASE_URL"] = scratch
    os.environ["FRONT_DESIGN_EMBEDDING_DIMENSIONS"] = str(_EMBED_DIM)
    try:
        cfg = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")
        yield scratch
    finally:
        if prev_url is None:
            os.environ.pop("FRONT_DESIGN_DATABASE_URL", None)
        else:
            os.environ["FRONT_DESIGN_DATABASE_URL"] = prev_url
        if prev_dim is None:
            os.environ.pop("FRONT_DESIGN_EMBEDDING_DIMENSIONS", None)
        else:
            os.environ["FRONT_DESIGN_EMBEDDING_DIMENSIONS"] = prev_dim
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


@pytest.mark.postgres
@pytest.mark.skipif(
    not _postgres_reachable(_TEST_DSN),
    reason="FRONT_DESIGN_TEST_DATABASE_URL unset or PostgreSQL unreachable",
)
def test_postgres_offline_ingest_with_embeddings(
    ingest_scratch_database_url: str,
) -> None:
    import psycopg

    with psycopg.connect(ingest_scratch_database_url, autocommit=True) as conn:
        conn.execute("TRUNCATE embeddings, chunks, resources RESTART IDENTITY CASCADE")

    settings = Settings(
        store_backend="postgres",
        database_url=ingest_scratch_database_url,
        embedding_provider="none",
        embedding_dimensions=_EMBED_DIM,
        enable_network_ingest=False,
    )
    provider = FakeEmbeddingProvider(dim=_EMBED_DIM)
    store: Store = create_store(settings)
    try:
        first = run_ingest(
            sources=["curated"],
            online=False,
            settings=settings,
            store=store,
            embedder=provider,
            embed=True,
            prune=True,
        )
        assert first.outcome.value == "success"
        assert store.count_resources(source_id="curated") > 0
        assert store.count_chunks(source_id="curated") > 0
        assert first.embeddings_written > 0
        assert store.count_embeddings() == first.embeddings_written

        second = run_ingest(
            sources=["curated"],
            online=False,
            settings=settings,
            store=store,
            embedder=provider,
            embed=True,
            prune=True,
        )
        assert second.embeddings_written == 0
        assert second.embeddings_reused == first.embeddings_written
        assert second.chunks_written == 0
    finally:
        store.close()
