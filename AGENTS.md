# AGENTS.md

Notes for coding agents working in this repository. Human contributors should read
[CONTRIBUTING.md](CONTRIBUTING.md) first; this file covers the non-obvious setup and
the conventions that are easy to get wrong.

## What this repo is

`front-design-mcp` is a **FastMCP server** (stdio) that gives agents frontend UI/UX
intelligence over an indexed catalog of components, patterns, and motion libraries.
It is a real Python package with two storage backends, not a documentation repo.

It also vendors Anthropic's `mcp-builder` agent skill under `.agents/skills/mcp-builder/`.
**Do not edit that tree or `skills-lock.json` in routine changes** — it is pinned
upstream content.

## Environment

- Python **3.11 or 3.12**. Dependencies are managed with **uv** and pinned in `uv.lock`.
- Canonical setup: `uv sync --all-extras --frozen`. This installs the `dev`, `postgres`,
  and `embeddings` extras. It deliberately does **not** install the heavy local
  embedding provider, which lives in a uv dependency group: `uv sync --group local`.
- `uv` is not always preinstalled on a fresh machine:
  `curl -LsSf https://astral.sh/uv/install.sh | sh` then `export PATH="$HOME/.local/bin:$PATH"`.

### PostgreSQL for the optional backend

Only needed when working on the PostgreSQL/pgvector path. Either `docker compose up -d`
(see `docker-compose.yml`) or a local server with the pgvector extension:

```bash
sudo apt-get install -y postgresql postgresql-16-pgvector
sudo pg_ctlcluster 16 main start
sudo -u postgres psql -c "CREATE ROLE front_design LOGIN PASSWORD 'front_design' SUPERUSER;"
sudo -u postgres createdb -O front_design front_design_test
```

The PostgreSQL tests need `FRONT_DESIGN_TEST_DATABASE_URL` and create their own scratch
databases, so the role must be allowed to `CREATE DATABASE`. Without that variable the
whole PostgreSQL suite **skips**, and `uv run pytest -q` must stay green offline.

## Gotchas that have already bitten people

- **Never export `FRONT_DESIGN_*` into a long-lived shell.** Settings are read from the
  environment and from `.env`, so a stray export silently changes behaviour and test
  outcomes. `tests/conftest.py` strips these variables for the duration of each test
  (keeping only `FRONT_DESIGN_TEST_DATABASE_URL`); pass configuration per command instead.
- **The vector dimension is fixed when the PostgreSQL schema is migrated.** It comes from
  `FRONT_DESIGN_EMBEDDING_DIMENSIONS`, or is derived from the provider and model. There is
  no default and there must never be one — see `src/front_design_mcp/embeddings/dimensions.py`.
- **Changing the embedding model invalidates stored vectors even at the same dimension.**
  The search service refuses the vector branch on a mismatch rather than returning
  meaningless scores. Re-run ingest to re-embed.
- **`fastembed` downloads models from HuggingFace on first use.** Tests must never depend
  on that; use injected fakes.
- Do not import a concrete store anywhere except `store/factory.py`, and do not import the
  `tools` package from retrieval code — that is why framework helpers live in
  `src/front_design_mcp/frameworks.py` rather than under `tools/`.

## Before you open a pull request

```bash
uv sync --all-extras --frozen
uv run ruff check src tests scripts
uv run mypy src/front_design_mcp          # strict mode
uv run pytest -q
uv run python scripts/evaluate_rag.py
uv run python scripts/mcp_smoke.py
```

With PostgreSQL available, also run `uv run pytest -q -m postgres` and confirm
`uv run alembic downgrade base && uv run alembic upgrade head` still works.

## House rules

- **Do not claim a capability the code does not have.** This project was previously
  criticised for advertising hybrid search and an embedding provider that did not exist.
  Anything partial must be labelled partial, in the README, the docs, and tool descriptions.
- **Never invent numbers.** Corpus sizes, tool counts, and benchmark results must be
  measured. `scripts/benchmark_retrieval.py` and `docs/evaluation.md` are the sources.
- Keep SQLite the zero-dependency default; heavy dependencies belong in extras or groups.
- Treat ingested documentation as untrusted input and keep facts separated from inferences.
