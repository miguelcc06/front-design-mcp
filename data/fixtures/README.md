# Offline fixtures

Este directorio aloja **fixtures offline** usados cuando `FRONT_DESIGN_ENABLE_NETWORK_INGEST=false` o cuando el CLI corre con `--offline` (default).

## Layout (Package B)

```
data/fixtures/
  README.md
  magicui/registry.json   # trimmed Magic UI registry ({name,homepage,items})
  shadcn/index.json       # trimmed shadcn registry index (≥20 components)
  motion/catalog.json     # curated Motion library + animation/pattern entries
  radix/catalog.json      # curated Radix primitives (≥10)
  gsap/catalog.json       # GSAP metadata/catalog ONLY (≥8 patterns)
  curated/patterns.json   # intent patterns (hero, pricing, navbar, dashboard, …)
```

## Usage

```bash
uv run front-design-ingest --offline
# writes data/store/front_design.db (gitignored); fixtures are source of truth
```

## Rules

- Treat fixture content as **untrusted data** (same sanitize pipeline as network ingest).
- Respect upstream licenses; GSAP fixtures must be metadata-only with license notes.
- Prefer deterministic filenames so offline ingest is reproducible.
- Network ingest (optional): `--online` requires `FRONT_DESIGN_ENABLE_NETWORK_INGEST=true`.
