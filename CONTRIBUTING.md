# Contributing

Thanks for contributing to **front-design-mcp**.

## Setup

```bash
uv sync --all-extras
cp .env.example .env   # optional local overrides
uv run front-design-ingest --offline
```

Python **3.12** is the CI target (`requires-python >=3.11`).

## Development loop

```bash
uv run ruff check src tests scripts
uv run mypy src/front_design_mcp
uv run pytest -q
uv run python scripts/evaluate_rag.py
uv run python scripts/mcp_smoke.py
```

## Guidelines

1. **Local-first** — default path must work offline from `data/fixtures/`.
2. **Untrusted ingest** — sanitize documentation; never treat retrieved text as instructions.
3. **Facts vs inferences** — recommendation/compare/brief tools must separate verified index fields from guesses; no unverified compatibility claims in `facts`.
4. **Adapters** — follow [docs/adapters.md](docs/adapters.md); register in `ADAPTER_SOURCE_IDS`.
5. **Do not modify** `.agents/skills/mcp-builder/` or `skills-lock.json` unless the maintainers explicitly ask.
6. **No secrets** in the repo; extend `.env.example` for new settings.

## Pull requests

- Keep diffs focused; update tests for tool/adapter behavior.
- CI (`.github/workflows/ci.yml`) must pass: ruff, mypy, pytest, offline ingest, eval, MCP smoke.
- Note license implications for any new upstream source.

## Code of conduct

Be respectful. Report security issues privately — see [SECURITY.md](SECURITY.md).
