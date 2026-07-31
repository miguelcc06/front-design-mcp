"""Unit tests for embedding providers (fakes only — no network, no API key)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from front_design_mcp.config import Settings
from front_design_mcp.embeddings.base import (
    EmbeddingConfigError,
    EmbeddingError,
    NullEmbeddingProvider,
)
from front_design_mcp.embeddings.factory import (
    create_embedding_provider,
    describe_provider,
)
from front_design_mcp.embeddings.fastembed_provider import FastEmbedEmbeddingProvider
from front_design_mcp.embeddings.openai_provider import (
    DEFAULT_OPENAI_MODEL,
    OpenAIEmbeddingProvider,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEmbeddingItem:
    def __init__(self, embedding: list[float], index: int) -> None:
        self.embedding = embedding
        self.index = index


class _FakeEmbeddingsResponse:
    def __init__(self, data: list[_FakeEmbeddingItem]) -> None:
        self.data = data


class _FakeEmbeddingsAPI:
    def __init__(
        self,
        *,
        dim: int = 1536,
        fail_times: int = 0,
        fail_exc: Exception | None = None,
        wrong_length: bool = False,
    ) -> None:
        self.dim = dim
        self.fail_times = fail_times
        self.fail_exc = fail_exc or ConnectionError("transient")
        self.wrong_length = wrong_length
        self.calls: list[dict[str, Any]] = []
        self._failures_remaining = fail_times

    def create(
        self,
        *,
        model: str,
        input: Sequence[str],
        dimensions: int | None = None,
    ) -> _FakeEmbeddingsResponse:
        self.calls.append(
            {"model": model, "input": list(input), "dimensions": dimensions}
        )
        if self._failures_remaining > 0:
            self._failures_remaining -= 1
            raise self.fail_exc
        dim = dimensions if dimensions is not None else self.dim
        if self.wrong_length:
            dim = dim + 7
        # Deliberately reverse order to ensure the provider sorts by index.
        items = [
            _FakeEmbeddingItem([float(i)] + [0.0] * (dim - 1), index=i)
            for i in range(len(input))
        ]
        items.reverse()
        return _FakeEmbeddingsResponse(items)


class _FakeOpenAIClient:
    def __init__(self, embeddings: _FakeEmbeddingsAPI) -> None:
        self.embeddings = embeddings


class _FakeFastEmbedModel:
    def __init__(self, dim: int = 384, wrong_length: bool = False) -> None:
        self.dim = dim
        self.wrong_length = wrong_length
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        dim = self.dim + 3 if self.wrong_length else self.dim
        return [[float(i)] + [0.1] * (dim - 1) for i in range(len(texts))]


# ---------------------------------------------------------------------------
# Null provider
# ---------------------------------------------------------------------------


def test_null_provider_disabled() -> None:
    provider = NullEmbeddingProvider()
    assert provider.enabled is False
    assert provider.name == "none"
    assert provider.model_ref.dim == 0


def test_null_embed_documents_raises() -> None:
    provider = NullEmbeddingProvider()
    with pytest.raises(EmbeddingConfigError, match="none"):
        provider.embed_documents(["a"])


def test_null_embed_query_raises() -> None:
    provider = NullEmbeddingProvider()
    with pytest.raises(EmbeddingConfigError, match="lexical"):
        provider.embed_query("hello")


# ---------------------------------------------------------------------------
# OpenAI provider — happy path / batching / dimensions
# ---------------------------------------------------------------------------


def test_openai_embed_documents_preserves_order_across_batches() -> None:
    api = _FakeEmbeddingsAPI(dim=1536)
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        batch_size=2,
        client=_FakeOpenAIClient(api),
    )
    texts = ["a", "b", "c", "d", "e"]
    vectors = provider.embed_documents(texts)
    assert len(vectors) == 5
    assert len(api.calls) == 3  # batches of 2, 2, 1
    # First component encodes the within-batch index; across batches the
    # provider concatenates in input order.
    assert [v[0] for v in vectors] == [0.0, 1.0, 0.0, 1.0, 0.0]
    assert all(len(v) == 1536 for v in vectors)


def test_openai_passes_dimensions_for_embedding_3() -> None:
    api = _FakeEmbeddingsAPI(dim=256)
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        dimensions=256,
        client=_FakeOpenAIClient(api),
    )
    assert provider.model_ref.dim == 256
    vectors = provider.embed_documents(["hello"])
    assert len(vectors[0]) == 256
    assert api.calls[0]["dimensions"] == 256


def test_openai_native_default_dim_is_1536() -> None:
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        client=_FakeOpenAIClient(_FakeEmbeddingsAPI()),
    )
    assert provider.model_ref.dim == 1536
    assert provider.model_ref.provider == "openai"
    assert provider.model_ref.model == "text-embedding-3-small"
    assert provider.enabled is True


def test_openai_dimensions_256_accepted() -> None:
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        dimensions=256,
        client=_FakeOpenAIClient(_FakeEmbeddingsAPI(dim=256)),
    )
    assert provider.model_ref.dim == 256


def test_openai_dimensions_too_large_raises() -> None:
    with pytest.raises(EmbeddingConfigError, match="exceeds native"):
        OpenAIEmbeddingProvider(
            model="text-embedding-3-small",
            api_key="sk-test",
            dimensions=99999,
            client=_FakeOpenAIClient(_FakeEmbeddingsAPI()),
        )


def test_openai_unknown_model_without_dimensions_raises() -> None:
    with pytest.raises(EmbeddingConfigError, match="FRONT_DESIGN_EMBEDDING_DIMENSIONS"):
        OpenAIEmbeddingProvider(
            model="my-custom-embedder-v9",
            api_key="sk-test",
            client=_FakeOpenAIClient(_FakeEmbeddingsAPI()),
        )


def test_openai_ada_002_with_different_dimensions_raises() -> None:
    with pytest.raises(EmbeddingConfigError, match="does not support"):
        OpenAIEmbeddingProvider(
            model="text-embedding-ada-002",
            api_key="sk-test",
            dimensions=256,
            client=_FakeOpenAIClient(_FakeEmbeddingsAPI()),
        )


def test_openai_wrong_length_vector_raises() -> None:
    api = _FakeEmbeddingsAPI(dim=1536, wrong_length=True)
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        client=_FakeOpenAIClient(api),
    )
    with pytest.raises(EmbeddingError, match="length mismatch"):
        provider.embed_documents(["x"])


def test_openai_embed_query_blank_raises() -> None:
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        client=_FakeOpenAIClient(_FakeEmbeddingsAPI()),
    )
    with pytest.raises(EmbeddingConfigError, match="non-blank"):
        provider.embed_query("   ")


def test_openai_empty_string_substituted_with_space() -> None:
    api = _FakeEmbeddingsAPI(dim=1536)
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        client=_FakeOpenAIClient(api),
    )
    vectors = provider.embed_documents([""])
    assert len(vectors) == 1
    assert api.calls[0]["input"] == [" "]


def test_openai_embed_query_success() -> None:
    api = _FakeEmbeddingsAPI(dim=1536)
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        client=_FakeOpenAIClient(api),
    )
    vec = provider.embed_query("search me")
    assert len(vec) == 1536


# ---------------------------------------------------------------------------
# OpenAI provider — retries & secret hygiene
# ---------------------------------------------------------------------------


class _AuthStyleError(Exception):
    """Mimics openai.AuthenticationError without importing openai details."""

    status_code = 401


def test_openai_retries_transient_then_succeeds() -> None:
    sleeps: list[float] = []
    api = _FakeEmbeddingsAPI(dim=1536, fail_times=2, fail_exc=ConnectionError("boom"))
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-test",
        max_retries=3,
        client=_FakeOpenAIClient(api),
        sleep_fn=sleeps.append,
    )
    vectors = provider.embed_documents(["ok"])
    assert len(vectors) == 1
    assert len(api.calls) == 3  # 2 failures + 1 success
    assert len(sleeps) == 2


def test_openai_auth_error_not_retried() -> None:
    sleeps: list[float] = []
    api = _FakeEmbeddingsAPI(
        dim=1536,
        fail_times=5,
        fail_exc=_AuthStyleError("invalid api key sk-super-secret"),
    )
    # Use a different key so scrubbing of fail_exc message is separate.
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key="sk-other",
        max_retries=3,
        client=_FakeOpenAIClient(api),
        sleep_fn=sleeps.append,
    )
    with pytest.raises(EmbeddingError, match="AuthenticationError|_AuthStyleError"):
        provider.embed_documents(["x"])
    assert len(api.calls) == 1
    assert sleeps == []


def test_openai_secret_hygiene_in_error_and_repr() -> None:
    secret = "sk-super-secret"

    class _LeakyError(Exception):
        status_code = 500

    api = _FakeEmbeddingsAPI(
        dim=1536,
        fail_times=10,
        fail_exc=_LeakyError(f"upstream rejected key {secret}"),
    )
    provider = OpenAIEmbeddingProvider(
        model="text-embedding-3-small",
        api_key=secret,
        max_retries=0,
        client=_FakeOpenAIClient(api),
        sleep_fn=lambda _: None,
    )
    with pytest.raises(EmbeddingError) as exc_info:
        provider.embed_documents(["x"])
    assert secret not in str(exc_info.value)
    assert "***" in str(exc_info.value)
    assert secret not in repr(provider)
    assert "text-embedding-3-small" in repr(provider)


# ---------------------------------------------------------------------------
# Factory & describe_provider
# ---------------------------------------------------------------------------


def test_factory_none_returns_null() -> None:
    settings = Settings(embedding_provider="none")
    provider = create_embedding_provider(settings)
    assert isinstance(provider, NullEmbeddingProvider)


def test_factory_openai_without_key_raises() -> None:
    settings = Settings(embedding_provider="openai", embedding_api_key=None)
    with pytest.raises(EmbeddingConfigError, match="FRONT_DESIGN_EMBEDDING_API_KEY"):
        create_embedding_provider(settings)


def test_factory_openai_with_empty_key_raises() -> None:
    settings = Settings(
        embedding_provider="openai",
        embedding_api_key=SecretStr(""),
    )
    with pytest.raises(EmbeddingConfigError, match="FRONT_DESIGN_EMBEDDING_API_KEY"):
        create_embedding_provider(settings)


def test_describe_provider_is_secret_free() -> None:
    provider = OpenAIEmbeddingProvider(
        model=DEFAULT_OPENAI_MODEL,
        api_key="sk-super-secret",
        dimensions=256,
        pipeline_version=2,
        client=_FakeOpenAIClient(_FakeEmbeddingsAPI(dim=256)),
    )
    summary = describe_provider(provider)
    assert set(summary) == {
        "provider",
        "model",
        "dim",
        "pipeline_version",
        "enabled",
    }
    assert summary["provider"] == "openai"
    assert summary["model"] == DEFAULT_OPENAI_MODEL
    assert summary["dim"] == 256
    assert summary["pipeline_version"] == 2
    assert summary["enabled"] is True
    assert "sk-super-secret" not in str(summary)


def test_describe_null_provider() -> None:
    summary = describe_provider(NullEmbeddingProvider())
    assert summary["enabled"] is False
    assert summary["provider"] == "none"
    assert summary["dim"] == 0


# ---------------------------------------------------------------------------
# FastEmbed provider
# ---------------------------------------------------------------------------


def test_fastembed_module_imports_without_package() -> None:
    import front_design_mcp.embeddings.fastembed_provider as mod

    assert mod.FastEmbedEmbeddingProvider is not None
    assert mod.DEFAULT_FASTEMBED_MODEL == "BAAI/bge-small-en-v1.5"


def test_fastembed_missing_dependency_raises() -> None:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("fastembed is installed in this environment")

    with pytest.raises(EmbeddingConfigError, match="uv sync --group local"):
        FastEmbedEmbeddingProvider()


def test_fastembed_with_injected_model() -> None:
    fake = _FakeFastEmbedModel(dim=384)
    provider = FastEmbedEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        model=fake,
        batch_size=2,
    )
    assert provider.enabled is True
    assert provider.model_ref.dim == 384
    vectors = provider.embed_documents(["a", "b", "c"])
    assert len(vectors) == 3
    assert all(len(v) == 384 for v in vectors)
    assert len(fake.calls) == 2  # batches of 2 + 1


def test_fastembed_multilingual_model_dim() -> None:
    fake = _FakeFastEmbedModel(dim=384)
    provider = FastEmbedEmbeddingProvider(
        model_name="intfloat/multilingual-e5-small",
        model=fake,
    )
    assert provider.model_ref.dim == 384


def test_fastembed_unknown_model_without_dimensions_raises() -> None:
    with pytest.raises(EmbeddingConfigError, match="FRONT_DESIGN_EMBEDDING_DIMENSIONS"):
        FastEmbedEmbeddingProvider(
            model_name="totally-unknown/model",
            model=MagicMock(),
        )


def test_fastembed_wrong_length_raises() -> None:
    fake = _FakeFastEmbedModel(dim=384, wrong_length=True)
    provider = FastEmbedEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        model=fake,
    )
    with pytest.raises(EmbeddingError, match="length mismatch"):
        provider.embed_documents(["x"])


def test_fastembed_blank_query_raises() -> None:
    provider = FastEmbedEmbeddingProvider(
        model_name="BAAI/bge-small-en-v1.5",
        model=_FakeFastEmbedModel(),
    )
    with pytest.raises(EmbeddingConfigError, match="non-blank"):
        provider.embed_query("")


def test_factory_fastembed_uses_default_model() -> None:
    # Inject via constructing provider path: factory will try to load fastembed
    # unless we only exercise the Settings→constructor wiring through a mock.
    # When fastembed is absent, construction raises EmbeddingConfigError from
    # the missing package — that is still valid factory behaviour.
    settings = Settings(embedding_provider="fastembed")
    try:
        import fastembed  # noqa: F401
    except ImportError:
        with pytest.raises(EmbeddingConfigError, match="uv sync --group local"):
            create_embedding_provider(settings)
    else:
        provider = create_embedding_provider(settings)
        assert isinstance(provider, FastEmbedEmbeddingProvider)
        assert provider.model_ref.model == "BAAI/bge-small-en-v1.5"
