"""Optional local embedding provider powered by fastembed.

``fastembed`` is an opt-in dependency group (``uv sync --group local``). This
module must import cleanly when the package is absent; the import is deferred
until a provider instance is constructed without an injected model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
)
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.store.base import EmbeddingModelRef

logger = get_logger(__name__)

DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"

# Small table of known native dimensions — do not invent entries.
_FASTEMBED_NATIVE_DIMS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "intfloat/multilingual-e5-small": 384,
}


def resolve_fastembed_dimensions(model_name: str, dimensions: int | None) -> int:
    """Resolve output dimension for a FastEmbed model name."""
    native = _FASTEMBED_NATIVE_DIMS.get(model_name)

    if dimensions is None:
        if native is None:
            raise EmbeddingConfigError(
                f"Unknown FastEmbed model {model_name!r}. Set "
                "FRONT_DESIGN_EMBEDDING_DIMENSIONS explicitly to the model's "
                "output size; refusing to assume a default."
            )
        return native

    if dimensions < 1:
        raise EmbeddingConfigError(
            f"embedding dimensions must be >= 1, got {dimensions}"
        )

    if native is not None and dimensions != native:
        raise EmbeddingConfigError(
            f"FastEmbed model {model_name!r} has fixed dimension {native}; "
            f"requested {dimensions} is not supported"
        )
    return dimensions


class FastEmbedEmbeddingProvider(EmbeddingProvider):
    """Fully local embeddings via fastembed (optional dependency)."""

    name = "fastembed"

    def __init__(
        self,
        model_name: str = DEFAULT_FASTEMBED_MODEL,
        dimensions: int | None = None,
        batch_size: int = 32,
        pipeline_version: int = 1,
        model: Any | None = None,
    ) -> None:
        if not model_name.strip():
            raise EmbeddingConfigError("FastEmbed model name must be non-blank")

        self._model_name = model_name
        self._batch_size = batch_size
        self._pipeline_version = pipeline_version
        self._dim = resolve_fastembed_dimensions(model_name, dimensions)
        self._model_override = model
        self._cached_model: Any | None = None

        if model is None:
            # Resolve the dependency eagerly so misconfiguration fails at init.
            self._load_model()

    def _load_model(self) -> Any:
        if self._model_override is not None:
            return self._model_override
        if self._cached_model is None:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise EmbeddingConfigError(
                    "The 'fastembed' package is required for the FastEmbed "
                    "embedding provider. Install the optional local group with: "
                    "uv sync --group local"
                ) from exc
            logger.info(
                "fastembed_loading",
                model=self._model_name,
                dim=self._dim,
            )
            self._cached_model = TextEmbedding(model_name=self._model_name)
        return self._cached_model

    @property
    def enabled(self) -> bool:
        return True

    @property
    def model_ref(self) -> EmbeddingModelRef:
        return EmbeddingModelRef(
            provider="fastembed",
            model=self._model_name,
            dim=self._dim,
            pipeline_version=self._pipeline_version,
        )

    def __repr__(self) -> str:
        return (
            f"FastEmbedEmbeddingProvider(model_name={self._model_name!r}, "
            f"dim={self._dim})"
        )

    def _verify_vectors(self, vectors: list[list[float]]) -> None:
        expected = self._dim
        for i, vec in enumerate(vectors):
            if len(vec) != expected:
                raise EmbeddingError(
                    f"Embedding length mismatch at index {i}: "
                    f"got {len(vec)}, expected {expected} "
                    f"(model={self._model_name!r})"
                )

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        # Preserve one vector per input; empty strings stay empty for local models.
        model = self._load_model()
        try:
            raw = list(model.embed(list(texts)))
        except Exception as exc:
            raise EmbeddingError(f"{type(exc).__name__}: {exc}") from exc

        if len(raw) != len(texts):
            raise EmbeddingError(
                f"FastEmbed returned {len(raw)} embeddings for {len(texts)} inputs"
            )

        vectors: list[list[float]] = []
        for item in raw:
            vectors.append([float(x) for x in item])
        self._verify_vectors(vectors)
        return vectors

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            results.extend(self._embed_batch(batch))
        return results

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmbeddingConfigError(
                "Query text must be non-blank for FastEmbed embedding"
            )
        return self._embed_batch([text])[0]


__all__ = [
    "DEFAULT_FASTEMBED_MODEL",
    "FastEmbedEmbeddingProvider",
    "resolve_fastembed_dimensions",
]
