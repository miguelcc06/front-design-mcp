# Investigación — front-design-mcp

**Fecha de consulta:** 2026-07-31  
**Producto:** FastMCP server de inteligencia UI/UX frontend para agentes de IA  
**Paquete Python:** `front_design_mcp` · **MCP name:** `front_design_mcp`

---

## 1. FastMCP

| Hecho | Detalle |
|-------|---------|
| Docs | https://gofastmcp.com |
| PyPI | https://pypi.org/project/fastmcp/ |
| Versión estable elegida | **3.4.5** (`fastmcp==3.4.5`) |
| v4 | Prerelease (`4.0.0b1`) — **no usar** en v1 |
| Licencia | Apache-2.0 |
| Import | `from fastmcp import FastMCP` (no `mcp.server.fastmcp`) |
| Tooling | Recomiendan **uv** |
| llms.txt | https://gofastmcp.com/llms.txt |

Decisión: pin exacto a FastMCP **stable 3.4.5**. Ver ADR-0001.

---

## 2. Model Context Protocol (MCP)

- Especificación consultada: https://modelcontextprotocol.io/specification/2025-06-18.md
- Capacidades relevantes: **tools**, **resources**, **prompts**
- Transporte local: **stdio**
- Remoto: **streamable HTTP**
- **SSE** está deprecado

Este servidor v1 opera por **stdio** (local-first).

---

## 3. MCP Builder skill (Anthropic)

| Hecho | Detalle |
|-------|---------|
| Repo oficial | https://github.com/anthropics/skills |
| Path del skill | `skills/mcp-builder` |
| Instalación | `npx skills add https://github.com/anthropics/skills --skill mcp-builder` |
| Resultado local | `.agents/skills/mcp-builder/` + `skills-lock.json` |
| Cursor | Carga skills desde `.agents/skills/` |

**Estado en este repo:** el skill **ya está presente** (no modificar `.agents/skills/mcp-builder/` ni `skills-lock.json`).

---

## 4. Fuentes iniciales (adapters reales en Package B)

### Motion — MIT
- Sitio: https://motion.dev
- npm: `motion`
- GitHub: https://github.com/motiondivision/motion
- Uso: patrones de animación curados + metadata npm/docs
- Atribución obligatoria a Motion

### Magic UI — MIT
- Sitio: https://magicui.design
- Registry: https://magicui.design/r/registry.json (~247 items)
- Offline: fixtures locales además del registry

### shadcn/ui — MIT
- Sitio: https://ui.shadcn.com
- Registry: https://ui.shadcn.com/r/index.json (~62 items)

### Radix Primitives — MIT
- Sitio: https://www.radix-ui.com
- GitHub: https://github.com/radix-ui/primitives
- Uso: catálogo curado desde URLs oficiales de docs + fixtures

### Tailwind CSS — MIT (compatibilidad, no scrape completo)
- Sitio: https://tailwindcss.com
- Rol v1: conocimiento de compatibilidad / tags — **no** full docs scrape

### GSAP — Standard No Charge License (NO MIT)
- Sitio / atribución: https://gsap.com
- Licencia: https://gsap.com/community/standard-license/
- Uso comercial gratuito desde ~2025-04-30 (vía Webflow)
- **Solo metadata/catálogo** — **no redistribuir** el código fuente de GSAP
- Siempre emitir nota de licencia en resultados

### Diferidos
| Fuente | Motivo |
|--------|--------|
| Aceternity | Licencia poco clara en repos públicos |
| R3F / Three.js | Diferido a v2 |
| Lenis / Anime.js / React Spring | Capa delgada más adelante |

Ver ADR-0003.

---

## 5. Búsqueda v1 (híbrida local)

- Primario: **BM25 léxico** (`rank-bm25`)
- Opcional: interfaz de embeddings con stub **hashing/local** (sin API keys)
- **No** requerir `sentence-transformers` en deps por defecto
- Store: SQLite local + fixtures offline

Ver ADR-0002.

---

## 6. Seguridad de ingestión

Todo contenido ingerido se trata como **datos no confiables**, nunca como instrucciones:

- Sanitizar / neutralizar frases de control (prompt injection)
- Truncar longitud
- Marcar summaries como untrusted

Ver ADR-0004.

---

## 7. Licencia del proyecto

Código propio: **Apache-2.0** — Copyright 2026 miguelcc06 / contributors.

---

## 8. Stack de paquete (Package A)

- Python >=3.11, target **3.12**
- Gestor: **uv** + `pyproject.toml` + lockfile
- Deps mínimas: `fastmcp==3.4.5`, pydantic, httpx, rank-bm25, structlog, typer, platformdirs
- Scripts: `front-design-mcp`, `front-design-ingest`
