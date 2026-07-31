# ADR 0006 — Hybrid search and Reciprocal Rank Fusion (RRF)

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

Con PostgreSQL + pgvector (ADR 0005) hay dos ramas de retrieval: léxica (`ts_rank_cd`) y vectorial (cosine similarity). Los scores de BM25 / `ts_rank_cd` / cosine viven en **escalas incomparables**: sumarlos o normalizarlos ad hoc distorsiona el ranking. Hace falta una fusión scale-free y un contrato claro de degradación cuando faltan vectores o falla el provider.

SQLite sigue siendo solo BM25 (sin rama vectorial). Este ADR aplica al path híbrido real (Postgres + provider habilitado).

## Decision

### Por qué RRF (no suma de scores)

Reciprocal Rank Fusion combina **rangos**, no magnitudes:

\[
\text{score}(d) = \sum_{\text{branch } b} \frac{w_b}{k + \mathrm{rank}_b(d)}
\]

Implementación: `search/rrf.py` → `weight / (k + rank)` por rama, con `k` por defecto **60** (`FRONT_DESIGN_RRF_K`, constante `DEFAULT_K`). Pesos por defecto `rrf_lexical_weight = 1.0` y `rrf_vector_weight = 1.0` (sin tuning empírico todavía).

Empates se rompen por `chunk_id` (determinismo). Una rama vacía es válida: se conserva el orden de la otra, pero los scores reportados en modo híbrido siguen siendo de fusión cuando ambas aportan.

### Orquestación (`SearchService`)

1. **Filtros antes del ranking.** `build_filters` resuelve `source_id` / `kind` / `tags`. El filtro de **framework** no cabe en SQL (aliasing); se expande a un `resource_ids` set en memoria y se empuja como `IN`. Si el set queda vacío → `excludes_everything` → modo `none`, sin retrieval.
2. **Pool de candidatos.** Cada rama pide `max(limit, search_candidates)` (default `search_candidates=50`) antes de fusionar/truncar.
3. **Modo efectivo.** `search_mode=auto|hybrid|vector|lexical`. Vector/híbrido solo si el store es `VectorSearcher` con `vector_search=True` **y** el embedder está `enabled`. Si no, cae a léxico.
4. **SQLite:** solo índice BM25 in-process; nunca hay rama vectorial.

### Fallbacks y flag `degraded`

Comportamiento real de `_vector_branch` / `search_detailed`:

| Situación | Resultado |
|-----------|-----------|
| Query vacía / solo whitespace | `mode=none`; nota; sin hits |
| Filtros que no matchean nada | `mode=none`; nota |
| Provider `none` / vector no nativo | Rama vectorial `[]`; lexical only |
| Fallo al embeddear query (`EmbeddingError` / `EmbeddingConfigError`) | Nota `"Vector branch unavailable: …"`; lexical; `degraded=True` si se pedía hybrid/vector |
| Dimension mismatch en `search_vector` (`ValueError`) | Misma degradación a lexical + nota |
| Embeddings ausentes / vacíos en DB | Vector `[]`; lexical; `degraded=True` + nota sobre missing embeddings |
| Hybrid con ambas ramas pobladas | RRF; `mode=hybrid`; `degraded=False` |

### Score reportado

En modo **hybrid**, `SearchHit.score` es el **score RRF**. **No es comparable** con BM25 ni con cosine. Las facts del hit incluyen rangos/scores por rama (`lexical_rank` / `vector_rank` / scores) para auditoría. En modo single-branch, `score` es el de esa rama (`as_fused`).

### Índice vectorial (migración)

`embeddings.embedding` usa **HNSW** con `vector_cosine_ops` (cosine distance). Motivo: similitud semántica estándar en pgvector. **No hay benchmark** en este repo que justifique IVFFlat; no se eligió IVFFlat.

La dimensión se fija en `alembic upgrade` desde `FRONT_DESIGN_EMBEDDING_DIMENSIONS` (default de migración 1536 si unset) y se registra en `store_metadata`.

## Consequences

### Limitaciones conocidas

- **Pesos RRF sin tunear** — defaults 1.0/1.0; no hay evaluación publicada que los justifique.
- **SQLite sin rama vectorial** — híbrido imposible en ese backend; `resolve_mode` siempre acaba en lexical si no hay vector nativo.
- **BM25 rebuildea el corpus entero en memoria** al startup / tras rebuild (`LexicalBM25Index.rebuild`) — O(corpus); no usar por query.
- FTS Postgres usa config `'english'`; queries en español dependen más de la rama vectorial (p. ej. `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` vía fastembed) cuando está disponible.

### Config relacionada

| Variable | Default | Rol |
|----------|---------|-----|
| `FRONT_DESIGN_SEARCH_MODE` | `auto` | Estrategia pedida |
| `FRONT_DESIGN_RRF_K` | `60` | Suavizado RRF |
| `FRONT_DESIGN_RRF_LEXICAL_WEIGHT` | `1.0` | Peso rama léxica |
| `FRONT_DESIGN_RRF_VECTOR_WEIGHT` | `1.0` | Peso rama vectorial |
| `FRONT_DESIGN_SEARCH_CANDIDATES` | `50` | Pool por rama antes de fusionar |
