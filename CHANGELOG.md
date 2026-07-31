# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Dual storage backends behind one `Store` interface: **SQLite** (default, offline) and **PostgreSQL + pgvector** (opt-in via `FRONT_DESIGN_STORE_BACKEND=postgres` and the `postgres` extra).
- Alembic migrations for PostgreSQL (`migrations/`, `alembic.ini`), including generated `tsvector`, GIN FTS index, HNSW cosine index, and `store_metadata.embedding_dim`.
- Real embedding providers: `none` (default), `openai` (`embeddings` extra), `fastembed` (`uv sync --group local`), with dimension ownership on the provider, batching/timeouts/bounded retries (OpenAI), and secret scrubbing.
- Embedding cache metadata on the store (`content_sha256` + provider/model/dim/`pipeline_version`); `FRONT_DESIGN_EMBEDDING_PIPELINE_VERSION` for manual invalidation.
- Hybrid retrieval with **Reciprocal Rank Fusion** on PostgreSQL when vectors are available (`SearchService`, `search/rrf.py`); filters applied **before** ranking (including framework → resource-id resolution).
- Store-level transactions, chunk fingerprints, and delete APIs to support incremental sync and pruning.
- Operator docs: `docs/postgres.md`, `docs/embeddings.md`, `docs/deployment.md`, `docs/threat-model-ingestion.md`; ADRs 0005 (storage) and 0006 (RRF); extended `docs/adapters.md`.
- CI job matrix for quality (Python 3.11/3.12) plus a dedicated `postgres` job with `pgvector/pgvector:pg16` that also verifies migrations replay from an empty database.
- `front_design_health` MCP tool reporting the open backend, the effective retrieval mode, whether vector and hybrid search are actually available, the embedding provider, and index counts, with database URLs redacted.
- Retrieval evaluation with Recall@K, MRR, and nDCG@K over 26 hand-labelled English and Spanish queries (`scripts/benchmark_retrieval.py`, `data/eval/`), comparing SQLite/BM25, PostgreSQL lexical, PostgreSQL vector, and PostgreSQL hybrid.
- Guard against querying with a different embedding model than the one that produced the stored vectors: a same-dimension model swap now degrades to lexical search and reports the mismatch instead of returning meaningless similarity scores.

### Changed

- Corrected documentation that previously over-claimed “local hybrid search” and a hashing embedding stub (ADR 0002 superseded / corrected).
- `.env.example` rewritten to cover all `FRONT_DESIGN_*` settings with real defaults.
- README rewritten with measured figures only, and an original SVG banner added.
- Ingest runs one transaction per source instead of committing per row, syncs incrementally by `content_sha256`, prunes records a source stopped producing (never when that source errored), and classifies runs as success, partial, or failed (CLI exit codes 0/1/2).
- `list_resources` applies tag filters in SQL before `LIMIT`/`OFFSET`; previously the filter ran after truncation and could return a falsely empty page.
- PostgreSQL full-text search retries with the conjunction relaxed to a disjunction when the strict `websearch_to_tsquery` matches nothing, so ordinary multi-word queries contribute to fusion.

### Removed

- `FRONT_DESIGN_POSTGRES_POOL_MIN_SIZE` and `FRONT_DESIGN_POSTGRES_POOL_MAX_SIZE`. Connection pooling is not implemented — `PostgresStore` uses a single connection guarded by a lock — and the settings advertised a capability that did not exist.

### Migration notes

- **SQLite:** databases upgrade automatically on open (`PRAGMA user_version` → schema v2). Legacy stub `embeddings` rows are dropped and the table recreated; resources/chunks are preserved.
- **PostgreSQL:** run `uv run alembic upgrade head` with `FRONT_DESIGN_DATABASE_URL` set. The vector column dimension is fixed at migration time, taken from `FRONT_DESIGN_EMBEDDING_DIMENSIONS` or derived from the configured provider and model. There is **no default**: if neither determines it, the migration fails with an actionable error rather than creating a 1536-wide column that would reject every vector.
- **`FRONT_DESIGN_EMBEDDING_PROVIDER=hashing` is no longer accepted** (and never worked). Use `none`, `openai`, or `fastembed`.
- **`SearchService`** now takes a `Store` and an optional embedding provider (not a SQLite-only index constructor).
- **`front_design_mcp.tools.frameworks`** moved to **`front_design_mcp.frameworks`**; a compatibility re-export remains under `tools.frameworks`.
