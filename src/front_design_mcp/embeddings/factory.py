"""Factory for embedding providers from application settings."""

from __future__ import annotations

from front_design_mcp.config import Settings
from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingProvider,
    NullEmbeddingProvider,
)
from front_design_mcp.embeddings.fastembed_provider import (
    DEFAULT_FASTEMBED_MODEL,
    FastEmbedEmbeddingProvider,
)
from front_design_mcp.embeddings.openai_provider import (
    DEFAULT_OPENAI_MODEL,
    OpenAIEmbeddingProvider,
)


def create_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Build the embedding provider selected by ``settings.embedding_provider``."""
    name = settings.embedding_provider

    if name == "none":
        return NullEmbeddingProvider()

    if name == "openai":
        secret = settings.embedding_api_key
        if secret is None or not secret.get_secret_value().strip():
            raise EmbeddingConfigError(
                "FRONT_DESIGN_EMBEDDING_API_KEY is required when "
                "FRONT_DESIGN_EMBEDDING_PROVIDER=openai"
            )
        return OpenAIEmbeddingProvider(
            model=settings.embedding_model or DEFAULT_OPENAI_MODEL,
            api_key=secret.get_secret_value(),
            dimensions=settings.embedding_dimensions,
            base_url=settings.embedding_base_url,
            timeout=settings.embedding_timeout,
            max_retries=settings.embedding_max_retries,
            batch_size=settings.embedding_batch_size,
            pipeline_version=settings.embedding_pipeline_version,
        )

    if name == "fastembed":
        return FastEmbedEmbeddingProvider(
            model_name=settings.embedding_model or DEFAULT_FASTEMBED_MODEL,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            pipeline_version=settings.embedding_pipeline_version,
        )

    raise EmbeddingConfigError(f"Unsupported embedding provider: {name!r}")


def describe_provider(provider: EmbeddingProvider) -> dict[str, object]:
    """JSON-safe, secret-free summary for health / capability reporting."""
    ref = provider.model_ref
    return {
        "provider": ref.provider,
        "model": ref.model,
        "dim": ref.dim,
        "pipeline_version": ref.pipeline_version,
        "enabled": provider.enabled,
    }


__all__ = [
    "create_embedding_provider",
    "describe_provider",
]
