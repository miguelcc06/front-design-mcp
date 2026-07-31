# ADR 0005 — Storage backend selection (SQLite vs PostgreSQL)

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

El modo mínimo debe arrancar sin servicios externos (solo Python + SQLite + fixtures). A la vez, un subset de usuarios necesita búsqueda híbrida real (léxico + vectores) y un store compartido. Meter SQLAlchemy/Alembic/pgvector en las dependencias por defecto contradice el non-goal de «minimal offline».

ADR 0002 afirmaba un search «híbrido» sobre SQLite con un stub de embeddings que **nunca existió** (corregido allí). Hace falta una decisión explícita de **dos backends** detrás de una sola interfaz.

## Decision

Soportar **dos backends** detrás de la interfaz `Store` en `store/base.py`:

| Backend | Cuándo | Migraciones | Retrieval |
|---------|--------|-------------|-----------|
| **SQLite** (default) | Offline, cero servicios | Forward-only vía `PRAGMA user_version` en `store/sqlite_schema.py` | Solo BM25 in-process (`rank-bm25`). **Sin** vector search ni híbrido. |
| **PostgreSQL + pgvector** (opt-in) | `FRONT_DESIGN_STORE_BACKEND=postgres` + extra `postgres` | Alembic en `migrations/` | FTS (`tsvector` / `ts_rank_cd`) + ANN cosine (HNSW); híbrido vía RRF (ADR 0006) |

### Interfaz y factory

- El contrato vive en `store/base.py` (`Store`, `StoreCapabilities`, embeddings metadata, transacciones).
- **Nada fuera de `store/factory.py` debe importar un store concreto.** `create_store(settings)` instancia `SqliteStore` o carga lazy `PostgresStore` (así el import de `psycopg`/`pgvector` no rompe el modo SQLite).
- Capacidades se reportan honestamente: SQLite declara `vector_search=False`.

### Por qué SQLite no usa Alembic

Alembic arrastra SQLAlchemy. Eso contaminaría el dependency set mínimo (non-goal explícito). En su lugar:

- Constante `SCHEMA_VERSION` (hoy `2`) en `store/sqlite_schema.py`.
- Runner forward-only: si `PRAGMA user_version` &lt; `SCHEMA_VERSION`, aplica el DDL v2 (o el upgrade legacy) y escribe `user_version`.
- **Trade-off:** sin autogenerate, sin downgrade, sin historial de revisiones. Solo avance. Suficiente para un esquema local pequeño.

### Upgrade legacy (v0.1 → v2)

Bases SQLite creadas antes del versionado tenían `user_version = 0` y una tabla `embeddings` stub (`chunk_id`, `provider`, `dims`, `blob`, `created_at`) que **nada leía**.

`_upgrade_legacy_to_v2` hace, en orden:

1. Añade columnas faltantes `created_at` / `updated_at` en `resources` y `chunks` (ALTER; SQLite no permite default no-constante en ADD COLUMN).
2. Backfill de timestamps con `COALESCE(..., datetime('now'))` — **no destructivo** para filas existentes.
3. Si `embeddings` existe con el esquema stub (columnas distintas del v2), **DROP** y se recrea con el DDL v2 (provider, model, dim, pipeline_version, content_sha256, vector BLOB). Las filas stub se pierden a propósito (eran basura).
4. `CREATE TABLE IF NOT EXISTS` del resto del esquema v2 + índices.
5. `PRAGMA user_version = 2`.

**Resources y chunks se preservan.** Solo se descartan embeddings stub.

PostgreSQL no tiene este path: se parte de migraciones Alembic limpias.

## Consequences

- Un solo código de tools/search puede hablar con `Store`; el backend se elige por config.
- Quién se queda en SQLite **pierde**: búsqueda vectorial, híbrido RRF, FTS nativo en DB, store multi-proceso compartido vía red, índices HNSW. Gana: cero ops, backup = copiar un fichero, re-derivable desde fixtures.
- Quién activa Postgres debe instalar `uv sync --extra postgres`, correr `alembic upgrade head`, y (para vectores) un embedding provider real. Ver `docs/postgres.md`.
- Pooling **no implementado**: `PostgresStore` usa una sola conexión con lock reentrante (`psycopg_pool` no está en el extra). No se exponen ajustes de pool para no prometer una capacidad ausente; las llamadas MCP concurrentes se serializan.
- La dimensión del vector en Postgres se fija **en migration time** (`FRONT_DESIGN_EMBEDDING_DIMENSIONS`) y se guarda en `store_metadata`; un cambio de dimensión implica migración fresca + re-embedding (ADR 0006 / `docs/embeddings.md`).
