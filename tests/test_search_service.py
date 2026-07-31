"""Tests for SearchService mode resolution, degradation, filters, and hybrid path."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from front_design_mcp.embeddings.base import (
    EmbeddingError,
    EmbeddingModelRef,
    EmbeddingProvider,
    NullEmbeddingProvider,
)
from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    RetrievalMode,
    SourceRef,
)
from front_design_mcp.search.base import RankedChunk, SearchFilters
from front_design_mcp.search.service import SearchService
from front_design_mcp.store.base import (
    EmbeddingMeta,
    EmbeddingRecord,
    Store,
    StoreCapabilities,
)
from front_design_mcp.store.sqlite_store import SqliteStore


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _resource(
    rid: str,
    *,
    name: str | None = None,
    source_id: str = "src",
    kind: ResourceKind = ResourceKind.LIBRARY,
    tags: list[str] | None = None,
    frameworks: list[str] | None = None,
) -> FrontendResource:
    return FrontendResource(
        id=rid,
        kind=kind,
        name=name or rid,
        description=f"Description for {rid}",
        source=SourceRef(source_id=source_id, source_name=source_id),
        license=LicenseInfo(name="MIT", spdx_id="MIT"),
        supported_frameworks=frameworks or [],
        tags=tags or [],
        capabilities=["docs"],
        last_indexed_at=datetime(2024, 1, 1, tzinfo=UTC),
        raw_refs={"k": "v"},
    )


def _chunk(
    cid: str,
    resource_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
) -> DocumentationChunk:
    body = content or f"content about {cid}"
    return DocumentationChunk(
        id=cid,
        resource_id=resource_id,
        title=title or cid,
        content=body,
        source_url=f"https://example.com/{cid}",
        license=LicenseInfo(name="MIT", spdx_id="MIT"),
        tags=tags or [],
        last_indexed_at=datetime(2024, 1, 1, tzinfo=UTC),
        content_sha256=_sha(body),
    )


class FakeEmbedder(EmbeddingProvider):
    name = "fake"

    def __init__(
        self,
        *,
        enabled: bool = True,
        dim: int = 4,
        fail: bool = False,
        vector: list[float] | None = None,
    ) -> None:
        self._enabled = enabled
        self._dim = dim
        self._fail = fail
        self._vector = vector or [0.1] * dim
        self.query_calls = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def model_ref(self) -> EmbeddingModelRef:
        return EmbeddingModelRef(provider="fake", model="fake-v1", dim=self._dim)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [list(self._vector) for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls += 1
        if self._fail:
            raise EmbeddingError("simulated embedding failure")
        return list(self._vector)


class MemoryStore(Store):
    """Minimal in-memory Store; optionally implements lexical/vector protocols."""

    backend = "memory"

    def __init__(
        self,
        *,
        vector_search: bool = False,
        lexical_native: bool = True,
        resources: list[FrontendResource] | None = None,
        chunks: list[DocumentationChunk] | None = None,
        lexical_results: list[RankedChunk] | None = None,
        vector_results: list[RankedChunk] | None = None,
        vector_error: Exception | None = None,
    ) -> None:
        self._vector_search = vector_search
        self._lexical_native = lexical_native
        self._resources = {r.id: r for r in (resources or [])}
        self._chunks = {c.id: c for c in (chunks or [])}
        self._lexical_results = lexical_results
        self._vector_results = vector_results if vector_results is not None else []
        self._vector_error = vector_error
        # Distinct embedding identities the store claims to hold, in the shape
        # stats() reports them. Empty means "nothing embedded yet".
        self.stored_embedding_models: list[dict[str, Any]] = []
        self.lexical_limits: list[int] = []
        self.vector_limits: list[int] = []
        self.lexical_calls = 0
        self.vector_calls = 0
        self.last_vector_model: EmbeddingModelRef | None = None

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    @contextmanager
    def transaction(self) -> Iterator[None]:
        yield

    def capabilities(self) -> StoreCapabilities:
        return StoreCapabilities(
            backend="memory",
            lexical_search=True,
            vector_search=self._vector_search,
        )

    def upsert_resources(self, resources: Sequence[FrontendResource]) -> None:
        for r in resources:
            self._resources[r.id] = r

    def get_resource(self, resource_id: str) -> FrontendResource | None:
        return self._resources.get(resource_id)

    def list_resources(
        self,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[FrontendResource]:
        items = list(self._resources.values())
        if source_id:
            items = [r for r in items if r.source.source_id == source_id]
        if kind:
            items = [r for r in items if r.kind.value == kind]
        return items[offset : offset + limit]

    def list_resource_ids(self, *, source_id: str | None = None) -> set[str]:
        return {r.id for r in self.list_resources(source_id=source_id)}

    def delete_resources(self, resource_ids: Sequence[str]) -> int:
        n = 0
        for rid in resource_ids:
            if rid in self._resources:
                del self._resources[rid]
                n += 1
        return n

    def count_resources(self, *, source_id: str | None = None) -> int:
        return len(self.list_resources(source_id=source_id))

    def upsert_chunks(self, chunks: Sequence[DocumentationChunk]) -> None:
        for c in chunks:
            self._chunks[c.id] = c

    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        return self._chunks.get(chunk_id)

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[DocumentationChunk]:
        return [self._chunks[c] for c in chunk_ids if c in self._chunks]

    def list_chunks(
        self,
        *,
        resource_id: str | None = None,
        source_id: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[DocumentationChunk]:
        items = list(self._chunks.values())
        if resource_id:
            items = [c for c in items if c.resource_id == resource_id]
        if source_id:
            allowed = {
                r.id for r in self._resources.values() if r.source.source_id == source_id
            }
            items = [c for c in items if c.resource_id in allowed]
        return items[offset : offset + limit]

    def list_chunk_fingerprints(self, *, source_id: str | None = None) -> dict[str, str]:
        return {c.id: c.content_sha256 for c in self.list_chunks(source_id=source_id)}

    def delete_chunks(self, chunk_ids: Sequence[str]) -> int:
        n = 0
        for cid in chunk_ids:
            if cid in self._chunks:
                del self._chunks[cid]
                n += 1
        return n

    def count_chunks(self, *, source_id: str | None = None) -> int:
        return len(self.list_chunks(source_id=source_id, limit=1_000_000))

    def upsert_embeddings(self, records: Sequence[EmbeddingRecord]) -> None:
        return None

    def get_embedding_metadata(
        self, chunk_ids: Sequence[str] | None = None
    ) -> dict[str, EmbeddingMeta]:
        return {}

    def delete_embeddings(
        self,
        *,
        chunk_ids: Sequence[str] | None = None,
        not_matching: EmbeddingModelRef | None = None,
    ) -> int:
        return 0

    def count_embeddings(self, *, model: EmbeddingModelRef | None = None) -> int:
        return 0

    def stats(self) -> dict[str, Any]:
        return {"backend": "memory", "embedding_models": self.stored_embedding_models}

    # Protocol methods — presence makes isinstance(..., LexicalSearcher) True.
    def search_lexical(
        self, query: str, *, filters: SearchFilters, limit: int
    ) -> list[RankedChunk]:
        self.lexical_calls += 1
        self.lexical_limits.append(limit)
        if self._lexical_results is not None:
            return list(self._lexical_results)[:limit]
        # Default: rank all chunks by simple presence of query tokens.
        out: list[RankedChunk] = []
        for i, chunk in enumerate(self._chunks.values(), start=1):
            if query.lower() in (chunk.title + chunk.content).lower():
                out.append(RankedChunk(chunk_id=chunk.id, score=float(10 - i), rank=i))
        return out[:limit]

    def search_vector(
        self,
        embedding: Sequence[float],
        *,
        filters: SearchFilters,
        limit: int,
        model: EmbeddingModelRef,
    ) -> list[RankedChunk]:
        self.vector_calls += 1
        self.vector_limits.append(limit)
        self.last_vector_model = model
        if self._vector_error is not None:
            raise self._vector_error
        return list(self._vector_results)[:limit]


# ---------------------------------------------------------------------------
# Mode resolution matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("search_mode", "vector_search", "provider_enabled", "expected"),
    [
        ("auto", False, False, RetrievalMode.LEXICAL),
        ("auto", False, True, RetrievalMode.LEXICAL),
        ("auto", True, False, RetrievalMode.LEXICAL),
        ("auto", True, True, RetrievalMode.HYBRID),
        ("lexical", False, False, RetrievalMode.LEXICAL),
        ("lexical", False, True, RetrievalMode.LEXICAL),
        ("lexical", True, False, RetrievalMode.LEXICAL),
        ("lexical", True, True, RetrievalMode.LEXICAL),
        ("vector", False, False, RetrievalMode.LEXICAL),
        ("vector", False, True, RetrievalMode.LEXICAL),
        ("vector", True, False, RetrievalMode.LEXICAL),
        ("vector", True, True, RetrievalMode.VECTOR),
        ("hybrid", False, False, RetrievalMode.LEXICAL),
        ("hybrid", False, True, RetrievalMode.LEXICAL),
        ("hybrid", True, False, RetrievalMode.LEXICAL),
        ("hybrid", True, True, RetrievalMode.HYBRID),
    ],
)
def test_resolve_mode_matrix(
    search_mode: str,
    vector_search: bool,
    provider_enabled: bool,
    expected: RetrievalMode,
) -> None:
    store = MemoryStore(vector_search=vector_search)
    svc = SearchService(
        store,
        embedder=FakeEmbedder(enabled=provider_enabled),
        search_mode=search_mode,
    )
    assert svc.resolve_mode() == expected


def test_auto_without_vector_capability_is_lexical() -> None:
    store = MemoryStore(vector_search=False)
    svc = SearchService(store, embedder=FakeEmbedder(enabled=True), search_mode="auto")
    assert svc.resolve_mode() == RetrievalMode.LEXICAL


# ---------------------------------------------------------------------------
# Degradation paths
# ---------------------------------------------------------------------------


def test_hybrid_degrades_when_vector_returns_empty() -> None:
    r = _resource("r1")
    c = _chunk("c1", "r1", content="accordion component docs")
    store = MemoryStore(
        vector_search=True,
        resources=[r],
        chunks=[c],
        lexical_results=[RankedChunk(chunk_id="c1", score=2.0, rank=1)],
        vector_results=[],
    )
    svc = SearchService(
        store, embedder=FakeEmbedder(enabled=True), search_mode="hybrid"
    )
    outcome = svc.search_detailed("accordion", limit=5)
    assert outcome.mode == "lexical"
    assert outcome.degraded is True
    assert any("vector" in n.lower() or "embedding" in n.lower() for n in outcome.notes)
    assert len(outcome.hits) >= 1


def test_provider_failure_degrades_to_lexical() -> None:
    r = _resource("r1")
    c = _chunk("c1", "r1", content="button component")
    store = MemoryStore(
        vector_search=True,
        resources=[r],
        chunks=[c],
        lexical_results=[RankedChunk(chunk_id="c1", score=3.0, rank=1)],
    )
    svc = SearchService(
        store,
        embedder=FakeEmbedder(enabled=True, fail=True),
        search_mode="hybrid",
    )
    outcome = svc.search_detailed("button", limit=5)
    assert outcome.mode == "lexical"
    assert outcome.degraded is True
    assert any("EmbeddingError" in n for n in outcome.notes)
    assert len(outcome.hits) == 1
    assert outcome.hits[0].chunk is not None
    assert outcome.hits[0].chunk.id == "c1"


def test_dimension_mismatch_value_error_degrades() -> None:
    r = _resource("r1")
    c = _chunk("c1", "r1", content="modal dialog")
    store = MemoryStore(
        vector_search=True,
        resources=[r],
        chunks=[c],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.5, rank=1)],
        vector_error=ValueError("dimension mismatch: expected 384 got 8"),
    )
    svc = SearchService(
        store, embedder=FakeEmbedder(enabled=True), search_mode="hybrid"
    )
    outcome = svc.search_detailed("modal", limit=5)
    assert outcome.mode == "lexical"
    assert outcome.degraded is True
    assert any("dimension mismatch" in n for n in outcome.notes)
    assert len(outcome.hits) == 1


def test_empty_query_returns_none_mode() -> None:
    store = MemoryStore(resources=[_resource("r1")], chunks=[_chunk("c1", "r1")])
    svc = SearchService(store, search_mode="lexical")
    outcome = svc.search_detailed("   ", limit=5)
    assert outcome.mode == "none"
    assert outcome.hits == []
    assert any("Empty query" in n for n in outcome.notes)
    assert store.lexical_calls == 0


def test_filters_matching_nothing_distinct_from_no_hits() -> None:
    store = MemoryStore(
        resources=[_resource("r1", frameworks=["react"])],
        chunks=[_chunk("c1", "r1", content="react hook")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
    )
    svc = SearchService(store, search_mode="lexical")
    # Framework no resource supports → excludes_everything
    empty_filter = svc.search_detailed(
        "hook", limit=5, framework="definitely-not-a-real-framework-xyz"
    )
    assert empty_filter.mode == "none"
    assert empty_filter.hits == []
    assert any("no resources" in n.lower() or "no chunk" in n.lower() for n in empty_filter.notes)
    assert store.lexical_calls == 0

    # Same store, no framework filter, but force empty lexical results
    store._lexical_results = []
    no_match = svc.search_detailed("zzzznonexistenttoken", limit=5)
    assert no_match.mode == "lexical"
    assert no_match.hits == []
    # Distinguishable: empty-filter uses mode none + resource note; no-match is lexical
    assert empty_filter.mode != no_match.mode
    assert any("Filters matched no resources" in n for n in empty_filter.notes)


# ---------------------------------------------------------------------------
# Filters before ranking (real SqliteStore regression)
# ---------------------------------------------------------------------------


def test_filters_applied_before_ranking_on_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "filter.db"
    store = SqliteStore(db)
    try:
        # Many high-BM25 chunks on filtered-out source (noise) that all mention
        # the query term repeatedly; few eligible chunks that mention it once.
        noise_resources = [
            _resource(f"noise-{i}", name=f"Noise {i}", source_id="noise-src")
            for i in range(12)
        ]
        keep = _resource("keep-1", name="Keep One", source_id="keep-src", tags=["ui"])
        store.upsert_resources([*noise_resources, keep])

        noise_chunks = [
            _chunk(
                f"noise-chunk-{i}",
                f"noise-{i}",
                title=f"accordion accordion accordion {i}",
                content="accordion " * 40,
            )
            for i in range(12)
        ]
        keep_chunk = _chunk(
            "keep-chunk",
            "keep-1",
            title="Accordion pattern",
            content="A simple accordion component example.",
        )
        store.upsert_chunks([*noise_chunks, keep_chunk])

        svc = SearchService(store, search_mode="lexical", candidates=50)
        # limit smaller than noise count — old bug would fill the page with noise
        # then filter to empty; correct behaviour returns the eligible chunk.
        hits = svc.search("accordion", limit=3, source_id="keep-src")
        assert len(hits) >= 1
        assert all(
            h.resource is not None and h.resource.source.source_id == "keep-src"
            for h in hits
        )
        assert any(h.chunk and h.chunk.id == "keep-chunk" for h in hits)
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Hybrid end-to-end
# ---------------------------------------------------------------------------


def test_hybrid_path_end_to_end() -> None:
    r = _resource("lib:one")
    c1 = _chunk("c-lex", "lib:one", content="pricing table layout")
    c2 = _chunk("c-both", "lib:one", content="pricing and billing")
    c3 = _chunk("c-vec", "lib:one", content="invoice UI")
    store = MemoryStore(
        vector_search=True,
        resources=[r],
        chunks=[c1, c2, c3],
        lexical_results=[
            RankedChunk(chunk_id="c-lex", score=5.0, rank=1),
            RankedChunk(chunk_id="c-both", score=4.0, rank=2),
        ],
        vector_results=[
            RankedChunk(chunk_id="c-both", score=0.95, rank=1),
            RankedChunk(chunk_id="c-vec", score=0.80, rank=2),
        ],
    )
    svc = SearchService(
        store,
        embedder=FakeEmbedder(enabled=True),
        search_mode="hybrid",
        rrf_k=60,
        candidates=20,
    )
    outcome = svc.search_detailed("pricing", limit=5)
    assert outcome.mode == "hybrid"
    assert outcome.vector_used is True
    assert outcome.backend == "memory"
    assert len(outcome.hits) >= 1
    both = next(h for h in outcome.hits if h.chunk and h.chunk.id == "c-both")
    assert both.lexical_rank == 2
    assert both.vector_rank == 1
    assert both.backend == "memory"
    assert both.mode == RetrievalMode.HYBRID
    assert any("RRF" in f for f in both.facts)
    assert any("not comparable" in f for f in both.facts)


def test_describe_reports_mode_and_never_leaks_key() -> None:
    store = MemoryStore(vector_search=False)
    svc = SearchService(
        store,
        embedder=NullEmbeddingProvider(),
        search_mode="auto",
    )
    desc = svc.describe()
    assert desc["effective_mode"] == "lexical"
    assert desc["lexical"] == "postgres_tsvector"  # native lexical on MemoryStore
    assert desc["vector_search_available"] is False
    blob = str(desc)
    assert "sk-" not in blob
    assert "api_key" not in blob.lower() or desc.get("embedding_provider") == "none"


def test_rebuild_and_lazy_build_on_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "lazy.db"
    store = SqliteStore(db)
    try:
        # BM25Okapi needs a few diverse docs before term IDF yields score > 0
        # (LexicalBM25Index drops non-positive scores).
        resources = [_resource(f"r{i}") for i in range(5)]
        chunks = [
            _chunk("c0", "r0", content="navbar sticky header navigation"),
            *[
                _chunk(f"c{i}", f"r{i}", content=f"unrelated filler topic widgets {i}")
                for i in range(1, 5)
            ],
        ]
        store.upsert_resources(resources)
        store.upsert_chunks(chunks)
        svc = SearchService(store, search_mode="lexical")
        count = svc.rebuild()
        assert count == 5
        # Fresh service — search without explicit rebuild (lazy)
        svc2 = SearchService(store, search_mode="lexical")
        hits = svc2.search("navbar", limit=5)
        assert len(hits) >= 1
        assert hits[0].chunk is not None
        assert hits[0].chunk.id == "c0"
    finally:
        store.close()


def test_limit_honoured_and_candidates_pool_larger() -> None:
    r = _resource("r1")
    chunks = [_chunk(f"c{i}", "r1", content=f"widget {i} accordion") for i in range(10)]
    lex = [
        RankedChunk(chunk_id=f"c{i}", score=float(10 - i), rank=i + 1) for i in range(10)
    ]
    store = MemoryStore(
        vector_search=True,
        resources=[r],
        chunks=chunks,
        lexical_results=lex,
        vector_results=lex[:5],
    )
    svc = SearchService(
        store,
        embedder=FakeEmbedder(enabled=True),
        search_mode="hybrid",
        candidates=40,
    )
    outcome = svc.search_detailed("accordion", limit=3)
    assert len(outcome.hits) == 3
    assert store.lexical_limits
    assert store.vector_limits
    assert store.lexical_limits[0] == 40  # max(limit=3, candidates=40)
    assert store.vector_limits[0] == 40


# ---------------------------------------------------------------------------
# Stored vectors from a different model
# ---------------------------------------------------------------------------


def _stored_model(
    *, provider: str = "fake", model: str = "fake-v1", dim: int = 4, pipeline_version: int = 1
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "dim": dim,
        "pipeline_version": pipeline_version,
    }


def test_matching_stored_model_allows_vector_branch() -> None:
    store = MemoryStore(
        vector_search=True,
        resources=[_resource("r1")],
        chunks=[_chunk("c1", "r1")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
        vector_results=[RankedChunk(chunk_id="c1", score=0.9, rank=1)],
    )
    store.stored_embedding_models = [_stored_model()]
    service = SearchService(store, embedder=FakeEmbedder(), search_mode="hybrid")

    outcome = service.search_detailed("button", limit=5)

    assert service.resolve_mode() is RetrievalMode.HYBRID
    assert outcome.mode == "hybrid"
    assert outcome.vector_used is True
    assert outcome.degraded is False
    assert store.last_vector_model == FakeEmbedder().model_ref


def test_mismatched_stored_model_blocks_vector_branch() -> None:
    """A same-dimension model swap must not silently produce nonsense scores."""
    store = MemoryStore(
        vector_search=True,
        resources=[_resource("r1")],
        chunks=[_chunk("c1", "r1")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
        vector_results=[RankedChunk(chunk_id="c1", score=0.9, rank=1)],
    )
    # Same dimension as the provider, different model: every dimension check passes.
    store.stored_embedding_models = [_stored_model(model="other-model-v9", dim=4)]
    embedder = FakeEmbedder(dim=4)
    service = SearchService(store, embedder=embedder, search_mode="hybrid")

    outcome = service.search_detailed("button", limit=5)

    assert outcome.mode == "lexical"
    assert outcome.degraded is True
    assert outcome.vector_used is False
    assert store.vector_calls == 0
    assert embedder.query_calls == 0
    assert any("other-model-v9" in note for note in outcome.notes)
    assert any("Re-embed" in note for note in outcome.notes)
    # Lexical results still come back rather than an error or an empty page.
    assert [hit.chunk.id for hit in outcome.hits if hit.chunk] == ["c1"]
    # The advertised mode must not claim hybrid while the branch is blocked.
    assert service.resolve_mode() is RetrievalMode.LEXICAL
    assert service.describe()["embedding_mismatch"] is not None


def test_mixed_stored_models_block_vector_branch() -> None:
    """Partial re-embed leaving two identities must not enable vector search."""
    store = MemoryStore(
        vector_search=True,
        resources=[_resource("r1")],
        chunks=[_chunk("c1", "r1")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
        vector_results=[RankedChunk(chunk_id="c1", score=0.9, rank=1)],
    )
    store.stored_embedding_models = [
        _stored_model(),
        _stored_model(model="other-model-v9", dim=4),
    ]
    embedder = FakeEmbedder(dim=4)
    service = SearchService(store, embedder=embedder, search_mode="hybrid")

    outcome = service.search_detailed("button", limit=5)

    assert outcome.mode == "lexical"
    assert outcome.degraded is True
    assert outcome.vector_used is False
    assert store.vector_calls == 0
    assert embedder.query_calls == 0
    assert any("mixed embedding identities" in note for note in outcome.notes)
    assert service.resolve_mode() is RetrievalMode.LEXICAL


def test_pipeline_version_change_blocks_vector_branch() -> None:
    store = MemoryStore(
        vector_search=True,
        resources=[_resource("r1")],
        chunks=[_chunk("c1", "r1")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
        vector_results=[RankedChunk(chunk_id="c1", score=0.9, rank=1)],
    )
    store.stored_embedding_models = [_stored_model(pipeline_version=2)]
    service = SearchService(store, embedder=FakeEmbedder(), search_mode="hybrid")

    outcome = service.search_detailed("button", limit=5)

    assert outcome.degraded is True
    assert outcome.vector_used is False


def test_no_stored_embeddings_is_not_a_mismatch() -> None:
    """An empty corpus must degrade for lack of vectors, not for a model conflict."""
    store = MemoryStore(
        vector_search=True,
        resources=[_resource("r1")],
        chunks=[_chunk("c1", "r1")],
        lexical_results=[RankedChunk(chunk_id="c1", score=1.0, rank=1)],
        vector_results=[],
    )
    store.stored_embedding_models = []
    service = SearchService(store, embedder=FakeEmbedder(), search_mode="hybrid")

    outcome = service.search_detailed("button", limit=5)

    assert service.describe()["embedding_mismatch"] is None
    assert outcome.degraded is True
    assert not any("Re-embed" in note for note in outcome.notes)
