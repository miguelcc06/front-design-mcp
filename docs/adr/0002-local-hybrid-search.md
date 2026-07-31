# ADR 0002 — Local hybrid search (BM25 + optional embeddings)

- **Status:** Superseded by [ADR 0005](0005-storage-backend-selection.md) and [ADR 0006](0006-hybrid-search-rrf.md)
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

El servidor debe descubrir componentes, patrones y docs con ranking útil, sin depender de APIs de pago ni de modelos de embedding pesados en el modo mínimo.

## Decision (histórica)

Search v1 se diseñó como **híbrido local-first**:

1. **Primario:** índice léxico **BM25** (`rank-bm25`), reconstruible en memoria desde el store SQLite.
2. **Opcional:** interfaz de embedding provider; stub **hashing/local** que funciona sin API keys.
3. **No** incluir `sentence-transformers` en dependencias por defecto (extras opcionales futuros).
4. Persistencia: **SQLite** + fixtures offline; network ingest opt-in (`FRONT_DESIGN_ENABLE_NETWORK_INGEST=false` por defecto).

## Consequences (históricas)

- Modo mínimo funciona offline sin claves
- Calidad semántica limitada hasta activar un provider real
- El diseño de interfaces permite añadir providers sin reescribir el store

---

## Superseded / Correction

> **Esta sección corrige lo que ADR 0002 afirmaba y que nunca fue cierto en el código.**

### Qué estaba mal

1. **No existió nunca un provider `hashing` / stub local.** La config aceptaba `embedding_provider="hashing"` en algún punto, pero **ningún código lo consumía**. No había implementación que produjera vectores sin API keys ni modelo local.
2. La tabla SQLite `embeddings` del esquema v0.1 era **código muerto**: se escribían filas stub que **nada leía** para ranking. En el upgrade a esquema v2 esa tabla se elimina y se recrea (véase ADR 0005).
3. Llamar al search v1 «híbrido» era engañoso: en el backend SQLite **solo** hay BM25 in-process (`rank-bm25`). **No hay búsqueda vectorial ni fusión híbrida en SQLite.**

### Realidad actual (v1)

| Backend | Léxico | Vectores | Híbrido (RRF) |
|---------|--------|----------|---------------|
| **SQLite** (default) | BM25 in-process | **No** | **No** |
| **PostgreSQL + pgvector** (opt-in) | `ts_rank_cd` / tsvector | Sí (con provider real) | Sí (ADR 0006) |

Providers de embedding reales: `none` (default), `openai` (extra `embeddings`), `fastembed` (dependency group `local`). Detalle en `docs/embeddings.md` y ADR 0005 / 0006.

La decisión de **local-first offline con BM25** y de **no** meter modelos pesados en el dependency set mínimo **sigue vigente**. Lo que se corrige es la overclaim de «híbrido + hashing stub».
