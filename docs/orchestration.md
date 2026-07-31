# Orquestación — front-design-mcp

## Identidad de modelos (evidencia)

| Rol | Model ID | Notas |
|-----|----------|-------|
| Parent Cloud Agent run model (Cursor run-info) | `cursor-grok-4.5-high-fast` | Evidencia: `cursor-cloud` `run-info` → `originalModelName` |
| Production implementer (Package A Task subagent) | `cursor-grok-4.5-high` | Grok escribe **todos** los archivos de producción de este paquete |
| Production implementer (Package B Task subagent) | `cursor-grok-4.5-high` | Adapters reales, fixtures, ingest, BM25 search service |
| Production implementer (Package C Task subagent) | `cursor-grok-4.5-high` | MCP tool surface, curated intents, smoke Client checks |
| Production implementer (Package D Task subagent) | `cursor-grok-4.5-high` | CI, RAG evaluation, docs, compare/`options` + mypy fixes |
| Official Cursor docs model id | `grok-4.5` | https://cursor.com/docs/evals.md · https://cursor.com/docs/models/grok-4-5.md |

**Nota de identidad (requerida):** el usuario solicitó Opus-as-orchestrator / Grok-as-producer. Los archivos de producción de **Package A**, **Package B**, **Package C** y **Package D** son escritos por **Grok 4.5 High** (`cursor-grok-4.5-high`). El parent Cloud Agent reporta `cursor-grok-4.5-high-fast` vía run-info.

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

### Package C — MCP tools (este paquete)

| Campo | Valor |
|-------|-------|
| Status | Complete (validation + commit) |
| Implementer | Task subagent `cursor-grok-4.5-high` (Grok 4.5 High) |
| Orchestrator | Opus (delegation); parent run model `cursor-grok-4.5-high-fast` |
| Scope | Full MCP tool surface + curated intent fixtures + auto-ingest + resources/prompt + smoke tests |

**Decisiones Package C (Orchestrator):**
1. Exact tool names from product brief (8 + `front_design_ping`)
2. Handlers under `src/front_design_mcp/tools/`; registered on FastMCP with `readOnlyHint=True`, `openWorldHint=False`, `idempotentHint=True`
3. Intent coverage fix: `CuratedAdapter` (`source_id=curated`) + `data/fixtures/curated/patterns.json` for hero/pricing/navbar/dashboard/onboarding/scroll storytelling (+ microinteraction)
4. Auto-ingest offline fixtures when DB empty on first tool use / ping
5. Resource `front-design://sources`; template `front-design://resource/{id}`; prompt `frontend_implementation_brief`
6. Recommendation/compare/brief tools separate `facts` vs `inferences`; never claim unverified compatibility

**Entregables Package C:**
- [x] Tools: discover, search, details, compare, recommend, find_components, find_animation_patterns, build_frontend_brief + ping
- [x] CuratedAdapter + patterns fixtures; registered in adapter registry + ingest CLI
- [x] Server auto-ingest + sources resource + resource template + implementation prompt
- [x] `tests/test_tools_smoke.py`, `tests/test_intent_coverage.py`
- [x] `docs/orchestration.md` Package C entry (model `cursor-grok-4.5-high`)

### Package C-fix — Framework aliases + bilingual recommend/brief

| Campo | Valor |
|-------|-------|
| Status | Complete |
| Implementer | Task subagent `cursor-grok-4.5-high` (Grok 4.5 High) |
| Orchestrator | Opus (Package C defect review) |
| Scope | Framework alias matching + ES/EN query expansion + recommend/brief fallbacks |

**Defects fixed:**
1. `resource_matches_framework` failed for `nextjs` / `next.js` against resources tagged `next`/`react` (substring equality only).
2. `recommend_frontend_stack` / `build_frontend_brief` returned empty for Spanish (and many natural) queries: BM25 on English index + appending Spanish a11y text → 0 hits; then framework filter removed remaining.

**Decisiones Package C-fix (Orchestrator):**
1. `normalize_framework_token(s) -> set[str]` in `tools/frameworks.py`; intersection matching; empty `supported_frameworks` does not exclude (unknown ≠ incompatible) + inference note when recommending
2. Fixed ES/EN lexicon expansion (`tools/lexicon.py`) — not a translation service; detect intents (dashboard/hero/pricing/…) in ES+EN; union BM25 with intent-targeted `find_components`
3. If still empty after search+filter → fallback curated/library anchors (motion/shadcn/radix), facts vs inferences separated
4. `build_frontend_brief` always selects intents via bilingual detection (`animado`→animation/hero); smoke brief components non-empty
5. Tests: `tests/test_framework_aliases.py`, `tests/test_recommend_i18n.py`

**Entregables Package C-fix:**
- [x] `tools/frameworks.py` + updated `resource_matches_framework`
- [x] `tools/lexicon.py` query expansion + intent detection
- [x] recommend/brief handlers: expand → intent union → curated/library fallback
- [x] Tests for aliases + Spanish SaaS/landing smoke paths

### Package D — Quality, evaluation, docs, CI

| Campo | Valor |
|-------|-------|
| Status | Complete (validation + commit) |
| Implementer | Task subagent `cursor-grok-4.5-high` (Grok 4.5 High) |
| Orchestrator | Opus (delegation); parent run model `cursor-grok-4.5-high-fast` |
| Scope | CI workflow, offline RAG eval, professional docs, compare/`options` + mypy fixes |

**Decisiones Package D (Orchestrator / review fixes):**
1. `compare_frontend_options` primary param is `options` (list of ids/names); `resources` kept as deprecated alias
2. `get_resource_details` keeps FastMCP Client-compatible param `id` (verified; no rename needed)
3. mypy clean: `rank_bm25` override, typed fixture loaders, `ToolAnnotations(...)` constructed properly, unused ignore removed
4. Offline eval: 4 fixed ES/EN queries; metrics ≥1 hit OR non-empty recommend; citations; no uncited hard compat claims in facts
5. CI: push/PR, Python 3.12, uv sync, ruff, mypy, pytest, offline ingest, eval, MCP smoke; `permissions: contents: read`
6. **Dockerfile:** skipped — not verified with `docker build` in this package; local `uv` + CI is the supported path (noted in README)

**Entregables Package D:**
- [x] `.github/workflows/ci.yml`
- [x] `docs/evaluation.md` + `scripts/evaluate_rag.py` + `tests/test_evaluation.py`
- [x] `scripts/mcp_smoke.py`
- [x] Professional `README.md`, `CONTRIBUTING.md`, `SECURITY.md`
- [x] `docs/adapters.md`, `docs/github.md`
- [x] Expanded `.env.example`; accurate `configs/*` (`uv run --directory … python -m front_design_mcp`)
- [x] compare/`options` + mypy fixes; orchestration Package D entry (model `cursor-grok-4.5-high`)

---

## Acceptance criteria — Package D

| # | Criterio | OK |
|---|----------|----|
| 1 | `uv sync --all-extras` | ☑ |
| 2 | `uv run ruff check src tests scripts` limpio | ☑ |
| 3 | `uv run mypy src/front_design_mcp` exit 0 | ☑ |
| 4 | `uv run front-design-ingest --offline` | ☑ |
| 5 | `uv run pytest -q` pasa | ☑ |
| 6 | `uv run python scripts/evaluate_rag.py` SUMMARY pass | ☑ |
| 7 | Client: `compare_frontend_options(options=[…])` + `get_resource_details(id=…)` | ☑ |
| 8 | `.agents/skills/mcp-builder/` y `skills-lock.json` intactos | ☑ |
| 9 | Commit + push a `cursor/front-design-mcp-v1-7601` | ☑ |

Package D implementado por Task subagent model `cursor-grok-4.5-high` (Grok 4.5 High). Parent run model: `cursor-grok-4.5-high-fast`. Docs model id: `grok-4.5`.

## Acceptance criteria — Package C

| # | Criterio | OK |
|---|----------|----|
| 1 | `uv sync --all-extras` | ☑ |
| 2 | `uv run ruff check src tests` limpio | ☑ |
| 3 | `uv run front-design-ingest --offline` popula SQLite (incl. curated) | ☑ |
| 4 | `uv run pytest -q` pasa | ☑ |
| 5 | FastMCP Client lista tools + ping + search(accordion) + find_components(pricing) ≥1 | ☑ |
| 6 | Intent coverage hero/pricing/navbar/dashboard ≥1 | ☑ |
| 7 | `.agents/skills/mcp-builder/` y `skills-lock.json` intactos | ☑ |
| 8 | Commit + push a `cursor/front-design-mcp-v1-7601` | ☑ |

Package C implementado por Task subagent model `cursor-grok-4.5-high` (Grok 4.5 High). Parent run model: `cursor-grok-4.5-high-fast`. Docs model id: `grok-4.5`.

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

---

## Final review

### Orchestrator adversarial review results (2026-07-31)

| Check | Result |
|-------|--------|
| `uv run ruff check src tests scripts` | pass |
| `uv run mypy src/front_design_mcp` | 0 errors |
| `uv run pytest -q` | 36 passed |
| `uv run python scripts/evaluate_rag.py` | 4/4 PASS |
| MCP Client smoke | lists 9 tools + resource + prompt; `compare_frontend_options` / `get_resource_details` ok |

### Parent model evidence

| Rol | Model ID |
|-----|----------|
| Parent Cloud Agent run | `cursor-grok-4.5-high-fast` |
| Production packages A–D + C-fix (Task subagents) | `cursor-grok-4.5-high` |

### GitHub metadata blockage

`gh repo edit` for description/topics returned **HTTP 403 Resource not accessible by integration** — cannot set description/topics with the current token. Repo URL https://github.com/miguelcc06/front-design-mcp is public and code is pushed on branch `cursor/front-design-mcp-v1-7601`. Suggested description/topics remain in [`docs/github.md`](github.md) for manual apply by the owner.

### Placeholder token note

The placeholder `ghp_xxx` in `.agents/skills/mcp-builder/reference/evaluation.md` is example text from the Anthropic skill, not a live secret.

### Known limitations (v1)

- BM25-only default (no dense vectors)
- Spanish support via lexicon, not full i18n
- GSAP metadata-only
- Magic UI / shadcn fixtures are subsets
- No Dockerfile in v1
