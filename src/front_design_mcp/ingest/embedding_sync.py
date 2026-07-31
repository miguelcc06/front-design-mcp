"""Embedding generation for ingest — cache-aware, batch-oriented.

Text embedded for each chunk is ``f"{chunk.title}\\n\\n{chunk.content}"`` so
titles participate in the vector without a separate field.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
)
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.models import DocumentationChunk
from front_design_mcp.store.base import EmbeddingRecord, Store

log = get_logger("ingest.embedding_sync")


@dataclass
class EmbeddingSyncStats:
    written: int = 0
    reused: int = 0
    skipped: int = 0
    errors: int = 0


def sync_embeddings(
    store: Store,
    embedder: EmbeddingProvider,
    chunks: Sequence[DocumentationChunk],
    *,
    batch_size: int = 32,
) -> EmbeddingSyncStats:
    """Embed ``chunks`` into ``store``, skipping cache hits.

    Cache key: ``EmbeddingMeta.matches(embedder.model_ref, chunk.content_sha256)``.
    A second run over unchanged content with the same model identity writes zero
    embeddings and reports them as ``reused``.
    """
    stats = EmbeddingSyncStats()
    if not embedder.enabled:
        return stats

    if not store.capabilities().vector_search:
        stats.skipped = len(chunks)
        log.info(
            "embedding_sync_skipped_no_vector_search",
            backend=store.capabilities().backend,
            chunks=len(chunks),
        )
        return stats

    if not chunks:
        return stats

    meta = store.get_embedding_metadata([c.id for c in chunks])
    to_embed: list[DocumentationChunk] = []
    for chunk in chunks:
        existing = meta.get(chunk.id)
        if existing is not None and existing.matches(
            embedder.model_ref, chunk.content_sha256
        ):
            stats.reused += 1
        else:
            to_embed.append(chunk)

    if not to_embed:
        return stats

    model = embedder.model_ref
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        # Title + body: keeps the heading in the vector space cheaply.
        texts = [f"{chunk.title}\n\n{chunk.content}" for chunk in batch]
        try:
            vectors = embedder.embed_documents(texts)
            records = [
                EmbeddingRecord(
                    chunk_id=chunk.id,
                    vector=vector,
                    content_sha256=chunk.content_sha256,
                    model=model,
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            store.upsert_embeddings(records)
            stats.written += len(records)
        except (EmbeddingError, EmbeddingConfigError) as exc:
            log.warning(
                "embedding_batch_failed",
                batch_size=len(batch),
                error=str(exc),
            )
            stats.errors += len(batch)
            # ValueError from upsert_embeddings (dim mismatch) is not caught here.

    return stats


__all__ = [
    "EmbeddingSyncStats",
    "sync_embeddings",
]
