"""Store protocol for persisting resources, chunks, and embedding stubs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from front_design_mcp.models import DocumentationChunk, FrontendResource


class Store(ABC):
    """Persistence interface for indexed frontend resources and docs."""

    @abstractmethod
    def open(self) -> None:
        """Open the store and ensure schema exists."""

    @abstractmethod
    def close(self) -> None:
        """Close underlying connections."""

    @abstractmethod
    def upsert_resource(self, resource: FrontendResource) -> None:
        """Insert or update a resource."""

    @abstractmethod
    def get_resource(self, resource_id: str) -> FrontendResource | None:
        """Fetch a resource by id."""

    @abstractmethod
    def list_resources(
        self,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FrontendResource]:
        """List resources with optional filters."""

    @abstractmethod
    def upsert_chunk(self, chunk: DocumentationChunk) -> None:
        """Insert or update a documentation chunk."""

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        """Fetch a chunk by id."""

    @abstractmethod
    def list_chunks(
        self,
        *,
        resource_id: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[DocumentationChunk]:
        """List documentation chunks."""

    @abstractmethod
    def upsert_embedding_stub(
        self,
        chunk_id: str,
        provider: str,
        dims: int,
        blob: bytes | None = None,
    ) -> None:
        """Store an embedding stub row (optional provider; hashing/local)."""

    @abstractmethod
    def get_embedding_stub(self, chunk_id: str, provider: str) -> dict[str, Any] | None:
        """Fetch embedding stub metadata for a chunk."""
