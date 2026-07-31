# Embeddings

How front-design-mcp turns chunk text into vectors (or explicitly declines to).

SQLite mode has **no vector search** even if you persist blobs in the local `embeddings` table — retrieval there is BM25 only. Vector / hybrid search requires the PostgreSQL backend ([ADR 0005](adr/0005-storage-backend-selection.md), [ADR 0006](adr/0006-hybrid-search-rrf.md)).

## Provider interface

`EmbeddingProvider` (`embeddings/base.py`):

- `enabled` — `False` for the null provider; callers must use lexical search.
- `model_ref` — `EmbeddingModelRef(provider, model, dim, pipeline_version)`.
- `embed_documents(texts)` / `embed_query(text)`.

**The provider owns the dimension.** Nothing in the package hardcodes a silent 1536 for unknown models. The Postgres schema dimension comes from migration-time `FRONT_DESIGN_EMBEDDING_DIMENSIONS` and must match `provider.model_ref.dim`.

Factory: `create_embedding_provider(settings)` in `embeddings/factory.py`.

## Providers

| Name | Install | Network | Notes |
|------|---------|---------|-------|
| `none` | (default, no extra) | No | No vectors. `NullEmbeddingProvider`. |
| `openai` | `uv sync --extra embeddings` | Yes — sends chunk/query text to the API host | Needs `FRONT_DESIGN_EMBEDDING_API_KEY` |
| `fastembed` | `uv sync --group local` (**not** an extra; not installed by `--all-extras`) | No (model download on first use) | Fully local ONNX via fastembed |

### `openai` models and native dimensions

From `embeddings/openai_provider.py` (do not invent others):

| Model | Native dim | Truncation via API `dimensions=` |
|-------|------------|----------------------------------|
| `text-embedding-3-small` (default) | 1536 | Yes (must be ≤ native) |
| `text-embedding-3-large` | 3072 | Yes |
| `text-embedding-ada-002` | 1536 | No — requested dim must equal native |

Optional: `FRONT_DESIGN_EMBEDDING_BASE_URL` for OpenAI-compatible endpoints.

### `fastembed` models and dimensions

From `embeddings/fastembed_provider.py`:

| Model | Dim | Notes |
|-------|-----|-------|
| `BAAI/bge-small-en-v1.5` (default) | 384 | English; smallest download |
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | English |
| `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | 384 | Multilingual |
| `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` | 768 | Multilingual, larger |
| `intfloat/multilingual-e5-large` | 1024 | Multilingual, largest |

Every entry was checked against `TextEmbedding.list_supported_models()`; a model
listed here that fastembed does not serve would fail during ingest rather than at
configuration time.

FastEmbed dimensions are **fixed** per model, so an override that disagrees is an
error. A multilingual model is worth considering because this project answers
Spanish queries while the PostgreSQL full-text index uses the `english` text
search configuration — but note that changing model changes the dimension, which
requires a fresh migration and a full re-embed (see `docs/postgres.md`).

## Dimension resolution

Rules as implemented:

1. **Known model, no override** → use the table’s native dimension.
2. **Unknown model, no override** → **error**. Never silently assume 1536 (OpenAI) or any default (FastEmbed).
3. **Unknown model + explicit `FRONT_DESIGN_EMBEDDING_DIMENSIONS`** → trust the caller (OpenAI may still pass `dimensions=` only for `text-embedding-3-*`).
4. **Known `text-embedding-3-*` + override** → override must be ≥ 1 and ≤ native.
5. **Known non-truncatable model + override ≠ native** → error.
6. **FastEmbed known model + override ≠ native** → error.

## Cache / when to recompute

Ingest calls `ingest/embedding_sync.sync_embeddings` after each source commit (when `--embed` and the provider is enabled). Text embedded per chunk is:

```text
{chunk.title}\n\n{chunk.content}
```

Cache hit when stored `EmbeddingMeta.matches(embedder.model_ref, chunk.content_sha256)` — i.e. **all** of:

- `content_sha256`
- `provider`
- `model`
- `dim`
- `pipeline_version`

On a hit the vector is **reused** (not rewritten). On backends with `vector_search=False` (SQLite), sync **skips** generation and counts chunks as skipped.

`FRONT_DESIGN_EMBEDDING_PIPELINE_VERSION` (default `1`) is the **manual invalidation lever**: bump it after chunking/normalization changes to force re-embedding even when text hashes are unchanged. Stale rows from another model identity can be removed with `delete_embeddings(not_matching=…)`.

Note: the cache key uses `content_sha256` of the stored chunk body, while the embedded string also includes the title. If you change titles without changing content, hashes may not invalidate — bump `pipeline_version` or adjust chunking if that matters.

## Batching, timeouts, retries (OpenAI)

| Setting | Default | Meaning |
|---------|---------|---------|
| `FRONT_DESIGN_EMBEDDING_BATCH_SIZE` | 32 | Texts per API/local batch |
| `FRONT_DESIGN_EMBEDDING_TIMEOUT` | 30.0 s | Client timeout (OpenAI) |
| `FRONT_DESIGN_EMBEDDING_MAX_RETRIES` | 3 | Bounded retries on **transient** failures |

Retried (by exception name / status): connection/timeouts, rate limits (429), 5xx, and named transient OpenAI errors (`APIConnectionError`, `RateLimitError`, …). **Not** retried: auth, permission, bad request, not found, config errors, other 4xx. Backoff: `min(2**attempt, 8) + jitter`.

Empty corpus strings are substituted with a single space before the OpenAI API (endpoint rejects empty inputs); callers still get one vector per input. FastEmbed keeps empty strings as-is for the local model.

## Secret hygiene

- API keys are `SecretStr` in settings.
- OpenAI provider `repr` omits the key.
- Exception messages scrub the key substring (`***`).
- Retries log `error_type` only, not response bodies with credentials.

## Cost and privacy

| Provider | Chunk text leaves the machine? |
|----------|--------------------------------|
| `none` | No |
| `fastembed` | No |
| `openai` | **Yes** — third-party API (or your `base_url` host) |

## Degradation

With `FRONT_DESIGN_EMBEDDING_PROVIDER=none` (default), or when the vector branch fails / embeddings are missing, `SearchService` answers with **lexical** search and records notes / `degraded=True` when hybrid or vector was requested ([ADR 0006](adr/0006-hybrid-search-rrf.md)).
