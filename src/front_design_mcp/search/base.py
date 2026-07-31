"""Retrieval interfaces: filters, ranked candidates, lexical and vector search."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from front_design_mcp.models import DocumentationChunk, SearchHit


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Filters applied *before* ranking and truncation.

    ``resource_ids`` is the escape hatch for filters that cannot be expressed
    in SQL (e.g. framework alias matching): the caller resolves the allowed
    resource set first, and backends push it down as an ``IN`` clause.
    """

    source_id: str | None = None
    kind: str | None = None
    tags: tuple[str, ...] = ()
    resource_ids: frozenset[str] | None = None

    @property
    def is_empty(self) -> bool:
        return (
            self.source_id is None
            and self.kind is None
            and not self.tags
            and self.resource_ids is None
        )

    @property
    def excludes_everything(self) -> bool:
        """True when the filters can provably match no rows."""
        return self.resource_ids is not None and len(self.resource_ids) == 0

    @classmethod
    def build(
        cls,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        tags: Sequence[str] | None = None,
        resource_ids: Sequence[str] | frozenset[str] | None = None,
    ) -> SearchFilters:
        return cls(
            source_id=source_id or None,
            kind=kind or None,
            tags=tuple(sorted({t.lower().strip() for t in (tags or []) if t.strip()})),
            resource_ids=None if resource_ids is None else frozenset(resource_ids),
        )


@dataclass(frozen=True, slots=True)
class RankedChunk:
    """One candidate from a single retrieval branch."""

    chunk_id: str
    score: float
    rank: int


@dataclass(slots=True)
class FusedCandidate:
    """A candidate after Reciprocal Rank Fusion."""

    chunk_id: str
    score: float
    lexical_rank: int | None = None
    vector_rank: int | None = None
    lexical_score: float | None = None
    vector_score: float | None = None


@dataclass(slots=True)
class SearchOutcome:
    """Search results plus the diagnostics needed for honest reporting."""

    hits: list[SearchHit] = field(default_factory=list)
    mode: str = "none"
    backend: str = "unknown"
    lexical_used: bool = False
    vector_used: bool = False
    degraded: bool = False
    notes: list[str] = field(default_factory=list)


@runtime_checkable
class LexicalSearcher(Protocol):
    """Backend-native full-text retrieval."""

    def search_lexical(
        self, query: str, *, filters: SearchFilters, limit: int
    ) -> list[RankedChunk]:
        """Return up to ``limit`` candidates ranked by lexical relevance."""


@runtime_checkable
class VectorSearcher(Protocol):
    """Backend-native approximate nearest-neighbour retrieval."""

    def search_vector(
        self,
        embedding: Sequence[float],
        *,
        filters: SearchFilters,
        limit: int,
    ) -> list[RankedChunk]:
        """Return up to ``limit`` candidates ranked by vector similarity."""


class SearchIndex(ABC):
    """In-process index over documentation chunks (BM25 for the SQLite path)."""

    @abstractmethod
    def rebuild(self, chunks: list[DocumentationChunk]) -> None:
        """Rebuild the index from a list of chunks."""

    @abstractmethod
    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        allowed_chunk_ids: frozenset[str] | None = None,
    ) -> list[SearchHit]:
        """Run a query, restricted to ``allowed_chunk_ids`` when provided."""


__all__ = [
    "FusedCandidate",
    "LexicalSearcher",
    "RankedChunk",
    "SearchFilters",
    "SearchIndex",
    "SearchOutcome",
    "VectorSearcher",
]
