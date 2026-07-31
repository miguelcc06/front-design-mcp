# Evaluation — front-design-mcp

Offline evaluation of the local BM25 + tool surface (Package D).

## How to run

```bash
uv sync --all-extras
uv run front-design-ingest --offline   # optional; eval auto-ingests into a temp DB
uv run python scripts/evaluate_rag.py
uv run pytest -q tests/test_evaluation.py
```

No network is required. The script points `FRONT_DESIGN_*` at a temporary directory.

## Queries (fixed)

| ID | Query | Mode |
|----|-------|------|
| `hero-reduced-motion` | Necesito un hero animado para Next.js que respete prefers-reduced-motion | `recommend_frontend_stack` |
| `motion-vs-gsap` | Compara Motion y GSAP para una landing con scroll storytelling | `compare_frontend_options` (`options`) |
| `pricing-a11y-tailwind` | Encuentra componentes de pricing accesibles compatibles con Tailwind | `find_components` (intent=pricing) |
| `saas-dashboard-stack` | Recomienda stack para un dashboard SaaS sobrio, rápido y responsive | `recommend_frontend_stack` |

## Metrics (basic)

A query **passes** when all of the following hold:

1. **Relevance:** ≥1 relevant hit **OR** non-empty `recommendation` / compare `items`.
2. **Citations:** at least one citation, provenance, or sources field is present.
3. **Facts hygiene:** no uncited *hard* compatibility claims in `facts` (regex for phrases like “fully compatible”, “guaranteed compatible”, …). Soft inferences are allowed in `inferences`.

The script prints a per-query line and `SUMMARY n/N passed`.

## What this does *not* measure

- LLM agent multi-step tool use (see Anthropic mcp-builder evaluation skill for that style).
- Ranking quality (nDCG / MRR) or embedding recall — v1 search is BM25 lexical only.
- True accessibility or performance compliance of upstream libraries.
- Online registry freshness (fixtures are curated snapshots).
- Cross-library runtime compatibility (facts vs inferences separation is the guardrail).

## Extending

Add entries to `QUERIES` in `scripts/evaluate_rag.py` and mirror expectations in `tests/test_evaluation.py`. Prefer stable fixture ids so CI stays deterministic offline.
