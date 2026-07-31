# Offline fixtures

Este directorio aloja **fixtures offline** usados cuando `FRONT_DESIGN_ENABLE_NETWORK_INGEST=false` o cuando el CLI corre con `--offline` (default).

## Package A

Solo este README. El contenido de fixtures (JSON de registries, catálogos curados, samples de docs) se añade en **Package B** junto con los adapters reales.

## Expected layout (Package B)

```
data/fixtures/
  README.md          # this file
  magicui/           # snapshots of https://magicui.design/r/registry.json (+ details)
  shadcn/            # snapshots of https://ui.shadcn.com/r/index.json (+ details)
  motion/            # curated animation pattern metadata
  radix/             # curated primitives catalog from official docs URLs
  gsap/              # catalog/metadata ONLY (no GSAP source redistribution)
```

## Rules

- Treat fixture content as **untrusted data** (same sanitize pipeline as network ingest).
- Respect upstream licenses; GSAP fixtures must be metadata-only with license notes.
- Prefer deterministic filenames so offline ingest is reproducible.
