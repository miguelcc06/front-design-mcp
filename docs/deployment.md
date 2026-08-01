# Deployment

front-design-mcp is a **local-first FastMCP server**. It is **not production-ready** (see below). Supported runtime path today: **stdio MCP** only.

## Local stdio MCP (supported)

Install and ingest offline fixtures, then point your client at the stdio entrypoint:

```bash
uv sync
uv run front-design-ingest --offline
uv run front-design-mcp
```

### Cursor

Add an MCP server that runs the CLI over stdio (adjust the path to your clone):

```json
{
  "mcpServers": {
    "front-design": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/front-design-mcp", "front-design-mcp"],
      "env": {
        "FRONT_DESIGN_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Claude Desktop

Same pattern: `command` + `args` invoking `front-design-mcp` (or `python -m front_design_mcp`) with working directory / `uv --directory` set so `./data` fixtures resolve.

Do not expose the process on a public network interface.

## SQLite deployment (default)

- `FRONT_DESIGN_STORE_BACKEND=sqlite` (default).
- Database file: `FRONT_DESIGN_DB_PATH` or `$FRONT_DESIGN_DATA_DIR/store/front_design.db` (default `./data/store/front_design.db`).
- **Backup:** copy the `.db` file (and `-wal`/`-shm` if present while a process is open; prefer shutting down first).
- **Re-derive:** delete the DB and run `uv run front-design-ingest --offline` — content comes from committed fixtures.
- **Search:** in-process BM25 only. **No vector search. No hybrid search.**

Schema upgrades run automatically on open (`PRAGMA user_version` → v2). See [ADR 0005](adr/0005-storage-backend-selection.md).

## PostgreSQL deployment (opt-in)

1. Provision Postgres + pgvector ([postgres.md](postgres.md)).
2. `uv sync --extra postgres`
3. Set `FRONT_DESIGN_STORE_BACKEND=postgres` and `FRONT_DESIGN_DATABASE_URL`.
4. **Migrations first:** `uv run alembic upgrade head` (set `FRONT_DESIGN_EMBEDDING_DIMENSIONS` to match your embedding model **before** the first upgrade).
5. Ingest: `uv run front-design-ingest --offline` (uses `create_store()`; optional `--backend postgres`). Enable a real embedding provider if you want vectors written during ingest.
6. Run the MCP server with the same env. The MCP tool runtime resolves the configured backend through `create_store()`, so the same PostgreSQL settings are used for ingestion and tool serving.

Notes:

- Shared read-mostly consumers are plausible once data is loaded; the current `PostgresStore` uses a **single connection** with a lock (pool settings in config are **not** applied yet).
- `FRONT_DESIGN_POSTGRES_STATEMENT_TIMEOUT_MS` (default 15000) caps statements.
- Hybrid search needs a real embedding provider (`openai` or `fastembed`) plus populated `embeddings` rows. With `none`, Postgres is lexical FTS only.

## Health / readiness

| Mechanism | What it reports |
|-----------|-----------------|
| MCP tool `front_design_ping` | Package name/version, offline vs network-ingest-enabled mode, configured embedding provider name, `status=ok`, `resources_indexed` |
| MCP tool `front_design_health` | Reports **backend**, **effective search mode**, and **index counts** (resources/chunks/embeddings as provided by the runtime). Prefer this for ops-style checks when available. |

Empty SQLite DBs may auto-ingest offline fixtures on first tool use (`tools/runtime.ensure_ready`).

## HTTP transport

The server ships **stdio only** today (`mcp.run()` with no HTTP app).

- **No HTTP transport** is implemented.
- **No authentication** layer is implemented.
- If HTTP is added later, it **must** require authentication and **must not** be exposed publicly by default.

## Operations

| Task | How |
|------|-----|
| Re-ingest / sync | `uv run front-design-ingest --offline` (defaults: `--prune`, `--embed`). Online only with `FRONT_DESIGN_ENABLE_NETWORK_INGEST=true` |
| Prune stale rows | Default `--prune`: per source, deletes store resources/chunks absent from the latest catalog (skipped if that source’s fetch failed) |
| Skip embeddings | `--no-embed`, or leave `FRONT_DESIGN_EMBEDDING_PROVIDER=none` (sync is a no-op / skipped on backends without vector search) |
| Re-embed after model/dim change | Align `FRONT_DESIGN_EMBEDDING_*` with schema dim; bump `FRONT_DESIGN_EMBEDDING_PIPELINE_VERSION` if chunking changed; re-run ingest with embed; on dim change recreate Postgres schema ([postgres.md](postgres.md)) |
| Backup SQLite | Copy DB file |
| Backup Postgres | `pg_dump` / `pg_restore` |

### CLI exit codes (`front-design-ingest`)

As implemented in `cli_ingest.py` / `SyncOutcome`:

| Code | Meaning |
|------|---------|
| **0** | `SyncOutcome.SUCCESS` — every source succeeded, no item/embedding batch errors, store has resources |
| **1** | `SyncOutcome.FAILED` (or uncaught exception) — nothing usable / all sources failed / empty store |
| **2** | `SyncOutcome.PARTIAL` — some sources or items failed while others succeeded |

**Also exit 2:** `--online` while `FRONT_DESIGN_ENABLE_NETWORK_INGEST=false` (guard before ingest runs). Same numeric code as PARTIAL — distinguish via stderr message vs `outcome` in `--json` output.

## Not production ready — missing pieces

This project is **Development Status :: 3 - Alpha**. At minimum, production would still need:

- HTTP transport **with** authentication (if remote access is required) — or a clear decision to stay stdio-only behind a trusted host
- SSRF hardening for network ingest ([threat-model-ingestion.md](threat-model-ingestion.md))
- Connection pooling / multi-instance story for Postgres
- Tuned RRF weights and an evaluation gate you trust (do not invent metrics)
- Operational runbooks for credential rotation, backup restore drills, and embedding cost controls

Use it as a **local agent sidecar**, not as an internet-facing service.
