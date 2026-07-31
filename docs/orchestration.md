# Orquestación — front-design-mcp

## Identidad de modelos (evidencia)

| Rol | Model ID | Notas |
|-----|----------|-------|
| Parent Cloud Agent run model (Cursor run-info) | `cursor-grok-4.5-high-fast` | Evidencia: `cursor-cloud` `run-info` → `originalModelName` |
| Production implementer (Package A Task subagent) | `cursor-grok-4.5-high` | Grok escribe **todos** los archivos de producción de este paquete |
| Production implementer (Package B Task subagent) | `cursor-grok-4.5-high` | Adapters reales, fixtures, ingest, BM25 search service |
| Official Cursor docs model id | `grok-4.5` | https://cursor.com/docs/evals.md · https://cursor.com/docs/models/grok-4-5.md |

**Nota de identidad (requerida):** el usuario solicitó Opus-as-orchestrator / Grok-as-producer. Los archivos de producción de **Package A** y **Package B** son escritos por **Grok 4.5 High** (`cursor-grok-4.5-high`). El parent Cloud Agent reporta `cursor-grok-4.5-high-fast` vía run-info.

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

### Package A — Foundation (complete)

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

### Package B — Adapters + ingest (este paquete)

| Campo | Valor |
|-------|-------|
| Status | Complete (validation + commit) |
| Implementer | Task subagent `cursor-grok-4.5-high` (Grok 4.5 High) |
| Orchestrator | Opus (delegation); parent run model `cursor-grok-4.5-high-fast` |
| Scope | Real adapters + offline fixtures + ingest pipeline + SqliteStore filters + BM25 SearchService + unit tests |

**Decisiones Package B (Orchestrator):**
1. Offline-first fixtures under `data/fixtures/{motion,magicui,shadcn,radix,gsap}/`
2. Adapters implement `SourceAdapter` fully; prefer fixtures when offline; online uses httpx with timeouts/retries; sanitize all text; fail in isolation
3. Magic UI parses `registry.json` shape; map `registry:ui` → component; examples → pattern/example
4. shadcn parses index list; install `npx shadcn@latest add {name}`
5. Motion curated catalog (no HTML scrape); MIT; `npm install motion`
6. Radix curated primitives ≥10; MIT; `@radix-ui/react-*`
7. GSAP metadata only; Standard No Charge License; `redistributable=false`
8. Documentation chunks (1–3) per resource with `content_sha256`; marked untrusted; <1500 chars
9. `ingest/pipeline.py` → `run_ingest(sources, online) -> IngestReport`
10. CLI wired to pipeline (`--source`, `--offline/--online`, report summary/JSON)
11. SqliteStore filters (kind, source_id, tags); lazy/auto-open; recreate-OK schema
12. `search/service.py` loads chunks + BM25 + filters → `SearchHit` + `Citation`
13. `uv run front-design-ingest --offline` builds `data/store/front_design.db`
14. Tests: `test_sanitize`, `test_adapters_offline`, `test_ingest_offline`

**Entregables Package B:**
- [x] Fixtures JSON committed for all five sources
- [x] Adapters: motion, magicui, shadcn, radix, gsap
- [x] `adapters/common.py` (fixtures, httpx retries, sanitize, chunks)
- [x] `ingest/pipeline.py` + CLI wiring
- [x] `search/service.py`
- [x] SqliteStore + Settings (`resolve_db_path` → `./data/store/front_design.db`)
- [x] Unit tests under `tests/`
- [x] `server.py` tool-name comment list corrected for Package C product brief

### Package C — MCP tools (pendiente)

Ocho tools (nombres exactos del product brief; corrección Orchestrator):
1. `discover_frontend_resources`
2. `search_frontend_knowledge`
3. `get_resource_details`
4. `compare_frontend_options`
5. `recommend_frontend_stack`
6. `find_components`
7. `find_animation_patterns`
8. `build_frontend_brief`
Plus keep `front_design_ping`.

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

## Acceptance criteria — Package B

| # | Criterio | OK |
|---|----------|----|
| 1 | `uv sync --all-extras` | ☑ |
| 2 | `uv run ruff check src tests` limpio | ☑ |
| 3 | `uv run front-design-ingest --offline` popula SQLite | ☑ |
| 4 | `uv run pytest -q` pasa | ☑ |
| 5 | Store resources/chunks counts > 0 | ☑ |
| 6 | Fixtures committed; db gitignored | ☑ |
| 7 | `.agents/skills/mcp-builder/` y `skills-lock.json` intactos | ☑ |
| 8 | Commit + push a `cursor/front-design-mcp-v1-7601` | ☑ |

Package B implementado por Task subagent model `cursor-grok-4.5-high` (Grok 4.5 High). Parent run model: `cursor-grok-4.5-high-fast`. Docs model id: `grok-4.5`.
