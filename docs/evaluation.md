# Evaluation — front-design-mcp

Retrieval quality and tool-surface hygiene for the offline fixture corpus.
Two entry points:

| Script | Role |
|--------|------|
| `scripts/evaluate_rag.py` | **CI gate** — SQLite/BM25 only, offline, no network, no embeddings |
| `scripts/benchmark_retrieval.py` | **Measurement** — compare up to four configs; never fails on quality |

## What is measured

### Tool cases (CI)

Four fixed product queries exercise `recommend_frontend_stack`,
`compare_frontend_options`, and `find_components`. A case passes when:

1. The handler returns `ok` and a non-empty recommendation / items list.
2. At least one citation / provenance / sources field is present.
3. No uncited *hard* compatibility claim appears in `facts` (regex for phrases
   like “fully compatible”, “guaranteed compatible”, …).

### Ranking metrics (CI reports; benchmark compares)

Over `data/eval/queries.json` (≥24 hand-labelled queries):

| Metric | Definition |
|--------|------------|
| **Recall@K** | \|relevant ∩ top K\| / \|relevant\|, mean over **answerable** queries only |
| **MRR@K** | Mean of 1/(rank of first relevant); 0 when none in top K |
| **nDCG@K** | Binary gains, discount `1/log2(rank+1)`; ideal DCG places `min(K, \|relevant\|)` relevant items first |
| **Latency** | Per-query wall clock; mean and p95 in ms |
| **Empty-result rate** | Fraction of queries with zero hits |
| **Correct abstention** | Fraction of **unanswerable** queries that returned nothing |
| **Citation coverage** | Fraction of hits whose citation has both `resource_id` and `url` |
| **Uncited hard claims** | Hard-compat regex hits in per-hit `facts` without a citation |

**Resource-level deduplication:** before rank metrics, consecutive chunk hits for
the same resource collapse to one slot (first wins). Chunk ids are an
implementation detail; judgements are resource ids.

K defaults: 5 and 10.

## Corpus (measured 2026-07-31)

Offline ingest of `data/fixtures/`:

| Source  | Resources | Chunks |
|---------|-----------|--------|
| motion  | 12        | 24     |
| magicui | 26        | 52     |
| shadcn  | 25        | 75     |
| radix   | 11        | 22     |
| gsap    | 9         | 27     |
| curated | 7         | 21     |
| **total** | **90**  | **221** |

PostgreSQL + `fastembed` (`BAAI/bge-small-en-v1.5`, **384** dims) stores
**221** embeddings for the same corpus.

## Commands

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /workspace   # or your clone

# CI gate (SQLite only)
uv run python scripts/evaluate_rag.py
uv run pytest -q tests/test_evaluation.py

# Benchmark — SQLite BM25 only (no Postgres required)
uv run python scripts/benchmark_retrieval.py --markdown

# Benchmark — all four configs (Postgres must already be migrated + ingested)
FRONT_DESIGN_EVAL_DATABASE_URL="postgresql+psycopg://USER:PASS@127.0.0.1:5432/DB" \
  uv run python scripts/benchmark_retrieval.py --markdown
```

PostgreSQL configs **skip** (exit 0) when `FRONT_DESIGN_EVAL_DATABASE_URL` is
unset or unreachable. They do **not** read `FRONT_DESIGN_DATABASE_URL`.

Known-good Postgres prep (one-time for a dedicated eval database):

```bash
sudo -u postgres createdb -O front_design front_design_eval
FRONT_DESIGN_DATABASE_URL="postgresql+psycopg://front_design:front_design@127.0.0.1:5432/front_design_eval" \
FRONT_DESIGN_EMBEDDING_PROVIDER=fastembed \
FRONT_DESIGN_EMBEDDING_MODEL="BAAI/bge-small-en-v1.5" \
  uv run alembic upgrade head

FRONT_DESIGN_DATABASE_URL="postgresql+psycopg://front_design:front_design@127.0.0.1:5432/front_design_eval" \
FRONT_DESIGN_STORE_BACKEND=postgres \
FRONT_DESIGN_EMBEDDING_PROVIDER=fastembed \
FRONT_DESIGN_EMBEDDING_MODEL="BAAI/bge-small-en-v1.5" \
  uv run front-design-ingest --offline
```

Configs:

1. `sqlite-bm25` — SQLite, `search_mode=lexical`
2. `postgres-lexical` — PostgreSQL `tsvector`, lexical only
3. `postgres-vector` — PostgreSQL + `fastembed` / `BAAI/bge-small-en-v1.5` (384-d)
4. `postgres-hybrid` — RRF fusion (`rrf_k=60` default)

## Results table (measured 2026-07-31)

Single machine, cold-ish process, 26 labelled queries, corpus 90/221/221.
**Latency is not a PostgreSQL benchmark.**

| config | Recall@5 | Recall@10 | MRR@5 | MRR@10 | nDCG@5 | nDCG@10 | lat_mean_ms | lat_p95_ms | empty_rate | abstention | citation | uncited_hard |
|--------|----------|-----------|-------|--------|--------|---------|-------------|------------|------------|------------|----------|--------------|
| sqlite-bm25 | 0.681 | 0.696 | 0.826 | 0.826 | 0.694 | 0.701 | 0.4 | 0.6 | 0.038 | 0.000 | 1.000 | 0 |
| postgres-lexical | 0.688 | 0.710 | 0.804 | 0.810 | 0.701 | 0.709 | 1.2 | 2.7 | 0.000 | 0.000 | 1.000 | 0 |
| postgres-vector | 0.819 | 0.884 | 0.870 | 0.870 | 0.782 | 0.813 | 6.4 | 8.3 | 0.000 | 0.000 | 1.000 | 0 |
| postgres-hybrid | 0.790 | 0.862 | 0.891 | 0.899 | 0.793 | 0.823 | 6.4 | 8.6 | 0.000 | 0.000 | 1.000 | 0 |

Provider for vector/hybrid: `fastembed` / `BAAI/bge-small-en-v1.5` / dim=384 /
`rrf_k=60`.

### Observed behaviour (same run)

- **Vectors beat BM25** on typos (`acordion`, `toolti`) and overall recall.
- **BM25 beat vector** on `injection-reveal-prompt-pricing` (MRR@10 1.0 vs 0.5);
  hybrid recovered to 1.0 via RRF.
- **Spanish** answerable MRR@10 is lower than English on every config
  (e.g. sqlite-bm25 ~0.75 vs ~0.84). `conceptual-pricing-es` scores 0 everywhere;
  BM25 returns **empty**, vector/hybrid return **irrelevant** hits.
- **Unanswerable** queries: all three returned lexical/vector noise on every
  configuration (`correct_abstention_rate = 0`). Reported to coordinator as a
  retrieval finding — not a missing feature of the eval harness.

## CI gate thresholds

| Check | Threshold | Justification |
|-------|-----------|---------------|
| Tool cases | all 4 must pass | Existing product regression gate |
| Citation coverage | ≥ 1.0 | SearchService always attaches resource_id + url |
| Uncited hard claims | == 0 | Facts hygiene |
| Correct abstention | ≥ `1.0 - ABSTENTION_TOLERANCE` with **tolerance = 1.0** (floor 0.0) | Measured abstention is 0.0 on SQLite BM25; inventing a positive floor would fail CI without fixing retrieval. Metric is still printed. |
| MRR@10 | floor 0.0 (informational) | Refuse invented quality targets on a 26-query set |

No committed numeric baseline file — numbers above are from a real run and will
drift if fixtures or ranking change.

## What these numbers do NOT show

- Statistical significance (26 hand-labelled queries is far too small).
- Production latency or Postgres capacity (tiny corpus, single process).
- Tuned HNSW recall, tuned RRF weights, or embedding-model bake-offs beyond
  the one local `bge-small` model used here.
- Cross-language quality under a Spanish `tsvector` config (English config is
  used for Spanish queries).
- LLM agent multi-step tool use.
- True accessibility / performance compliance of upstream libraries.
- Online registry freshness.

## Limitations

- Hand-labelled judgements: small, biased, fixture-bound.
- Relevance is resource-level only.
- Prompt-injection cases only assert retrieval of the legitimate intent; they
  do not simulate a full LLM agent refusing the injection.
- SQLite and Postgres lexical analyzers differ (BM25 vs `tsvector`), so
  `sqlite-bm25` vs `postgres-lexical` is not an apples-to-apples tokenizer test.

## Extending

See `data/eval/README.md`. Add a query to `data/eval/queries.json`, verify
resource ids against an offline ingest, re-run the benchmark and CI script, and
update this doc only with **measured** numbers.
