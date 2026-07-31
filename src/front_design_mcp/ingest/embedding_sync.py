"""Embedding generation for ingest — cache-aware, batch-oriented.

Text embedded for each chunk is ``f"{chunk.title}\\n\\n{chunk.content}"`` so
titles participate in the vector without a separate field. The cache fingerprint
stored on each embedding row is the SHA-256 of that exact embedded text — not
the chunk's ``content_sha256``, which may ignore title and always ignores tags,
URL, licence, and other metadata.
"""

from __future__ import annotations

import hashlib
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


def embedding_input_text(chunk: DocumentationChunk) -> str:
    """Exact text passed to the embedding provider for ``chunk``."""
    return f"{chunk.title}\n\n{chunk.content}"


def embedding_input_sha256(chunk: DocumentationChunk) -> str:
    """Fingerprint of the embedded text; used as the embedding cache key."""
    return hashlib.sha256(embedding_input_text(chunk).encode("utf-8")).hexdigest()


def sync_embeddings(
    store: Store,
    embedder: EmbeddingProvider,
    chunks: Sequence[DocumentationChunk],
    *,
    batch_size: int = 32,
) -> EmbeddingSyncStats:
    """Embed ``chunks`` into ``store``, skipping cache hits.

    Cache key: ``EmbeddingMeta.matches(embedder.model_ref, embedding_input_sha256)``.
    Title or content changes invalidate the vector; tag/URL/licence/timestamp-only
    changes do not, because they are absent from the embedded text.
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
    input_hashes: dict[str, str] = {}
    for chunk in chunks:
        input_sha = embedding_input_sha256(chunk)
        input_hashes[chunk.id] = input_sha
        existing = meta.get(chunk.id)
        if existing is not None and existing.matches(embedder.model_ref, input_sha):
            stats.reused += 1
        else:
            to_embed.append(chunk)

    if not to_embed:
        return stats

    model = embedder.model_ref
    for start in range(0, len(to_embed), batch_size):
        batch = to_embed[start : start + batch_size]
        texts = [embedding_input_text(chunk) for chunk in batch]
        try:
            vectors = embedder.embed_documents(texts)
            records = [
                EmbeddingRecord(
                    chunk_id=chunk.id,
                    vector=vector,
                    content_sha256=input_hashes[chunk.id],
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
    "embedding_input_sha256",
    "embedding_input_text",
    "sync_embeddings",
]
