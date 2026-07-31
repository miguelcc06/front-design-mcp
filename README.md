<div align="center">
  <img src="./assets/banner.svg" width="100%" alt="front-design-mcp banner" />

  <br />
  <br />

  # 🎨 front-design-mcp

  **Local-first FastMCP server that gives AI agents frontend UI/UX intelligence**

  <p align="center">
    <img src="https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+" />
    <img src="https://img.shields.io/badge/FastMCP-3.4.5-00C7B7?style=for-the-badge" alt="FastMCP 3.4.5" />
    <img src="https://img.shields.io/badge/SQLite-default-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
    <img src="https://img.shields.io/badge/PostgreSQL-15+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 15+" />
    <img src="https://img.shields.io/badge/pgvector-optional-336791?style=for-the-badge" alt="pgvector" />
    <img src="https://img.shields.io/badge/License-Apache%202.0-D22128?style=for-the-badge" alt="Apache-2.0" />
  </p>
</div>

---

> **front-design-mcp** indexes offline frontend catalogs (components, patterns, motion libraries) and exposes discover / search / compare / recommend tools over **stdio** MCP — SQLite + BM25 by default, with optional PostgreSQL + pgvector hybrid search when you add an embedding provider.

## ✨ Key Features

* 📦 **Offline by default** — SQLite + BM25 needs no PostgreSQL, no API key, and no network
* 🧰 **10 MCP tools** — discover, search, details, compare, recommend, find components/animations, and build implementation briefs
* 📚 **Measured corpus** — **90** resources / **221** chunks from **6** sources (fixtures under `data/fixtures/`)
* 🐘 **Optional PostgreSQL + pgvector** — lexical (`tsvector`), vector, and hybrid (RRF) when an embedding provider is configured
* 🔐 **Agent-safe outputs** — provenance, licenses, and a clear split between **facts** and **inferences**
* 🔄 **Incremental ingest** — content-hash sync, optional prune, embedding reuse; exit codes `0` / `1` / `2` (partial)
* 🔌 **stdio only** — no HTTP transport and no authentication are implemented (not production ready)

## 🏗️ Architecture

```mermaid
flowchart LR
  Client[MCP client] --> Server[FastMCP server]
  Server --> Handlers[Tool handlers]
  Handlers --> Search[SearchService]
  Search --> BM25[BM25 in-process]
  Search --> PGSearch[PostgreSQL tsvector + pgvector]
  BM25 --> StoreIface[Store interface]
  PGSearch --> StoreIface
  StoreIface --> Sqlite[SqliteStore]
  StoreIface --> Postgres[PostgresStore]
  Ingest[front-design-ingest CLI] --> Adapters[Source adapters]
  Adapters --> Fixtures[Fixtures]
  Adapters --> StoreIface
  Embed[Embedding provider] --> PGSearch
```

## 🔀 Storage & Search Modes

**SQLite + BM25 is the default** and needs no PostgreSQL, no API key, and no network.

**Vector and hybrid search require both PostgreSQL + pgvector and an embedding provider.** SQLite mode has neither. Hybrid search only applies in that PostgreSQL + provider configuration — call `front_design_health` to see whether hybrid is actually active.

| | SQLite (default) | PostgreSQL + pgvector |
|---|---|---|
| External services | None | PostgreSQL **15+** with the pgvector extension (verified on **16.14** + pgvector **0.6.0**) |
| Extra dependencies | None beyond the base install | `uv sync --extra postgres` (`psycopg` 3.3.4, `pgvector` 0.5.0, Alembic 1.18.5, SQLAlchemy 2.x) |
| Lexical strategy | In-process BM25 (`rank-bm25` 0.2.2); corpus rebuilt in memory at startup | PostgreSQL `tsvector` / `websearch_to_tsquery` (`english` config) |
| Vector search | No | Yes, when an embedding provider is configured |
| Hybrid / RRF | No | Yes, when vector search is available (`SEARCH_MODE=auto` → hybrid) |
| Migrations | Automatic SQLite schema on open | Alembic (`uv run alembic upgrade head`); vector dimension fixed at migration time |
| Filters | `source_id`, `kind`, tags, resource ids | Same filters, pushed into SQL |
| Best for | Local / offline agents, zero infra | Semantic + hybrid retrieval with a chosen embedding model |

### Measured retrieval quality

26 hand-labelled English+Spanish queries, corpus 90/221, `rrf_k=60`, `fastembed` / `BAAI/bge-small-en-v1.5` / 384 dims:

| config | Recall@10 | MRR@10 | nDCG@10 |
|---|---|---|---|
| sqlite-bm25 | 0.696 | 0.826 | 0.701 |
| postgres-lexical | 0.710 | 0.810 | 0.709 |
| postgres-vector | 0.884 | 0.870 | 0.813 |
| postgres-hybrid | 0.862 | 0.899 | 0.823 |

With `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dims) instead: postgres-vector **0.870 / 0.822 / 0.770** and postgres-hybrid **0.899 / 0.920 / 0.846**.

> ⚠️ **Caveat:** 26 hand-labelled queries on a 90-resource corpus is far too small for statistical significance. Latency figures are deliberately omitted here because they are single-machine, tiny-corpus numbers — see [docs/evaluation.md](docs/evaluation.md).

## 📋 Requirements

* **Python** 3.11 or 3.12 (`requires-python >= 3.11`)
* **Package** `0.1.0`, licence **Apache-2.0**
* **Pinned core:** FastMCP **3.4.5**, mcp 1.29.0, pydantic 2.13.4, rank-bm25 0.2.2
* **Default path:** no database server, no API key, no network
* **Optional PostgreSQL path:** PostgreSQL **15+** with the [pgvector](https://github.com/pgvector/pgvector) extension (tested on **16.14** + pgvector **0.6.0**)
* **Optional embeddings:** OpenAI-compatible API (`--extra embeddings`) or local fastembed (`uv sync --group local`)

## 🚀 Quick Start (SQLite, default)

```bash
uv sync --all-extras
uv run front-design-ingest --offline
uv run front-design-mcp
# equivalent:
# uv run python -m front_design_mcp
```

This writes a SQLite store under `./data/store/` (or `FRONT_DESIGN_DATA_DIR`) and starts the MCP server on **stdio**. No PostgreSQL, no API key, no network.

## 🐘 PostgreSQL + pgvector Setup

Opt-in path for lexical + vector + hybrid retrieval.

### 1. Start PostgreSQL (dev Compose)

[`docker-compose.yml`](docker-compose.yml) ships a **development-only** `pgvector/pgvector:pg16` service (user/password/db `front_design` / `front_design` / `front_design`, bound to `127.0.0.1:5432`):

```bash
docker compose up -d
docker compose ps   # wait until healthy
```

> 💡 Those credentials are **dev defaults only** — do not use them in production.

### 2. Install extras and configure

```bash
uv sync --extra postgres
# For local embeddings also:
# uv sync --extra postgres --group local
# Or with everything:
# uv sync --all-extras --group local
```

```bash
export FRONT_DESIGN_STORE_BACKEND=postgres
export FRONT_DESIGN_DATABASE_URL=postgresql+psycopg://front_design:front_design@127.0.0.1:5432/front_design

# Choose an embedding provider BEFORE migrating (dimension is fixed at migration time).
export FRONT_DESIGN_EMBEDDING_PROVIDER=fastembed
export FRONT_DESIGN_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
# OpenAI alternative:
# export FRONT_DESIGN_EMBEDDING_PROVIDER=openai
# export FRONT_DESIGN_EMBEDDING_MODEL=text-embedding-3-small
# export FRONT_DESIGN_EMBEDDING_API_KEY=YOUR_OPENAI_API_KEY_HERE
```

> ⚠️ The `embeddings.embedding` column is created as `vector(N)` from the configured provider/model (or an explicit `FRONT_DESIGN_EMBEDDING_DIMENSIONS`). There is no default: if the dimension cannot be derived, the migration fails rather than guessing. Changing to a different dimension later requires a fresh schema and a full re-embed.

> 🛡️ Switching to a **different model of the same dimension** passes every dimension check but makes similarity scores meaningless. The server compares the configured model against the identities actually stored, and if they disagree it skips the vector branch, answers with lexical search, and reports the mismatch through `front_design_health` instead of returning plausible-looking nonsense. Re-run ingest to re-embed.

### 3. Migrate and ingest

```bash
uv run alembic upgrade head
uv run front-design-ingest --offline
uv run front-design-mcp
```

Confirm hybrid is live with the `front_design_health` tool (`capabilities.hybrid_search` / `search.effective_mode`).

## ⚙️ Configuration

All settings use the `FRONT_DESIGN_` prefix (see `.env.example` and `src/front_design_mcp/config.py`). There are **no** connection-pool settings — pooling is not implemented.

### Core

| Variable | Default | Meaning |
|---|---|---|
| `FRONT_DESIGN_DATA_DIR` | `None` (→ `./data`) | Root for fixtures, cache, and store artifacts |
| `FRONT_DESIGN_DB_PATH` | `None` (→ `$DATA_DIR/store/front_design.db`) | SQLite database path |
| `FRONT_DESIGN_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `FRONT_DESIGN_HTTP_TIMEOUT` | `30.0` | HTTP timeout (seconds) for network ingest |
| `FRONT_DESIGN_ENABLE_NETWORK_INGEST` | `false` | Allow `--online` ingest |

### Storage

| Variable | Default | Meaning |
|---|---|---|
| `FRONT_DESIGN_STORE_BACKEND` | `sqlite` | `sqlite` \| `postgres` |
| `FRONT_DESIGN_DATABASE_URL` | `None` | Required for postgres (`postgresql://` or `postgresql+psycopg://`) |
| `FRONT_DESIGN_POSTGRES_STATEMENT_TIMEOUT_MS` | `15000` | Statement timeout; `0` disables |

### Embeddings

| Variable | Default | Meaning |
|---|---|---|
| `FRONT_DESIGN_EMBEDDING_PROVIDER` | `none` | `none` \| `openai` \| `fastembed` |
| `FRONT_DESIGN_EMBEDDING_MODEL` | `None` | Provider default when unset |
| `FRONT_DESIGN_EMBEDDING_DIMENSIONS` | `None` | Optional override; must match the model |
| `FRONT_DESIGN_EMBEDDING_API_KEY` | `None` | Required for `openai` |
| `FRONT_DESIGN_EMBEDDING_BASE_URL` | `None` | OpenAI-compatible base URL override |
| `FRONT_DESIGN_EMBEDDING_BATCH_SIZE` | `32` | Embed batch size |
| `FRONT_DESIGN_EMBEDDING_TIMEOUT` | `30.0` | Provider timeout (seconds) |
| `FRONT_DESIGN_EMBEDDING_MAX_RETRIES` | `3` | Provider retry count |
| `FRONT_DESIGN_EMBEDDING_PIPELINE_VERSION` | `1` | Bump to force re-embedding after chunking changes |

**Providers**

| Provider | Install | Models (native dims) |
|---|---|---|
| `none` | (default) | Vector search disabled |
| `openai` | `uv sync --extra embeddings` | `text-embedding-3-small` 1536, `text-embedding-3-large` 3072, `text-embedding-ada-002` 1536 |
| `fastembed` | `uv sync --group local` | `BAAI/bge-small-en-v1.5` 384 (default), `sentence-transformers/all-MiniLM-L6-v2` 384, `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 384, `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` 768, `intfloat/multilingual-e5-large` 1024 |

### Search

| Variable | Default | Meaning |
|---|---|---|
| `FRONT_DESIGN_SEARCH_MODE` | `auto` | `auto` \| `lexical` \| `vector` \| `hybrid` (`auto` → hybrid when backend + embeddings allow it, else lexical) |
| `FRONT_DESIGN_RRF_K` | `60` | Reciprocal Rank Fusion smoothing constant |
| `FRONT_DESIGN_RRF_LEXICAL_WEIGHT` | `1.0` | Lexical branch weight (untuned) |
| `FRONT_DESIGN_RRF_VECTOR_WEIGHT` | `1.0` | Vector branch weight (untuned) |
| `FRONT_DESIGN_SEARCH_CANDIDATES` | `50` | Per-branch candidate pool before fusion |

## 🧰 MCP Tools Available

| Tool | Purpose |
|------|---------|
| `front_design_ping` | Liveness — version, backend, embedding provider, indexed resource count |
| `front_design_health` | Readiness — effective retrieval mode, hybrid/vector availability, counts |
| `discover_frontend_resources` | Browse/filter the catalog (kind, framework, tags, license, …) |
| `search_frontend_knowledge` | Search documentation chunks (BM25 or hybrid depending on config) |
| `get_resource_details` | Full resource + related chunks by `id` |
| `compare_frontend_options` | Compare options by id/name; separates facts from inferences |
| `recommend_frontend_stack` | Stack suggestion from requirements + constraints |
| `find_components` | Intent → components/patterns |
| `find_animation_patterns` | Motion patterns with a11y / cost notes when known |
| `build_frontend_brief` | Implementation brief from a product description |

Also registered:

| Kind | Name |
|------|------|
| Resource | `front-design://sources` |
| Resource template | `front-design://resource/{id}` |
| Prompt | `frontend_implementation_brief` |

## 🔌 Client configuration

Copy the examples under [`configs/`](configs/) and replace `/absolute/path/to/front-design-mcp` with your clone path.

### Cursor / Claude Desktop — SQLite (default)

```json
{
  "mcpServers": {
    "front_design_mcp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/front-design-mcp",
        "python",
        "-m",
        "front_design_mcp"
      ],
      "env": {
        "FRONT_DESIGN_LOG_LEVEL": "INFO",
        "FRONT_DESIGN_ENABLE_NETWORK_INGEST": "false",
        "FRONT_DESIGN_EMBEDDING_PROVIDER": "none"
      }
    }
  }
}
```

### Cursor / Claude Desktop — PostgreSQL + embeddings

```json
{
  "mcpServers": {
    "front_design_mcp": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/front-design-mcp",
        "python",
        "-m",
        "front_design_mcp"
      ],
      "env": {
        "FRONT_DESIGN_LOG_LEVEL": "INFO",
        "FRONT_DESIGN_ENABLE_NETWORK_INGEST": "false",
        "FRONT_DESIGN_STORE_BACKEND": "postgres",
        "FRONT_DESIGN_DATABASE_URL": "postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DBNAME",
        "FRONT_DESIGN_EMBEDDING_PROVIDER": "fastembed",
        "FRONT_DESIGN_EMBEDDING_MODEL": "BAAI/bge-small-en-v1.5"
      }
    }
  }
}
```

For OpenAI embeddings, set `FRONT_DESIGN_EMBEDDING_PROVIDER` to `openai`, pick a model, and set `FRONT_DESIGN_EMBEDDING_API_KEY` to `YOUR_OPENAI_API_KEY_HERE` (never commit a real key).

Example files: [`configs/cursor.mcp.json.example`](configs/cursor.mcp.json.example), [`configs/claude-desktop.mcp.json.example`](configs/claude-desktop.mcp.json.example).

## 💻 CLI Quick Reference

```bash
# Server (stdio)
uv run front-design-mcp
uv run python -m front_design_mcp

# Ingest (exit 0=success, 1=failed, 2=partial)
uv run front-design-ingest --offline
uv run front-design-ingest --online          # requires ENABLE_NETWORK_INGEST=true
uv run front-design-ingest --offline --source shadcn
uv run front-design-ingest --offline --prune
uv run front-design-ingest --offline --no-prune
uv run front-design-ingest --offline --embed
uv run front-design-ingest --offline --no-embed
uv run front-design-ingest --offline --backend sqlite
uv run front-design-ingest --offline --backend postgres
uv run front-design-ingest --offline --json

# Migrations (postgres)
uv run alembic upgrade head
uv run alembic current
uv run alembic history
uv run alembic downgrade base

# Evaluation
uv run python scripts/evaluate_rag.py
uv run python scripts/benchmark_retrieval.py --markdown
uv run python scripts/benchmark_retrieval.py --config sqlite-bm25 --json
uv run python scripts/mcp_smoke.py
```

## 🔄 Ingestion & Sync

* **Offline fixtures** are the default (`--offline`). Network ingest is **off** until `FRONT_DESIGN_ENABLE_NETWORK_INGEST=true`.
* Chunks are written **incrementally** when any persisted field changes (title, content, tags, URL, version, licence — not only `content_sha256`). Adapter-stamped `last_indexed_at` alone does not force a rewrite.
* **`--prune`** (default) deletes store rows that disappeared from a source. A source whose adapter **errored**, or that had **any item-level normalization failure**, is never pruned (a partial catalog is not authoritative); the report records `prune_skipped_reason` and the run is `partial`.
* With an embedding provider, `--embed` (default) generates vectors for changed embedded text (`title + content`) and **reuses** embeddings when that fingerprint + model identity still match; tag/URL/licence-only edits do not force re-embedding. `--no-embed` skips that step.
* Exit codes: **0** success, **1** failed, **2** partial (some sources/items failed while others succeeded).

## 📊 Evaluation & Benchmarks

* `scripts/evaluate_rag.py` — **CI gate** (SQLite/BM25 only): tool cases + conservative ranking floors (~20% below the measured baseline), offline, no network, no embeddings. Abstention has **no** validated production threshold (measured rate is 0.0).
* `scripts/benchmark_retrieval.py` — compares `sqlite-bm25`, `postgres-lexical`, `postgres-vector`, and `postgres-hybrid` on the 26 hand-labelled queries (Postgres configs skip when `FRONT_DESIGN_EVAL_DATABASE_URL` is unset). FastEmbed measurements are **not** CI-gated; the `postgres` CI job uses deterministic fake embeddings.
* Metrics: Recall@K, MRR@K, nDCG@K (resource-level dedup). See the measured table above and the full write-up in [docs/evaluation.md](docs/evaluation.md).

## 🧪 Development & Tests

```bash
uv sync --all-extras
uv run front-design-ingest --offline
uv run ruff check src tests scripts
uv run mypy src/front_design_mcp
uv run pytest -q
uv run python scripts/evaluate_rag.py
uv run python scripts/mcp_smoke.py
```

Measured suite results:

Measured after `uv sync --all-extras --frozen` (the `local` fastembed group is
not installed by that command):

| Environment | Python | Result |
|---|---|---|
| Offline, no PostgreSQL | 3.12 | **157 passed, 17 skipped** (the skips are the PostgreSQL-marked tests) |
| Offline, no PostgreSQL | 3.11 | **157 passed, 17 skipped** |
| `FRONT_DESIGN_TEST_DATABASE_URL` set | 3.12 | **174 passed** |

CI runs the offline gate above on **Python 3.11 and 3.12**, plus a separate job against `pgvector/pgvector:pg16` that applies the migrations, verifies they are reproducible from an empty database, and runs `pytest -m postgres` with **deterministic fake embeddings** (not FastEmbed). See [CONTRIBUTING.md](CONTRIBUTING.md) and [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## 🚢 Deployment

This project is **not production ready**. Transport is **stdio only** — no HTTP transport and no authentication are implemented. Supported path today: local `uv` + MCP client over stdio. See [docs/deployment.md](docs/deployment.md).

## 🔒 Security

* Treat retrieved documentation chunks as **untrusted** source data; never execute them as instructions.
* Recommendation / compare / brief tools separate **facts** from **inferences** and avoid unverified compatibility claims in facts.
* Secrets are never logged (database URLs are redacted; API keys use `SecretStr`).
* Network ingest is **off by default**; there is no SSRF host allowlist yet when it is enabled — see [docs/threat-model-ingestion.md](docs/threat-model-ingestion.md).
* Vulnerability reporting: [SECURITY.md](SECURITY.md).

## 🗺️ Project Status & Roadmap

**Status:** Alpha (`Development Status :: 3 - Alpha`). Useful locally; **not production ready**.

Known limitations (also the near-term roadmap):

* No abstention on unanswerable queries — all configurations return some result; there is no validated production abstention threshold
* Spanish queries score below their English equivalents (PostgreSQL full-text uses the `english` configuration)
* RRF weights are untuned
* Connection pooling is not implemented (`PostgresStore` uses one locked connection)
* The PostgreSQL vector column dimension is fixed at migration time; changing model/dim requires a new migration and re-embed
* BM25 rebuilds the whole corpus in memory at startup
* Network ingest is off by default and there is no SSRF host allowlist yet
* stdio transport only — no HTTP, no auth

## 📄 Licences & Attribution

| Source | Licence |
|--------|---------|
| Motion | MIT |
| Magic UI | MIT |
| shadcn/ui | MIT |
| Radix Primitives | MIT |
| GSAP | Standard No Charge — **metadata only, not redistributable** |
| Curated patterns | Internal MIT metadata linking to upstream docs |

This project is **Apache-2.0** ([LICENSE](LICENSE)). Upstream catalogs keep their own licences. Offline corpus (measured): motion 12/24, magicui 26/52, shadcn 25/75, radix 11/22, gsap 9/27, curated 7/21 (resources/chunks).

## Docs index

| Document | Purpose |
|----------|---------|
| [docs/adapters.md](docs/adapters.md) | How to add a SourceAdapter |
| [docs/deployment.md](docs/deployment.md) | Local stdio deployment notes |
| [docs/embeddings.md](docs/embeddings.md) | Embedding providers and dimensions |
| [docs/evaluation.md](docs/evaluation.md) | RAG evaluation & benchmarks |
| [docs/github.md](docs/github.md) | Suggested GitHub description/topics |
| [docs/orchestration.md](docs/orchestration.md) | Package plan and acceptance notes |
| [docs/postgres.md](docs/postgres.md) | PostgreSQL + pgvector operator guide |
| [docs/research.md](docs/research.md) | Research notes & source facts |
| [docs/threat-model-ingestion.md](docs/threat-model-ingestion.md) | Ingestion threat model |
| [docs/adr/0001-fastmcp-stable.md](docs/adr/0001-fastmcp-stable.md) | ADR: FastMCP |
| [docs/adr/0002-local-hybrid-search.md](docs/adr/0002-local-hybrid-search.md) | ADR: local hybrid search |
| [docs/adr/0003-source-selection.md](docs/adr/0003-source-selection.md) | ADR: source selection |
| [docs/adr/0004-untrusted-ingestion.md](docs/adr/0004-untrusted-ingestion.md) | ADR: untrusted ingestion |
| [docs/adr/0005-storage-backend-selection.md](docs/adr/0005-storage-backend-selection.md) | ADR: storage backend |
| [docs/adr/0006-hybrid-search-rrf.md](docs/adr/0006-hybrid-search-rrf.md) | ADR: hybrid search / RRF |
| [AGENTS.md](AGENTS.md) | Setup notes and house rules for coding agents |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Dev setup & PR guidelines |
| [SECURITY.md](SECURITY.md) | Vulnerability reporting |
| [CHANGELOG.md](CHANGELOG.md) | Release notes |
| [`.env.example`](.env.example) | Environment template |

---

<div align="center">
  <i>Built so agents can discover components, cite sources, and stay honest about what they know.</i><br />
  <b>License: Apache-2.0</b>
</div>
