"""Search orchestration: filters, lexical/vector branches, fusion, degradation.

The service talks to the :class:`~front_design_mcp.store.base.Store` interface and
the :class:`~front_design_mcp.embeddings.base.EmbeddingProvider` interface only. It
never imports a concrete backend, which is what lets the same tool surface run on
SQLite/BM25 offline and on PostgreSQL/pgvector hybrid search.
"""

from __future__ import annotations

from collections.abc import Sequence

from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
    NullEmbeddingProvider,
)
from front_design_mcp.frameworks import resource_matches_framework
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import (
    Citation,
    DocumentationChunk,
    FrontendResource,
    RetrievalMode,
    SearchHit,
)
from front_design_mcp.search.base import (
    FusedCandidate,
    LexicalSearcher,
    RankedChunk,
    SearchFilters,
    SearchOutcome,
    VectorSearcher,
)
from front_design_mcp.search.lexical import LexicalBM25Index
from front_design_mcp.search.rrf import as_fused, reciprocal_rank_fusion
from front_design_mcp.store.base import Store

log = get_logger("search.service")


class SearchService:
    """Backend-agnostic retrieval over stored chunks."""

    def __init__(
        self,
        store: Store,
        *,
        embedder: EmbeddingProvider | None = None,
        search_mode: str = "auto",
        rrf_k: int = 60,
        rrf_lexical_weight: float = 1.0,
        rrf_vector_weight: float = 1.0,
        candidates: int = 50,
    ) -> None:
        self._store = store
        self._embedder = embedder or NullEmbeddingProvider()
        self._search_mode = search_mode
        self._rrf_k = rrf_k
        self._rrf_lexical_weight = rrf_lexical_weight
        self._rrf_vector_weight = rrf_vector_weight
        self._candidates = candidates

        caps = store.capabilities()
        self._backend = caps.backend
        self._native_lexical = isinstance(store, LexicalSearcher)
        self._native_vector = isinstance(store, VectorSearcher) and caps.vector_search
        # Only the non-native path needs an in-process index.
        self._index: LexicalBM25Index | None = None if self._native_lexical else LexicalBM25Index()
        self._resource_cache: dict[str, FrontendResource] = {}
        self._built = False

    # --- index lifecycle -------------------------------------------------

    def rebuild(self) -> int:
        """(Re)load in-process state. Returns the number of indexed chunks.

        For PostgreSQL this only refreshes the resource cache — ranking happens
        in the database, so there is no corpus to load into memory.
        """
        resources = self._store.list_resources(limit=1_000_000)
        self._resource_cache = {r.id: r for r in resources}
        self._built = True
        if self._index is None:
            return self._store.count_chunks()
        chunks = self._store.list_chunks(limit=1_000_000)
        self._index.rebuild(chunks)
        return len(chunks)

    def _ensure_built(self) -> None:
        if not self._built:
            self.rebuild()

    # --- mode resolution -------------------------------------------------

    def resolve_mode(self) -> RetrievalMode:
        """Effective retrieval mode given backend, provider, and configuration."""
        vector_possible = self._native_vector and self._embedder.enabled
        if self._search_mode == "lexical":
            return RetrievalMode.LEXICAL
        if self._search_mode == "vector":
            return RetrievalMode.VECTOR if vector_possible else RetrievalMode.LEXICAL
        if self._search_mode == "hybrid":
            return RetrievalMode.HYBRID if vector_possible else RetrievalMode.LEXICAL
        return RetrievalMode.HYBRID if vector_possible else RetrievalMode.LEXICAL

    def describe(self) -> dict[str, object]:
        """Honest capability report for health checks and the README."""
        caps = self._store.capabilities()
        return {
            "backend": caps.backend,
            "configured_mode": self._search_mode,
            "effective_mode": self.resolve_mode().value,
            "lexical": "postgres_tsvector" if self._native_lexical else "bm25_in_process",
            "vector_search_available": self._native_vector and self._embedder.enabled,
            "embedding_provider": self._embedder.model_ref.provider,
            "embedding_model": self._embedder.model_ref.model,
            "embedding_dim": self._embedder.model_ref.dim or None,
            "rrf_k": self._rrf_k,
        }

    # --- filters ---------------------------------------------------------

    def build_filters(
        self,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] | None = None,
        framework: str | None = None,
    ) -> SearchFilters:
        """Resolve public filter arguments into pre-ranking filters.

        Framework matching uses alias expansion that cannot be expressed in SQL,
        so it is resolved to an explicit resource-id set first. That keeps the
        filter *before* ranking instead of trimming an already truncated page.
        """
        resource_ids: frozenset[str] | None = None
        if framework:
            self._ensure_built()
            resource_ids = frozenset(
                rid
                for rid, resource in self._resource_cache.items()
                if resource_matches_framework(resource, framework)
            )
        return SearchFilters.build(
            source_id=source_id,
            kind=kind,
            tags=tags,
            resource_ids=resource_ids,
        )

    # --- retrieval branches ----------------------------------------------

    def _lexical_branch(
        self, query: str, filters: SearchFilters, limit: int
    ) -> list[RankedChunk]:
        if self._native_lexical:
            searcher: LexicalSearcher = self._store  # type: ignore[assignment]  # guarded by isinstance in __init__
            return searcher.search_lexical(query, filters=filters, limit=limit)
        assert self._index is not None
        allowed = self._store.resolve_filtered_chunk_ids(filters)
        return self._index.rank(query, limit=limit, allowed_chunk_ids=allowed)

    def _vector_branch(
        self, query: str, filters: SearchFilters, limit: int, notes: list[str]
    ) -> list[RankedChunk]:
        if not self._native_vector or not self._embedder.enabled:
            return []
        try:
            embedding = self._embedder.embed_query(query)
        except (EmbeddingConfigError, EmbeddingError) as exc:
            notes.append(f"Vector branch unavailable: {type(exc).__name__}. Lexical only.")
            log.warning("vector_branch_failed", error=type(exc).__name__)
            return []
        searcher: VectorSearcher = self._store  # type: ignore[assignment]  # guarded by isinstance in __init__
        try:
            return searcher.search_vector(embedding, filters=filters, limit=limit)
        except ValueError as exc:
            # Dimension mismatch between the provider and the stored schema.
            notes.append(f"Vector branch unavailable: {exc}")
            log.warning("vector_search_rejected", error=str(exc))
            return []

    # --- public API ------------------------------------------------------

    def search_detailed(
        self,
        query: str,
        *,
        limit: int = 10,
        source_id: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] | None = None,
        framework: str | None = None,
    ) -> SearchOutcome:
        """Run the configured retrieval strategy and report how it was answered."""
        self._ensure_built()
        outcome = SearchOutcome(backend=self._backend)
        requested_mode = self.resolve_mode()

        if not query.strip():
            outcome.mode = RetrievalMode.NONE.value
            outcome.notes.append("Empty query: no retrieval attempted.")
            return outcome

        filters = self.build_filters(
            source_id=source_id, kind=kind, tags=tags, framework=framework
        )
        if filters.excludes_everything:
            outcome.mode = RetrievalMode.NONE.value
            outcome.notes.append("Filters matched no resources, so no chunk could match.")
            return outcome

        pool = max(limit, self._candidates)
        lexical = self._lexical_branch(query, filters, pool)
        vector: list[RankedChunk] = []
        if requested_mode in (RetrievalMode.HYBRID, RetrievalMode.VECTOR):
            vector = self._vector_branch(query, filters, pool, outcome.notes)

        outcome.lexical_used = bool(lexical) or requested_mode != RetrievalMode.VECTOR
        outcome.vector_used = bool(vector)

        candidates: list[FusedCandidate]
        if requested_mode == RetrievalMode.HYBRID and vector:
            candidates = reciprocal_rank_fusion(
                lexical,
                vector,
                k=self._rrf_k,
                lexical_weight=self._rrf_lexical_weight,
                vector_weight=self._rrf_vector_weight,
            )
            effective = RetrievalMode.HYBRID
        elif requested_mode == RetrievalMode.VECTOR and vector:
            candidates = as_fused(vector, lexical=False)
            effective = RetrievalMode.VECTOR
        else:
            candidates = as_fused(lexical, lexical=True)
            effective = RetrievalMode.LEXICAL
            if requested_mode in (RetrievalMode.HYBRID, RetrievalMode.VECTOR):
                outcome.degraded = True
                if not any("Vector branch unavailable" in note for note in outcome.notes):
                    outcome.notes.append(
                        "No vector candidates (missing or empty embeddings); "
                        "answered with lexical search only."
                    )

        outcome.mode = effective.value
        outcome.hits = self._materialize(candidates[:limit], mode=effective)
        return outcome

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        source_id: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] | None = None,
        framework: str | None = None,
    ) -> list[SearchHit]:
        """Ranked hits only. See :meth:`search_detailed` for diagnostics."""
        return self.search_detailed(
            query,
            limit=limit,
            source_id=source_id,
            kind=kind,
            tags=tags,
            framework=framework,
        ).hits

    # --- hydration -------------------------------------------------------

    def _resource_for(self, resource_id: str) -> FrontendResource | None:
        cached = self._resource_cache.get(resource_id)
        if cached is not None:
            return cached
        fetched = self._store.get_resource(resource_id)
        if fetched is not None:
            self._resource_cache[resource_id] = fetched
        return fetched

    def _materialize(
        self, candidates: Sequence[FusedCandidate], *, mode: RetrievalMode
    ) -> list[SearchHit]:
        if not candidates:
            return []
        chunk_ids = [c.chunk_id for c in candidates]
        chunks: dict[str, DocumentationChunk] = {
            c.id: c for c in self._store.get_chunks(chunk_ids)
        }

        hits: list[SearchHit] = []
        for candidate in candidates:
            chunk = chunks.get(candidate.chunk_id)
            if chunk is None:
                continue
            resource = self._resource_for(chunk.resource_id)
            if resource is None:
                continue
            hits.append(
                SearchHit(
                    resource=resource,
                    chunk=chunk,
                    score=candidate.score,
                    citation=Citation(
                        resource_id=resource.id,
                        chunk_id=chunk.id,
                        title=chunk.title,
                        url=chunk.source_url or resource.docs_url,
                        source_id=resource.source.source_id,
                        excerpt=chunk.content[:240] if chunk.content else None,
                    ),
                    facts=self._facts_for(candidate, resource, mode),
                    inferences=[],
                    mode=mode,
                    backend=self._backend,
                    lexical_rank=candidate.lexical_rank,
                    vector_rank=candidate.vector_rank,
                    lexical_score=candidate.lexical_score,
                    vector_score=candidate.vector_score,
                )
            )
        return hits

    def _facts_for(
        self, candidate: FusedCandidate, resource: FrontendResource, mode: RetrievalMode
    ) -> list[str]:
        facts = [
            f"source={resource.source.source_id}",
            f"kind={resource.kind.value}",
            f"retrieval={mode.value} backend={self._backend}",
        ]
        if candidate.lexical_rank is not None:
            facts.append(
                f"lexical rank={candidate.lexical_rank} score={candidate.lexical_score:.4f}"
                if candidate.lexical_score is not None
                else f"lexical rank={candidate.lexical_rank}"
            )
        if candidate.vector_rank is not None:
            facts.append(
                f"vector rank={candidate.vector_rank} cosine_similarity="
                f"{candidate.vector_score:.4f}"
                if candidate.vector_score is not None
                else f"vector rank={candidate.vector_rank}"
            )
        if mode == RetrievalMode.HYBRID:
            facts.append(
                f"RRF score={candidate.score:.6f} (k={self._rrf_k}; not comparable to BM25/cosine)"
            )
        return facts


__all__ = ["SearchService"]
