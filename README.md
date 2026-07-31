# front-design-mcp

FastMCP server that gives AI agents specialized frontend UI/UX intelligence — discover frameworks, components, animations, patterns, and templates with citations.

> **Status:** Work in progress (v0.1.0 scaffold). Foundation only — adapters, ingest, and MCP tools land in later packages.

## Quick start (dev)

```bash
uv sync --all-extras
uv run front-design-mcp
# or
uv run python -m front_design_mcp
```

Ingest CLI stub:

```bash
uv run front-design-ingest --help
```

## Docs

| Document | Purpose |
|----------|---------|
| [docs/research.md](docs/research.md) | Research notes & source facts |
| [docs/orchestration.md](docs/orchestration.md) | Package plan, decisions, acceptance |
| [docs/adr/](docs/adr/) | Architecture Decision Records |

## License

Apache-2.0 — see [LICENSE](LICENSE). Third-party catalogs retain their own licenses (MIT for Motion/Magic UI/shadcn/Radix; GSAP Standard No Charge — metadata only).
