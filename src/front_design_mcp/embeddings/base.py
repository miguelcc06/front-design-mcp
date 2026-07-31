"""Embedding provider interface.

Providers are the source of truth for the vector dimension. Nothing in this
package hardcodes a dimension: the store schema is created from
``provider.model_ref.dim`` and mismatches fail fast instead of silently
producing unusable vectors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from front_design_mcp.store.base import EmbeddingModelRef


class EmbeddingError(RuntimeError):
    """Embedding generation failed after the configured retries."""


class EmbeddingConfigError(ValueError):
    """Provider configuration is invalid or incompatible with stored data."""


class EmbeddingProvider(ABC):
    """Turns text into vectors, or explicitly declares itself disabled."""

    name: str = "unknown"

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """False for the null provider; callers must degrade to lexical search."""

    @property
    @abstractmethod
    def model_ref(self) -> EmbeddingModelRef:
        """Provider/model/dimension/pipeline identity of produced vectors."""

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus texts. Returns one vector per input, in order.

        Implementations batch, apply timeouts, retry a bounded number of times,
        and must never include credentials in exceptions or log records.
        """

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query."""


class NullEmbeddingProvider(EmbeddingProvider):
    """The ``none`` provider: no vectors, no network, no dependencies."""

    name = "none"

    @property
    def enabled(self) -> bool:
        return False

    @property
    def model_ref(self) -> EmbeddingModelRef:
        return EmbeddingModelRef(provider="none", model="none", dim=0, pipeline_version=1)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingConfigError(
            "Embedding provider is 'none'. Set FRONT_DESIGN_EMBEDDING_PROVIDER to a "
            "real provider to generate vectors."
        )

    def embed_query(self, text: str) -> list[float]:
        raise EmbeddingConfigError(
            "Embedding provider is 'none'. Vector search is unavailable; "
            "lexical search is used instead."
        )


__all__ = [
    "EmbeddingConfigError",
    "EmbeddingError",
    "EmbeddingModelRef",
    "EmbeddingProvider",
    "NullEmbeddingProvider",
]
