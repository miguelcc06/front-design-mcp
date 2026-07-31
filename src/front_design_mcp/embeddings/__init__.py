"""Embedding providers (optional; the default configuration uses none)."""

from __future__ import annotations

from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingModelRef,
    EmbeddingProvider,
    NullEmbeddingProvider,
)
from front_design_mcp.embeddings.factory import (
    create_embedding_provider,
    describe_provider,
)
from front_design_mcp.embeddings.fastembed_provider import (
    DEFAULT_FASTEMBED_MODEL,
    FastEmbedEmbeddingProvider,
)
from front_design_mcp.embeddings.openai_provider import (
    DEFAULT_OPENAI_MODEL,
    OpenAIEmbeddingProvider,
)

__all__ = [
    "DEFAULT_FASTEMBED_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "EmbeddingConfigError",
    "EmbeddingError",
    "EmbeddingModelRef",
    "EmbeddingProvider",
    "FastEmbedEmbeddingProvider",
    "NullEmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "create_embedding_provider",
    "describe_provider",
]
