"""OpenAI-compatible remote embedding provider.

Empty corpus strings are substituted with a single space before the API call
because the OpenAI embeddings endpoint rejects empty inputs; callers still
receive one vector per input in the original order.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Sequence
from typing import Any

from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    EmbeddingProvider,
)
from front_design_mcp.logging_utils import get_logger
from front_design_mcp.store.base import EmbeddingModelRef

logger = get_logger(__name__)

DEFAULT_OPENAI_MODEL = "text-embedding-3-small"

# Documented native dimensions only — do not invent entries.
_OPENAI_NATIVE_DIMS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}

_TRANSIENT_EXC_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "ServiceUnavailableError",
        "TimeoutError",
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
    }
)

_NON_TRANSIENT_EXC_NAMES = frozenset(
    {
        "AuthenticationError",
        "PermissionDeniedError",
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
        "ConflictError",
        "EmbeddingConfigError",
    }
)


def _supports_dimensions_api(model: str) -> bool:
    return model.startswith("text-embedding-3-")


def resolve_openai_dimensions(model: str, dimensions: int | None) -> tuple[int, int | None]:
    """Resolve output dim and optional ``dimensions=`` API argument.

    Returns ``(resolved_dim, api_dimensions_param)``. The API param is only set
    when the caller explicitly requested truncation on a ``text-embedding-3-*``
    model.
    """
    native = _OPENAI_NATIVE_DIMS.get(model)

    if dimensions is None:
        if native is None:
            raise EmbeddingConfigError(
                f"Unknown OpenAI embedding model {model!r}. Set "
                "FRONT_DESIGN_EMBEDDING_DIMENSIONS explicitly to the model's "
                "output size; refusing to assume 1536."
            )
        return native, None

    if dimensions < 1:
        raise EmbeddingConfigError(
            f"embedding dimensions must be >= 1, got {dimensions}"
        )

    if native is None:
        # Unknown model with an explicit dim — trust the caller.
        return dimensions, dimensions if _supports_dimensions_api(model) else None

    if _supports_dimensions_api(model):
        if dimensions > native:
            raise EmbeddingConfigError(
                f"dimensions={dimensions} exceeds native size {native} for "
                f"model {model!r}"
            )
        return dimensions, dimensions

    if dimensions != native:
        raise EmbeddingConfigError(
            f"Model {model!r} does not support dimension truncation "
            f"(native={native}, requested={dimensions})"
        )
    return native, None


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Remote embeddings via the OpenAI (or compatible) Embeddings API."""

    name = "openai"

    def __init__(
        self,
        model: str,
        api_key: str,
        dimensions: int | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        batch_size: int = 32,
        pipeline_version: int = 1,
        client: Any | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        if not model.strip():
            raise EmbeddingConfigError("OpenAI embedding model must be non-blank")
        if not api_key:
            raise EmbeddingConfigError(
                "FRONT_DESIGN_EMBEDDING_API_KEY is required for the OpenAI provider"
            )

        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._pipeline_version = pipeline_version
        self._client_override = client
        self._cached_client: Any | None = None
        self._sleep: Callable[[float], None] = sleep_fn or time.sleep

        resolved, api_dims = resolve_openai_dimensions(model, dimensions)
        self._dim = resolved
        self._api_dimensions = api_dims

        if client is None:
            # Fail fast on missing dependency at construction when no fake client.
            self._ensure_openai_importable()

    @staticmethod
    def _ensure_openai_importable() -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise EmbeddingConfigError(
                "The 'openai' package is required for the OpenAI embedding "
                "provider. Install it with: uv sync --extra embeddings"
            ) from exc

    @property
    def _client(self) -> Any:
        if self._client_override is not None:
            return self._client_override
        if self._cached_client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise EmbeddingConfigError(
                    "The 'openai' package is required for the OpenAI embedding "
                    "provider. Install it with: uv sync --extra embeddings"
                ) from exc
            kwargs: dict[str, Any] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
                # We implement our own bounded retry + backoff.
                "max_retries": 0,
            }
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._cached_client = OpenAI(**kwargs)
        return self._cached_client

    @property
    def enabled(self) -> bool:
        return True

    @property
    def model_ref(self) -> EmbeddingModelRef:
        return EmbeddingModelRef(
            provider="openai",
            model=self._model,
            dim=self._dim,
            pipeline_version=self._pipeline_version,
        )

    def __repr__(self) -> str:
        return (
            f"OpenAIEmbeddingProvider(model={self._model!r}, dim={self._dim}, "
            f"base_url={self._base_url!r})"
        )

    def _scrub(self, text: str) -> str:
        if self._api_key and self._api_key in text:
            return text.replace(self._api_key, "***")
        return text

    def _wrap_error(self, exc: BaseException) -> EmbeddingError:
        detail = self._scrub(str(exc))
        return EmbeddingError(f"{type(exc).__name__}: {detail}")

    def _is_transient(self, exc: BaseException) -> bool:
        name = type(exc).__name__
        if name in _NON_TRANSIENT_EXC_NAMES:
            return False
        if name in _TRANSIENT_EXC_NAMES:
            return True
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            if status == 429 or status >= 500:
                return True
            if 400 <= status < 500:
                return False
        return False

    def _call_with_retries(self, operation: Callable[[], Any]) -> Any:
        attempt = 0
        while True:
            try:
                return operation()
            except (EmbeddingError, EmbeddingConfigError):
                raise
            except Exception as exc:
                if not self._is_transient(exc) or attempt >= self._max_retries:
                    raise self._wrap_error(exc) from exc
                delay = min(2**attempt, 8) + random.uniform(0.0, 0.25)
                logger.warning(
                    "embedding_retry",
                    attempt=attempt + 1,
                    max_retries=self._max_retries,
                    delay_s=round(delay, 3),
                    error_type=type(exc).__name__,
                )
                self._sleep(delay)
                attempt += 1

    def _prepare_inputs(self, texts: Sequence[str]) -> list[str]:
        # OpenAI rejects empty strings; keep one vector per input.
        return [t if t else " " for t in texts]

    def _verify_vectors(self, vectors: list[list[float]]) -> None:
        expected = self._dim
        for i, vec in enumerate(vectors):
            if len(vec) != expected:
                raise EmbeddingError(
                    f"Embedding length mismatch at index {i}: "
                    f"got {len(vec)}, expected {expected} "
                    f"(model={self._model!r})"
                )

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        prepared = self._prepare_inputs(texts)

        def _once() -> Any:
            kwargs: dict[str, Any] = {
                "model": self._model,
                "input": prepared,
            }
            if self._api_dimensions is not None:
                kwargs["dimensions"] = self._api_dimensions
            return self._client.embeddings.create(**kwargs)

        response = self._call_with_retries(_once)
        data = getattr(response, "data", None)
        if data is None:
            raise EmbeddingError("OpenAI embeddings response missing 'data'")

        # Sort by index — the API does not guarantee input order.
        items = sorted(data, key=lambda item: getattr(item, "index", 0))
        if len(items) != len(texts):
            raise EmbeddingError(
                f"OpenAI returned {len(items)} embeddings for {len(texts)} inputs"
            )

        vectors: list[list[float]] = []
        for item in items:
            embedding = getattr(item, "embedding", None)
            if embedding is None:
                raise EmbeddingError("OpenAI embedding item missing 'embedding'")
            vectors.append([float(x) for x in embedding])

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
                "Query text must be non-blank for OpenAI embedding"
            )
        return self._embed_batch([text])[0]


__all__ = [
    "DEFAULT_OPENAI_MODEL",
    "OpenAIEmbeddingProvider",
    "resolve_openai_dimensions",
]
