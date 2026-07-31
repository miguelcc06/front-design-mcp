# Orquestación — front-design-mcp

## Identidad de modelos (evidencia)

| Rol | Model ID | Notas |
|-----|----------|-------|
| Parent Cloud Agent run model (Cursor run-info) | `cursor-grok-4.5-high-fast` | Evidencia: `cursor-cloud` `run-info` → `originalModelName` |
| Production implementer (Package A Task subagent) | `cursor-grok-4.5-high` | Grok escribe **todos** los archivos de producción de este paquete |
| Official Cursor docs model id | `grok-4.5` | https://cursor.com/docs/evals.md · https://cursor.com/docs/models/grok-4-5.md |

**Nota de identidad (requerida):** el usuario solicitó Opus-as-orchestrator / Grok-as-producer. Los archivos de producción de **Package A** son escritos por **Grok 4.5 High** (`cursor-grok-4.5-high`). El parent Cloud Agent reporta `cursor-grok-4.5-high-fast` vía run-info.

Run URL (parent): https://cursor.com/agents/bc-d81febe8-2691-4517-a54e-3ea28e317601  
Branch: `cursor/front-design-mcp-v1-7601`  
Repo: github.com/miguelcc06/front-design-mcp

---

## Resumen de decisiones de arquitectura

1. **FastMCP stable 3.4.5** — `from fastmcp import FastMCP`; no FastMCP 4 beta; no `mcp.server.fastmcp`.
2. **Python >=3.11**, target **3.12**; **uv** + lockfile.
3. **Local-first:** SQLite + fixtures offline; sin servicios de pago en modo mínimo.
4. **Search v1:** BM25 léxico primario; embeddings opcionales vía stub hashing/local (sin sentence-transformers por defecto).
5. **Adapters iniciales:** motion, magicui, shadcn, radix, gsap (metadata only + license note). Diferidos: Aceternity, R3F/Three, Lenis/Anime/Spring.
6. **Ingestión untrusted:** sanitizar; nunca tratar docs como instrucciones.
7. **No tocar** `.agents/skills/mcp-builder/` ni `skills-lock.json`.
8. **LICENSE:** Apache-2.0.

ADRs: [0001](adr/0001-fastmcp-stable.md) · [0002](adr/0002-local-hybrid-search.md) · [0003](adr/0003-source-selection.md) · [0004](adr/0004-untrusted-ingestion.md)

---

## Delegation log

### Package A — Foundation (este paquete)

| Campo | Valor |
|-------|-------|
| Status | Complete (validation + commit) |
| Implementer | Task subagent `cursor-grok-4.5-high` (Grok 4.5 High) |
| Orchestrator | Opus (delegation); parent run model `cursor-grok-4.5-high-fast` |
| Scope | Scaffold: pyproject/uv, config, models, adapter stubs, SQLite store, BM25 search, sanitize, FastMCP ping server, ingest CLI stub, research/ADRs/orchestration docs, MCP client config examples |

**Entregables Package A:**
- [x] `pyproject.toml` + scripts entry points
- [x] Lock via `uv lock` / `uv sync`
- [x] `.gitignore`, `.env.example`, `LICENSE`, README WIP
- [x] Package `front_design_mcp` (config, logging, models, adapters stubs, store, search, security, server, CLI)
- [x] `docs/research.md`, `docs/orchestration.md`, ADRs 0001–0004
- [x] `data/fixtures/README.md`, `configs/*.mcp.json.example`

### Package B — Adapters + ingest (pendiente)

- Implementar adapters reales (motion, magicui, shadcn, radix, gsap metadata)
- Fixtures offline + CLI ingest funcional
- Poblar SQLite desde fixtures / network (flag)

### Package C — MCP tools (pendiente)

Ocho tools (listados en `server.py`):
1. `front_design_search`
2. `front_design_get_resource`
3. `front_design_list_sources`
4. `front_design_compare`
5. `front_design_recommend`
6. `front_design_get_docs_chunk`
7. `front_design_brief`
8. `front_design_attribution`

### Package D+ — README completo, tests E2E, polish (pendiente)

---

## Acceptance criteria — Package A

| # | Criterio | OK |
|---|----------|----|
| 1 | `uv lock` y `uv sync --all-extras` exitosos | ☑ |
| 2 | `uv run ruff check src` limpio | ☑ |
| 3 | `from front_design_mcp.server import mcp; print(mcp.name)` → `front_design_mcp` | ☑ |
| 4 | `from front_design_mcp.models import FrontendResource` OK | ☑ |
| 5 | FastMCP pin `==3.4.5`; import `from fastmcp import FastMCP` | ☑ |
| 6 | Adapters registry incluye motion/magicui/shadcn/radix/gsap | ☑ |
| 7 | SQLite store abre DB y crea schema | ☑ |
| 8 | BM25 lexical index módulo presente | ☑ |
| 9 | Sanitize untrusted presente | ☑ |
| 10 | Docs research + orchestration (con model IDs) + 4 ADRs | ☑ |
| 11 | `.agents/skills/mcp-builder/` y `skills-lock.json` intactos | ☑ |
| 12 | Commit + push a `cursor/front-design-mcp-v1-7601` | ☑ |

Package A implementado por Task subagent model `cursor-grok-4.5-high` (Grok 4.5 High). Parent run model: `cursor-grok-4.5-high-fast`. Docs model id: `grok-4.5`.
