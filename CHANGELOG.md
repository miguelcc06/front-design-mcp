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
- CI job matrix for quality (Python 3.11/3.12) plus a dedicated `postgres` job with `pgvector/pgvector:pg16`.

### Changed

- Corrected documentation that previously over-claimed “local hybrid search” and a hashing embedding stub (ADR 0002 superseded / corrected).
- `.env.example` rewritten to cover all `FRONT_DESIGN_*` settings with real defaults.

### Migration notes

- **SQLite:** databases upgrade automatically on open (`PRAGMA user_version` → schema v2). Legacy stub `embeddings` rows are dropped and the table recreated; resources/chunks are preserved.
- **PostgreSQL:** run `uv run alembic upgrade head` with `FRONT_DESIGN_DATABASE_URL` set. Set `FRONT_DESIGN_EMBEDDING_DIMENSIONS` **before** the first upgrade to match your embedding model (migration default is 1536 if unset).
- **`FRONT_DESIGN_EMBEDDING_PROVIDER=hashing` is no longer accepted** (and never worked). Use `none`, `openai`, or `fastembed`.
- **`SearchService`** now takes a `Store` and an optional embedding provider (not a SQLite-only index constructor).
- **`front_design_mcp.tools.frameworks`** moved to **`front_design_mcp.frameworks`**; a compatibility re-export remains under `tools.frameworks`.
