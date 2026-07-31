"""Resolve the vector dimension without constructing a provider.

Migrations must size the ``vector(n)`` column before any provider exists, and
must not guess. This module derives the dimension from the same configuration
the runtime uses, and fails with an actionable error when it cannot be known.
"""

from __future__ import annotations

import os

from front_design_mcp.embeddings.base import EmbeddingConfigError
from front_design_mcp.embeddings.fastembed_provider import (
    DEFAULT_FASTEMBED_MODEL,
    resolve_fastembed_dimensions,
)
from front_design_mcp.embeddings.openai_provider import (
    DEFAULT_OPENAI_MODEL,
    resolve_openai_dimensions,
)


def resolve_dimension(
    *, provider: str, model: str | None = None, dimensions: int | None = None
) -> int:
    """Vector dimension implied by a provider/model/override combination."""
    if provider == "openai":
        native, _requested = resolve_openai_dimensions(model or DEFAULT_OPENAI_MODEL, dimensions)
        return native
    if provider == "fastembed":
        return resolve_fastembed_dimensions(model or DEFAULT_FASTEMBED_MODEL, dimensions)
    if provider == "none":
        if dimensions is None:
            raise EmbeddingConfigError(
                "Cannot determine the embedding dimension: "
                "FRONT_DESIGN_EMBEDDING_PROVIDER=none carries no model. Set "
                "FRONT_DESIGN_EMBEDDING_DIMENSIONS explicitly, or select the provider "
                "you intend to use before creating the schema."
            )
        return dimensions
    raise EmbeddingConfigError(f"Unsupported embedding provider: {provider!r}")


def resolve_dimension_from_env() -> int:
    """Dimension for schema creation, taken from ``FRONT_DESIGN_*`` variables.

    Precedence: an explicit ``FRONT_DESIGN_EMBEDDING_DIMENSIONS`` wins, otherwise
    the configured provider and model decide. There is deliberately no default:
    silently creating a 1536-wide column for an unknown model produces a schema
    that rejects every vector the provider generates.
    """
    raw = os.environ.get("FRONT_DESIGN_EMBEDDING_DIMENSIONS", "").strip()
    override: int | None = None
    if raw:
        try:
            override = int(raw)
        except ValueError as exc:
            raise EmbeddingConfigError(
                f"FRONT_DESIGN_EMBEDDING_DIMENSIONS must be an integer, got {raw!r}"
            ) from exc
        if override < 1:
            raise EmbeddingConfigError(
                f"FRONT_DESIGN_EMBEDDING_DIMENSIONS must be >= 1, got {override}"
            )

    provider = os.environ.get("FRONT_DESIGN_EMBEDDING_PROVIDER", "none").strip() or "none"
    model = os.environ.get("FRONT_DESIGN_EMBEDDING_MODEL", "").strip() or None
    return resolve_dimension(provider=provider, model=model, dimensions=override)


__all__ = ["resolve_dimension", "resolve_dimension_from_env"]
