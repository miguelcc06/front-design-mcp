# ADR 0002 — Local hybrid search (BM25 + optional embeddings)

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

El servidor debe descubrir componentes, patrones y docs con ranking útil, sin depender de APIs de pago ni de modelos de embedding pesados en el modo mínimo.

## Decision

Search v1 es **híbrido local-first**:

1. **Primario:** índice léxico **BM25** (`rank-bm25`), reconstruible en memoria desde el store SQLite.
2. **Opcional:** interfaz de embedding provider; stub **hashing/local** que funciona sin API keys.
3. **No** incluir `sentence-transformers` en dependencias por defecto (extras opcionales futuros).
4. Persistencia: **SQLite** + fixtures offline; network ingest opt-in (`FRONT_DESIGN_ENABLE_NETWORK_INGEST=false` por defecto).

## Consequences

- Modo mínimo funciona offline sin claves
- Calidad semántica limitada hasta activar un provider real
- El diseño de interfaces permite añadir providers sin reescribir el store
