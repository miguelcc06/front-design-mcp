# Retrieval evaluation query set

Hand-labelled relevance judgements for `front-design-mcp` offline fixtures.

## Corpus (measured)

Offline ingest of `data/fixtures/` yields:

| Source   | Resources | Chunks |
|----------|-----------|--------|
| motion   | 12        | 24     |
| magicui  | 26        | 52     |
| shadcn   | 25        | 75     |
| radix    | 11        | 22     |
| gsap     | 9         | 27     |
| curated  | 7         | 21     |
| **total**| **90**    | **221**|

Re-measure after fixture changes:

```bash
uv run front-design-ingest --offline
# or open a temp SQLite store and call store.count_resources() / count_chunks()
```

## Schema

Each entry in `queries.json` → `queries[]`:

| Field | Meaning |
|-------|---------|
| `id` | Stable kebab-case id |
| `query` | User-typed text |
| `lang` | `en` or `es` |
| `category` | `synonym` \| `conceptual` \| `typo` \| `filter` \| `unanswerable` \| `injection` \| `exact` |
| `filters` | Optional `kind`, `source_id`, `tags`, `framework` (null / `[]` = unset) |
| `relevant_resource_ids` | Resource ids that count as relevant |
| `notes` | Why those ids were chosen / what injection asserts |

**Relevance is at resource granularity.** A returned chunk is relevant when
`hit.resource.id` (or `citation.resource_id`) is in `relevant_resource_ids`.
Chunk ids are an implementation detail and must not appear in judgements.

Unanswerable queries use `relevant_resource_ids: []`. A perfect system returns
no hits for those.

## How judgements were made

1. Ingest the offline fixtures into a temporary SQLite store.
2. List every resource id and read descriptions / tags from fixtures.
3. For each query, pick ids that a knowledgeable user would accept as answering
   the intent (not every weakly related resource).
4. Verify every id exists in the ingested store (CI enforces this).

These labels are **small and biased**: ~26 queries, one labeler, fixture-bound.
They exercise weaknesses (typos, Spanish, conceptual phrasing, abstention,
prompt injection) rather than produce a flattering score.

## How to add a query

1. Confirm the resource ids you need exist (`uv run front-design-ingest --offline`
   then inspect the store, or grep `data/fixtures/**`).
2. Append an object to `queries` in `queries.json` with all required keys.
3. Prefer pairing English/Spanish for the same intent when comparing lexical
   vs vector quality.
4. Re-run:

```bash
uv run python scripts/benchmark_retrieval.py --markdown
uv run python scripts/evaluate_rag.py
uv run pytest -q tests/test_evaluation.py
```

5. Update `docs/evaluation.md` only after you paste **measured** numbers from a
   real run — never invent baselines.
