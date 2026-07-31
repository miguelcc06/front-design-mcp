"""In-memory BM25 lexical search over documentation chunks."""

from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from front_design_mcp.models import Citation, DocumentationChunk, SearchHit
from front_design_mcp.search.base import SearchIndex

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    """Simple whitespace/alnum tokenizer for BM25."""
    return [t.lower() for t in _TOKEN_RE.findall(text)]


class LexicalBM25Index(SearchIndex):
    """BM25 index rebuilt in-memory from store chunks (Package A)."""

    def __init__(self) -> None:
        self._chunks: list[DocumentationChunk] = []
        self._corpus_tokens: list[list[str]] = []
        self._bm25: BM25Okapi | None = None

    def rebuild(self, chunks: list[DocumentationChunk]) -> None:
        self._chunks = list(chunks)
        self._corpus_tokens = [
            tokenize(f"{c.title}\n{c.content}\n{' '.join(c.tags)}") for c in self._chunks
        ]
        if self._corpus_tokens:
            self._bm25 = BM25Okapi(self._corpus_tokens)
        else:
            self._bm25 = None

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if not self._bm25 or not self._chunks or not query.strip():
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        hits: list[SearchHit] = []
        for idx, score in ranked[:limit]:
            if score <= 0:
                continue
            chunk = self._chunks[idx]
            hits.append(
                SearchHit(
                    chunk=chunk,
                    score=float(score),
                    citation=Citation(
                        resource_id=chunk.resource_id,
                        chunk_id=chunk.id,
                        title=chunk.title,
                        url=chunk.source_url,
                        excerpt=chunk.content[:240] if chunk.content else None,
                    ),
                    facts=[f"BM25 score={score:.4f} for chunk {chunk.id}"],
                    inferences=[],
                )
            )
        return hits
