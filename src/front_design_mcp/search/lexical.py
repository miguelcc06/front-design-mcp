"""In-memory BM25 lexical search over documentation chunks (SQLite backend)."""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from front_design_mcp.models import Citation, DocumentationChunk, SearchHit
from front_design_mcp.search.base import RankedChunk, SearchIndex

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Simple whitespace/alnum tokenizer for BM25."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class LexicalBM25Index(SearchIndex):
    """BM25 index rebuilt in-memory from store chunks.

    Only used by the SQLite backend; PostgreSQL ranks with ``ts_rank_cd`` inside
    the database. ``rebuild`` is O(corpus) and is called once at startup and again
    after an in-process ingest, so callers must not invoke it per query.
    """

    def __init__(self) -> None:
        self._chunks: list[DocumentationChunk] = []
        self._corpus_tokens: list[list[str]] = []
        self._bm25: BM25Okapi | None = None

    @property
    def size(self) -> int:
        return len(self._chunks)

    def rebuild(self, chunks: list[DocumentationChunk]) -> None:
        self._chunks = list(chunks)
        self._corpus_tokens = [
            tokenize(f"{c.title}\n{c.content}\n{' '.join(c.tags)}") for c in self._chunks
        ]
        self._bm25 = BM25Okapi(self._corpus_tokens) if self._corpus_tokens else None

    def rank(
        self,
        query: str,
        *,
        limit: int = 10,
        allowed_chunk_ids: frozenset[str] | None = None,
    ) -> list[RankedChunk]:
        """Rank chunk ids by BM25, restricted to ``allowed_chunk_ids`` if given.

        Filtering happens before truncation: excluded chunks can never consume a
        result slot, which is what makes filtered queries return real matches
        instead of a falsely empty page.
        """
        if not self._bm25 or not self._chunks or not query.strip() or limit <= 0:
            return []
        if allowed_chunk_ids is not None and not allowed_chunk_ids:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []

        scores = self._bm25.get_scores(tokens)
        candidates: list[tuple[str, float]] = []
        for idx, score in enumerate(scores):
            if score <= 0:
                continue
            chunk_id = self._chunks[idx].id
            if allowed_chunk_ids is not None and chunk_id not in allowed_chunk_ids:
                continue
            candidates.append((chunk_id, float(score)))

        candidates.sort(key=lambda item: (-item[1], item[0]))
        return [
            RankedChunk(chunk_id=chunk_id, score=score, rank=position)
            for position, (chunk_id, score) in enumerate(candidates[:limit], start=1)
        ]

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        allowed_chunk_ids: frozenset[str] | None = None,
    ) -> list[SearchHit]:
        """Convenience wrapper returning chunk-only hits (used by tests/tools)."""
        by_id = {c.id: c for c in self._chunks}
        hits: list[SearchHit] = []
        for ranked in self.rank(query, limit=limit, allowed_chunk_ids=allowed_chunk_ids):
            chunk = by_id.get(ranked.chunk_id)
            if chunk is None:
                continue
            hits.append(
                SearchHit(
                    chunk=chunk,
                    score=ranked.score,
                    citation=Citation(
                        resource_id=chunk.resource_id,
                        chunk_id=chunk.id,
                        title=chunk.title,
                        url=chunk.source_url,
                        excerpt=chunk.content[:240] if chunk.content else None,
                    ),
                    facts=[f"BM25 score={ranked.score:.4f} for chunk {chunk.id}"],
                    inferences=[],
                    lexical_rank=ranked.rank,
                    lexical_score=ranked.score,
                )
            )
        return hits


__all__ = ["LexicalBM25Index", "tokenize"]
