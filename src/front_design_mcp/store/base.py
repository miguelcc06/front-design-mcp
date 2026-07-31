"""Storage interface for resources, chunks, and embeddings.

Both backends (SQLite and PostgreSQL) implement :class:`Store`. Search-specific
capabilities live in :mod:`front_design_mcp.search.base` so that a store can
opt into lexical/vector retrieval without every backend having to implement it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from front_design_mcp.models import DocumentationChunk, FrontendResource

if TYPE_CHECKING:
    # Import-time only: a runtime import would make store.base and search.base
    # circular (search.service -> embeddings.base -> store.base).
    from front_design_mcp.search.base import SearchFilters


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
    def transaction(self) -> AbstractContextManager[None]:
        """Run a batch of writes in one transaction.

        Used as ``with store.transaction():``. Implementations commit on
        success, roll back on exception, and nesting joins the outermost
        transaction rather than opening a savepoint. Writes issued inside a
        transaction must not commit on their own.
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

    def embedding_models(self) -> list[EmbeddingModelRef]:
        """Distinct embedding identities present in the store.

        Lets callers detect that the configured provider is not the one that
        produced the stored vectors. A same-dimension model swap passes every
        dimension check while making similarity scores meaningless, so this is
        the only signal that catches it.
        """
        raw = self.stats().get("embedding_models") or []
        models: list[EmbeddingModelRef] = []
        for entry in raw:
            models.append(
                EmbeddingModelRef(
                    provider=str(entry["provider"]),
                    model=str(entry["model"]),
                    dim=int(entry["dim"]),
                    pipeline_version=int(entry["pipeline_version"]),
                )
            )
        return models

    # --- filter resolution -----------------------------------------------

    def resolve_filtered_chunk_ids(self, filters: SearchFilters) -> frozenset[str] | None:
        """Chunk ids allowed by ``filters``, or ``None`` when nothing is filtered.

        Needed by retrieval strategies that rank in-process (the SQLite BM25
        path) so filters are applied before scoring and truncation. Backends
        that push filters into their own SQL do not need to override this; the
        default implementation is a correct but unoptimised fallback.
        """
        if filters.is_empty:
            return None
        if filters.excludes_everything:
            return frozenset()
        resources = self.list_resources(
            source_id=filters.source_id,
            kind=filters.kind,
            limit=1_000_000,
        )
        wanted_tags = set(filters.tags)
        allowed: set[str] = set()
        for resource in resources:
            if filters.resource_ids is not None and resource.id not in filters.resource_ids:
                continue
            resource_tags = {t.lower() for t in resource.tags}
            for chunk in self.list_chunks(resource_id=resource.id, limit=1_000_000):
                if wanted_tags:
                    chunk_tags = {t.lower() for t in chunk.tags}
                    if not wanted_tags & (chunk_tags | resource_tags):
                        continue
                allowed.add(chunk.id)
        return frozenset(allowed)

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
