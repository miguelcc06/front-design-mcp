"""Storage interface for resources, chunks, and embeddings.

Both backends (SQLite and PostgreSQL) implement :class:`Store`. Search-specific
capabilities live in :mod:`front_design_mcp.search.base` so that a store can
opt into lexical/vector retrieval without every backend having to implement it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from front_design_mcp.models import DocumentationChunk, FrontendResource


class SyncOutcome(StrEnum):
    """Result class of an ingest/sync run."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EmbeddingModelRef:
    """Identity of the pipeline that produced an embedding.

    Embeddings are only reusable when *all* fields match, together with the
    chunk's ``content_sha256``.
    """

    provider: str
    model: str
    dim: int
    pipeline_version: int = 1

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.model}:{self.dim}:v{self.pipeline_version}"


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    """A vector to persist for one chunk."""

    chunk_id: str
    vector: Sequence[float]
    content_sha256: str
    model: EmbeddingModelRef


@dataclass(frozen=True, slots=True)
class EmbeddingMeta:
    """Persisted embedding metadata used to decide whether to recompute."""

    chunk_id: str
    provider: str
    model: str
    dim: int
    pipeline_version: int
    content_sha256: str
    created_at: datetime | None = None

    def matches(self, model: EmbeddingModelRef, content_sha256: str) -> bool:
        return (
            self.provider == model.provider
            and self.model == model.model
            and self.dim == model.dim
            and self.pipeline_version == model.pipeline_version
            and self.content_sha256 == content_sha256
        )


@dataclass(frozen=True, slots=True)
class StoreCapabilities:
    """What a concrete store can do, for honest capability reporting."""

    backend: str
    lexical_search: bool
    vector_search: bool
    embedding_dim: int | None = None


class StoreNotSupportedError(NotImplementedError):
    """Raised when a backend is asked for a capability it does not have."""


class Store(ABC):
    """Persistence interface for indexed frontend resources and docs."""

    backend: str = "unknown"

    # --- lifecycle -------------------------------------------------------

    @abstractmethod
    def open(self) -> None:
        """Open the store and verify the schema is present and usable."""

    @abstractmethod
    def close(self) -> None:
        """Close underlying connections."""

    @abstractmethod
    def transaction(self) -> Iterator[None]:
        """Context manager running a batch of writes in one transaction.

        Implementations are context managers (``with store.transaction():``)
        and must commit on success and roll back on exception. Nesting joins
        the outermost transaction rather than opening a savepoint.
        """

    @abstractmethod
    def capabilities(self) -> StoreCapabilities:
        """Report backend name and retrieval capabilities."""

    # --- resources -------------------------------------------------------

    @abstractmethod
    def upsert_resources(self, resources: Sequence[FrontendResource]) -> None:
        """Insert or update many resources."""

    def upsert_resource(self, resource: FrontendResource) -> None:
        """Insert or update a single resource."""
        self.upsert_resources([resource])

    @abstractmethod
    def get_resource(self, resource_id: str) -> FrontendResource | None:
        """Fetch a resource by id."""

    @abstractmethod
    def list_resources(
        self,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[FrontendResource]:
        """List resources. Filters are applied *before* limit/offset."""

    @abstractmethod
    def list_resource_ids(self, *, source_id: str | None = None) -> set[str]:
        """All resource ids, optionally restricted to one source."""

    @abstractmethod
    def delete_resources(self, resource_ids: Sequence[str]) -> int:
        """Delete resources and their chunks/embeddings. Returns rows removed."""

    @abstractmethod
    def count_resources(self, *, source_id: str | None = None) -> int:
        """Number of stored resources."""

    # --- chunks ----------------------------------------------------------

    @abstractmethod
    def upsert_chunks(self, chunks: Sequence[DocumentationChunk]) -> None:
        """Insert or update many documentation chunks."""

    def upsert_chunk(self, chunk: DocumentationChunk) -> None:
        """Insert or update a single documentation chunk."""
        self.upsert_chunks([chunk])

    @abstractmethod
    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        """Fetch a chunk by id."""

    @abstractmethod
    def get_chunks(self, chunk_ids: Sequence[str]) -> list[DocumentationChunk]:
        """Fetch many chunks by id (order follows ``chunk_ids`` where present)."""

    @abstractmethod
    def list_chunks(
        self,
        *,
        resource_id: str | None = None,
        source_id: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[DocumentationChunk]:
        """List documentation chunks. Filters applied before limit/offset."""

    @abstractmethod
    def list_chunk_fingerprints(self, *, source_id: str | None = None) -> dict[str, str]:
        """Map ``chunk_id -> content_sha256`` for incremental sync."""

    @abstractmethod
    def delete_chunks(self, chunk_ids: Sequence[str]) -> int:
        """Delete chunks (and their embeddings). Returns rows removed."""

    @abstractmethod
    def count_chunks(self, *, source_id: str | None = None) -> int:
        """Number of stored chunks."""

    # --- embeddings ------------------------------------------------------

    @abstractmethod
    def upsert_embeddings(self, records: Sequence[EmbeddingRecord]) -> None:
        """Persist vectors. Raises ``ValueError`` on dimension mismatch."""

    @abstractmethod
    def get_embedding_metadata(
        self, chunk_ids: Sequence[str] | None = None
    ) -> dict[str, EmbeddingMeta]:
        """Embedding metadata by chunk id, for cache-hit decisions."""

    @abstractmethod
    def delete_embeddings(
        self,
        *,
        chunk_ids: Sequence[str] | None = None,
        not_matching: EmbeddingModelRef | None = None,
    ) -> int:
        """Delete embeddings by chunk id, or every row from another model."""

    @abstractmethod
    def count_embeddings(self, *, model: EmbeddingModelRef | None = None) -> int:
        """Number of stored embeddings, optionally for one model identity."""

    # --- introspection ---------------------------------------------------

    @abstractmethod
    def stats(self) -> dict[str, Any]:
        """Backend-reported counts and configuration, safe for logs/tools."""


__all__ = [
    "EmbeddingMeta",
    "EmbeddingModelRef",
    "EmbeddingRecord",
    "Store",
    "StoreCapabilities",
    "StoreNotSupportedError",
    "SyncOutcome",
]
