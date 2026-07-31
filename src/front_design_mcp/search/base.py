"""Search index protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod

from front_design_mcp.models import DocumentationChunk, SearchHit


class SearchIndex(ABC):
    """Abstract search index over documentation chunks."""

    @abstractmethod
    def rebuild(self, chunks: list[DocumentationChunk]) -> None:
        """Rebuild the index from a list of chunks."""

    @abstractmethod
    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        """Run a search query and return ranked hits."""
