# PostgreSQL + pgvector operator guide

Opt-in storage backend for front-design-mcp. SQLite remains the default and has **no** vector search and **no** hybrid search. See [ADR 0005](adr/0005-storage-backend-selection.md) and [ADR 0006](adr/0006-hybrid-search-rrf.md).

## Requirements (verified)

Commands below were run against a live instance on this environment:

| Check | Result |
|-------|--------|
| `SELECT version();` | **PostgreSQL 16.14** (Ubuntu 16.14-0ubuntu0.24.04.1) |
| `SELECT extversion FROM pg_extension WHERE extname='vector';` | **pgvector 0.6.0** |

You need PostgreSQL **16.x** (or compatible) with the **pgvector** extension available to the role that runs migrations.

## Start a database

### Option A — Docker Compose (repo)

`docker-compose.yml` ships a **development-only** service:

- Image: `pgvector/pgvector:pg16`
- Defaults: user/password/db `front_design` / `front_design` / `front_design`
- Bound to `127.0.0.1:5432` only
- Volume: `front_design_pgdata`
- Healthcheck: `pg_isready`

```bash
docker compose up -d
docker compose ps   # wait until healthy
```

Matching app URL (dev credentials — do **not** use in production):

```bash
export FRONT_DESIGN_DATABASE_URL=postgresql://front_design:front_design@127.0.0.1:5432/front_design
```

Stop: `docker compose down` (add `-v` only if you intend to wipe the volume).

### Option B — Existing server

Create a database and role, install the extension (superuser or a role allowed to create extensions):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Point `FRONT_DESIGN_DATABASE_URL` at that database.

## Install the Python extra

```bash
uv sync --extra postgres
# or, with other extras:
uv sync --all-extras
```

This pulls `psycopg[binary]`, `pgvector`, `sqlalchemy`, and `alembic`.

## Configuration

```bash
export FRONT_DESIGN_STORE_BACKEND=postgres
export FRONT_DESIGN_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
```

Notes:

- The `+psycopg` SQLAlchemy dialect suffix is **accepted** and **stripped** for the runtime libpq/psycopg DSN (`Settings.require_database_url` / `_strip_sqlalchemy_driver`). Alembic uses `Settings.sqlalchemy_database_url()`, which re-pins `postgresql+psycopg://`.
- Plain `postgresql://…` also works.
- Passwords are **redacted** in `Settings.redacted_database_url()` (logs / safe error context).
- Related settings (defaults from `config.py`):
  - `FRONT_DESIGN_POSTGRES_STATEMENT_TIMEOUT_MS=15000` — applied as `SET statement_timeout` on connect
  - `FRONT_DESIGN_POSTGRES_POOL_MIN_SIZE=1` / `FRONT_DESIGN_POSTGRES_POOL_MAX_SIZE=4` — present in config; **`PostgresStore` currently uses a single connection + lock** (pooling not wired; `psycopg_pool` is not a declared dependency)

## Migrations

Set the URL (and embedding dimensions **before** the first `upgrade` if you are not using the migration default of 1536):

```bash
export FRONT_DESIGN_DATABASE_URL=postgresql+psycopg://front_design:front_design@127.0.0.1:5432/YOUR_DB
export FRONT_DESIGN_EMBEDDING_DIMENSIONS=1536   # must match the embedding model you will use
```

```bash
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic downgrade base    # drops app tables + helper function; leaves extension
```

### Dimension rule

- Column `embeddings.embedding` is created as `vector(N)` where `N` comes from `FRONT_DESIGN_EMBEDDING_DIMENSIONS` at **migration time**. If unset, the migration uses documented default **1536**.
- The value is written to `store_metadata` under key `embedding_dim`.
- Changing to a model with a **different** dimension requires a **fresh** schema (downgrade/upgrade or new database) and **full re-embedding**. The store fails fast on mismatch.

Exact error raised by `PostgresStore` (constructor / upsert / search):

```text
Embedding dimension mismatch ({context}): schema expects {expected}, got {actual}. Re-run migrations with the correct FRONT_DESIGN_EMBEDDING_DIMENSIONS={expected} (or re-embed with a {expected}-dimensional model).
```

### Verified on a scratch database

Against `front_design_docs_scratch` with `FRONT_DESIGN_EMBEDDING_DIMENSIONS=8`:

1. `uv run alembic upgrade head` → revision `0001_initial`, `vector(8)`, `store_metadata.embedding_dim=8`
2. `uv run alembic downgrade base` → tables dropped
3. `uv run alembic upgrade head` again → same schema (reproducible empty → head cycle)

## Schema overview

| Object | Role |
|--------|------|
| `resources` | Indexed frontend resources (JSONB license/source, `TEXT[]` tags/frameworks/capabilities). Indexes: `source_id`, `kind`, GIN on `tags`. |
| `chunks` | Documentation chunks + `content_sha256`. Generated **`search_vector`** `tsvector` (english) over `title`, `content`, and tags via helper. GIN index `ix_chunks_search_vector`. |
| `embeddings` | One row per chunk: provider/model/dim/pipeline_version/`content_sha256` + `embedding vector(N)`. HNSW index `ix_embeddings_hnsw` on `embedding vector_cosine_ops`; btree on model identity. |
| `store_metadata` | Key/value; includes `embedding_dim`. |
| `front_design_array_to_text(text[])` | **IMMUTABLE** SQL wrapper around `array_to_string`. Exists because `array_to_string` is STABLE in PostgreSQL and **cannot** appear in a `GENERATED` column; the wrapper lets tags participate in the stored tsvector. |
| `alembic_version` | Alembic bookkeeping. |

Downgrade drops tables + the helper function; it **leaves** the `vector` extension installed (other DBs/roles may depend on it).

## Backups and restore

```bash
# Logical dump
pg_dump -Fc -h 127.0.0.1 -U front_design -d YOUR_DB -f front_design.dump

# Restore into an empty database
pg_restore -h 127.0.0.1 -U front_design -d YOUR_DB --clean --if-exists front_design.dump
```

- Chunk **content** is the source of truth for embeddings: vectors are **re-derivable** by re-running the embedding provider over stored chunks, but re-embedding costs **time and (for OpenAI) money**.
- After restoring into a database whose `embedding_dim` / column type **differs** from your current provider: do not mix dimensions. Prefer migrate a clean DB with the correct `FRONT_DESIGN_EMBEDDING_DIMENSIONS`, restore **data** carefully, or truncate `embeddings` and re-embed to match the live schema. Opening `PostgresStore` with a mismatched `FRONT_DESIGN_EMBEDDING_DIMENSIONS` raises the dimension-mismatch error above.

## Troubleshooting

| Symptom | What to do |
|---------|------------|
| `extension 'vector' is not installed` | `CREATE EXTENSION vector;` or run `alembic upgrade head` as a role that can create extensions. Store error also points at this. |
| `schema is incomplete (missing tables: …)` | Run `uv run alembic upgrade head` with `FRONT_DESIGN_DATABASE_URL` set. |
| Dimension mismatch | Align provider dim with `store_metadata.embedding_dim`, or recreate schema + re-embed. |
| Statement timeout | Increase `FRONT_DESIGN_POSTGRES_STATEMENT_TIMEOUT_MS` (ms; `0` disables). Default 15000. |
| `FRONT_DESIGN_DATABASE_URL is required` | Set URL when `FRONT_DESIGN_STORE_BACKEND=postgres`. |
| Import / `postgres` extra missing | `uv sync --extra postgres`. |

## Search capability reminder

With Postgres + a real embedding provider (`openai` or `fastembed`), `SearchService` can run **hybrid** retrieval (RRF). With `FRONT_DESIGN_EMBEDDING_PROVIDER=none` (default), Postgres still provides **lexical** FTS only — not hybrid. SQLite never provides hybrid.
