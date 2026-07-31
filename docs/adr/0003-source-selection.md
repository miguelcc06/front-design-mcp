# ADR 0003 — Source selection for v1 adapters

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

Hay muchas librerías UI/animación. Debemos elegir fuentes con licencia clara, registries oficiales, y valor inmediato para agentes frontend — sin redistribuir código prohibido.

## Decision

### Incluidos en v1 (adapters reales — Package B)

| source_id | Licencia | Notas |
|-----------|----------|-------|
| `motion` | MIT | Curated patterns + npm/docs metadata; https://motion.dev |
| `magicui` | MIT | Registry https://magicui.design/r/registry.json |
| `shadcn` | MIT | Registry https://ui.shadcn.com/r/index.json |
| `radix` | MIT | Catálogo curado docs + fixtures; https://www.radix-ui.com |
| `gsap` | Standard No Charge | **Metadata only**; no redistribuir source; siempre license note |

Tailwind: compatibilidad/tags — no full scrape en v1.

### Diferidos

- **Aceternity** — licencia poco clara en repos públicos
- **R3F / Three.js** — v2
- **Lenis / Anime.js / React Spring** — capa delgada posterior

## Consequences

- Atribución y notas de licencia son parte del contrato de tools
- GSAP requiere cuidado especial (no MIT, no redistribute)
- Aceternity no se ingiere hasta aclarar licencia
