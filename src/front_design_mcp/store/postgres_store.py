"""PostgreSQL + pgvector store implementing :class:`Store` plus search protocols.

Uses a single ``psycopg`` connection guarded by a reentrant lock. ``psycopg_pool``
is not a declared dependency of the ``postgres`` extra, so pooling is intentionally
omitted in favour of this simpler thread-safe approach (MCP tools may run
concurrently; callers serialize on the lock).
"""

from __future__ import annotations

import contextlib
import json
import threading
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.search.base import RankedChunk
from front_design_mcp.store.base import (
    EmbeddingMeta,
    EmbeddingModelRef,
    EmbeddingRecord,
    Store,
    StoreCapabilities,
)

if TYPE_CHECKING:
    from front_design_mcp.search.base import SearchFilters

_REQUIRED_TABLES = ("resources", "chunks", "embeddings", "store_metadata")


def _dim_mismatch_message(*, expected: int, actual: int, context: str) -> str:
    return (
        f"Embedding dimension mismatch ({context}): schema expects {expected}, "
        f"got {actual}. Re-run migrations with the correct "
        f"FRONT_DESIGN_EMBEDDING_DIMENSIONS={expected} (or re-embed with a "
        f"{expected}-dimensional model)."
    )


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return list(value)


class PostgresStore(Store):
    """PostgreSQL-backed store with FTS lexical search and pgvector ANN."""

    backend: str = "postgres"

    def __init__(
        self,
        dsn: str,
        *,
        embedding_dim: int | None = None,
        statement_timeout_ms: int = 15_000,
        auto_open: bool = True,
    ) -> None:
        self._dsn = dsn
        self._requested_embedding_dim = embedding_dim
        self._statement_timeout_ms = statement_timeout_ms
        self._conn: psycopg.Connection[Any] | None = None
        self._lock = threading.RLock()
        self._txn_depth = 0
        self._schema_embedding_dim: int | None = None
        if auto_open:
            self.open()

    # --- lifecycle -------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._conn is not None and not self._conn.closed:
                return
            self._conn = psycopg.connect(self._dsn, row_factory=dict_row)
            register_vector(self._conn)
            # SET does not accept bind parameters; value is a validated int.
            timeout_ms = max(0, int(self._statement_timeout_ms))
            self._conn.execute(f"SET statement_timeout = {timeout_ms}")
            self._verify_vector_extension()
            self._verify_tables()
            self._schema_embedding_dim = self._read_schema_embedding_dim()
            if (
                self._requested_embedding_dim is not None
                and self._requested_embedding_dim != self._schema_embedding_dim
            ):
                dim_schema = self._schema_embedding_dim
                dim_req = self._requested_embedding_dim
                self.close()
                raise ValueError(
                    _dim_mismatch_message(
                        expected=dim_schema,
                        actual=dim_req,
                        context="constructor embedding_dim vs store_metadata",
                    )
                )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    if not self._conn.closed:
                        self._conn.close()
                finally:
                    self._conn = None
                    self._txn_depth = 0

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit on success; roll back on error. Nested calls join the outer txn."""
        with self._lock:
            conn = self._require_conn()
            self._txn_depth += 1
            try:
                yield
                if self._txn_depth == 1:
                    conn.commit()
            except Exception:
                if self._txn_depth == 1:
                    conn.rollback()
                raise
            finally:
                self._txn_depth -= 1

    def capabilities(self) -> StoreCapabilities:
        return StoreCapabilities(
            backend="postgres",
            lexical_search=True,
            vector_search=True,
            embedding_dim=self._schema_dim(),
        )

    # --- resources -------------------------------------------------------

    def upsert_resources(self, resources: Sequence[FrontendResource]) -> None:
        if not resources:
            return
        rows = [self._resource_params(r) for r in resources]
        sql = """
            INSERT INTO resources (
                id, kind, name, description, source_id, source_json,
                homepage_url, docs_url, install_command, license_json,
                supported_frameworks, tags, capabilities,
                accessibility_notes, performance_notes, last_indexed_at,
                attribution, raw_refs_json, updated_at
            ) VALUES (
                %(id)s, %(kind)s, %(name)s, %(description)s, %(source_id)s,
                %(source_json)s, %(homepage_url)s, %(docs_url)s,
                %(install_command)s, %(license_json)s, %(supported_frameworks)s,
                %(tags)s, %(capabilities)s, %(accessibility_notes)s,
                %(performance_notes)s, %(last_indexed_at)s, %(attribution)s,
                %(raw_refs_json)s, now()
            )
            ON CONFLICT (id) DO UPDATE SET
                kind = EXCLUDED.kind,
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                source_id = EXCLUDED.source_id,
                source_json = EXCLUDED.source_json,
                homepage_url = EXCLUDED.homepage_url,
                docs_url = EXCLUDED.docs_url,
                install_command = EXCLUDED.install_command,
                license_json = EXCLUDED.license_json,
                supported_frameworks = EXCLUDED.supported_frameworks,
                tags = EXCLUDED.tags,
                capabilities = EXCLUDED.capabilities,
                accessibility_notes = EXCLUDED.accessibility_notes,
                performance_notes = EXCLUDED.performance_notes,
                last_indexed_at = EXCLUDED.last_indexed_at,
                attribution = EXCLUDED.attribution,
                raw_refs_json = EXCLUDED.raw_refs_json,
                updated_at = now()
        """
        with self._lock:
            conn = self._require_conn()
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            self._commit_if_needed(conn)

    def get_resource(self, resource_id: str) -> FrontendResource | None:
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT * FROM resources WHERE id = %s",
                (resource_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_resource(row)

    def list_resources(
        self,
        *,
        source_id: str | None = None,
        kind: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10_000,
        offset: int = 0,
    ) -> list[FrontendResource]:
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = %s")
            params.append(source_id)
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)
        if tags:
            # Filter in SQL *before* LIMIT/OFFSET (case-insensitive overlap).
            wanted = sorted({t.lower().strip() for t in tags if t.strip()})
            if wanted:
                clauses.append(
                    "(SELECT array_agg(lower(t)) FROM unnest(tags) AS t) "
                    "&& %s::text[]"
                )
                params.append(wanted)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT * FROM resources {where} ORDER BY name LIMIT %s OFFSET %s",
                params,
            ).fetchall()
            return [self._row_to_resource(r) for r in rows]

    def list_resource_ids(self, *, source_id: str | None = None) -> set[str]:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                rows = conn.execute(
                    "SELECT id FROM resources WHERE source_id = %s",
                    (source_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT id FROM resources").fetchall()
            return {str(r["id"]) for r in rows}

    def delete_resources(self, resource_ids: Sequence[str]) -> int:
        if not resource_ids:
            return 0
        with self._lock:
            conn = self._require_conn()
            result = conn.execute(
                "DELETE FROM resources WHERE id = ANY(%s)",
                (list(resource_ids),),
            )
            deleted = result.rowcount if result.rowcount is not None else 0
            self._commit_if_needed(conn)
            return int(deleted)

    def count_resources(self, *, source_id: str | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM resources WHERE source_id = %s",
                    (source_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM resources").fetchone()
            return int(row["n"]) if row else 0

    # --- chunks ----------------------------------------------------------

    def upsert_chunks(self, chunks: Sequence[DocumentationChunk]) -> None:
        if not chunks:
            return
        rows = [self._chunk_params(c) for c in chunks]
        sql = """
            INSERT INTO chunks (
                id, resource_id, title, content, source_url, version,
                license_json, tags, content_sha256, last_indexed_at, updated_at
            ) VALUES (
                %(id)s, %(resource_id)s, %(title)s, %(content)s, %(source_url)s,
                %(version)s, %(license_json)s, %(tags)s, %(content_sha256)s,
                %(last_indexed_at)s, now()
            )
            ON CONFLICT (id) DO UPDATE SET
                resource_id = EXCLUDED.resource_id,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                source_url = EXCLUDED.source_url,
                version = EXCLUDED.version,
                license_json = EXCLUDED.license_json,
                tags = EXCLUDED.tags,
                content_sha256 = EXCLUDED.content_sha256,
                last_indexed_at = EXCLUDED.last_indexed_at,
                updated_at = now()
        """
        with self._lock:
            conn = self._require_conn()
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            self._commit_if_needed(conn)

    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        with self._lock:
            conn = self._require_conn()
            row = conn.execute(
                "SELECT * FROM chunks WHERE id = %s",
                (chunk_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_chunk(row)

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[DocumentationChunk]:
        if not chunk_ids:
            return []
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                "SELECT * FROM chunks WHERE id = ANY(%s)",
                (list(chunk_ids),),
            ).fetchall()
            by_id = {str(r["id"]): self._row_to_chunk(r) for r in rows}
            return [by_id[cid] for cid in chunk_ids if cid in by_id]

    def list_chunks(
        self,
        *,
        resource_id: str | None = None,
        source_id: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[DocumentationChunk]:
        clauses: list[str] = []
        params: list[Any] = []
        join = ""
        if resource_id is not None:
            clauses.append("c.resource_id = %s")
            params.append(resource_id)
        if source_id is not None:
            join = "JOIN resources r ON r.id = c.resource_id"
            clauses.append("r.source_id = %s")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT c.* FROM chunks c {join} {where} "
                f"ORDER BY c.title LIMIT %s OFFSET %s",
                params,
            ).fetchall()
            return [self._row_to_chunk(r) for r in rows]

    def list_chunk_fingerprints(self, *, source_id: str | None = None) -> dict[str, str]:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                rows = conn.execute(
                    """
                    SELECT c.id, c.content_sha256
                    FROM chunks c
                    JOIN resources r ON r.id = c.resource_id
                    WHERE r.source_id = %s
                    """,
                    (source_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, content_sha256 FROM chunks"
                ).fetchall()
            return {str(r["id"]): str(r["content_sha256"]) for r in rows}

    def delete_chunks(self, chunk_ids: Sequence[str]) -> int:
        if not chunk_ids:
            return 0
        with self._lock:
            conn = self._require_conn()
            result = conn.execute(
                "DELETE FROM chunks WHERE id = ANY(%s)",
                (list(chunk_ids),),
            )
            deleted = result.rowcount if result.rowcount is not None else 0
            self._commit_if_needed(conn)
            return int(deleted)

    def count_chunks(self, *, source_id: str | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n
                    FROM chunks c
                    JOIN resources r ON r.id = c.resource_id
                    WHERE r.source_id = %s
                    """,
                    (source_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
            return int(row["n"]) if row else 0

    # --- embeddings ------------------------------------------------------

    def upsert_embeddings(self, records: Sequence[EmbeddingRecord]) -> None:
        if not records:
            return
        schema_dim = self._schema_dim()
        rows: list[dict[str, Any]] = []
        for rec in records:
            vec_len = len(rec.vector)
            if rec.model.dim != schema_dim:
                raise ValueError(
                    _dim_mismatch_message(
                        expected=schema_dim,
                        actual=rec.model.dim,
                        context=f"EmbeddingRecord.model.dim for chunk {rec.chunk_id!r}",
                    )
                )
            if vec_len != schema_dim:
                raise ValueError(
                    _dim_mismatch_message(
                        expected=schema_dim,
                        actual=vec_len,
                        context=f"vector length for chunk {rec.chunk_id!r}",
                    )
                )
            rows.append(
                {
                    "chunk_id": rec.chunk_id,
                    "provider": rec.model.provider,
                    "model": rec.model.model,
                    "dim": rec.model.dim,
                    "pipeline_version": rec.model.pipeline_version,
                    "content_sha256": rec.content_sha256,
                    "embedding": list(rec.vector),
                }
            )
        sql = """
            INSERT INTO embeddings (
                chunk_id, provider, model, dim, pipeline_version,
                content_sha256, embedding
            ) VALUES (
                %(chunk_id)s, %(provider)s, %(model)s, %(dim)s,
                %(pipeline_version)s, %(content_sha256)s, %(embedding)s
            )
            ON CONFLICT (chunk_id) DO UPDATE SET
                provider = EXCLUDED.provider,
                model = EXCLUDED.model,
                dim = EXCLUDED.dim,
                pipeline_version = EXCLUDED.pipeline_version,
                content_sha256 = EXCLUDED.content_sha256,
                embedding = EXCLUDED.embedding,
                created_at = now()
        """
        with self._lock:
            conn = self._require_conn()
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            self._commit_if_needed(conn)

    def get_embedding_metadata(
        self, chunk_ids: Sequence[str] | None = None
    ) -> dict[str, EmbeddingMeta]:
        with self._lock:
            conn = self._require_conn()
            if chunk_ids is None:
                rows = conn.execute(
                    """
                    SELECT chunk_id, provider, model, dim, pipeline_version,
                           content_sha256, created_at
                    FROM embeddings
                    """
                ).fetchall()
            else:
                if not chunk_ids:
                    return {}
                rows = conn.execute(
                    """
                    SELECT chunk_id, provider, model, dim, pipeline_version,
                           content_sha256, created_at
                    FROM embeddings
                    WHERE chunk_id = ANY(%s)
                    """,
                    (list(chunk_ids),),
                ).fetchall()
            return {
                str(r["chunk_id"]): EmbeddingMeta(
                    chunk_id=str(r["chunk_id"]),
                    provider=str(r["provider"]),
                    model=str(r["model"]),
                    dim=int(r["dim"]),
                    pipeline_version=int(r["pipeline_version"]),
                    content_sha256=str(r["content_sha256"]),
                    created_at=r["created_at"],
                )
                for r in rows
            }

    def delete_embeddings(
        self,
        *,
        chunk_ids: Sequence[str] | None = None,
        not_matching: EmbeddingModelRef | None = None,
    ) -> int:
        if chunk_ids is None and not_matching is None:
            return 0
        clauses: list[str] = []
        params: list[Any] = []
        if chunk_ids is not None:
            if not chunk_ids:
                return 0
            clauses.append("chunk_id = ANY(%s)")
            params.append(list(chunk_ids))
        if not_matching is not None:
            clauses.append(
                "NOT (provider = %s AND model = %s AND dim = %s "
                "AND pipeline_version = %s)"
            )
            params.extend(
                [
                    not_matching.provider,
                    not_matching.model,
                    not_matching.dim,
                    not_matching.pipeline_version,
                ]
            )
        where = " AND ".join(clauses)
        with self._lock:
            conn = self._require_conn()
            result = conn.execute(f"DELETE FROM embeddings WHERE {where}", params)
            deleted = result.rowcount if result.rowcount is not None else 0
            self._commit_if_needed(conn)
            return int(deleted)

    def count_embeddings(self, *, model: EmbeddingModelRef | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if model is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM embeddings
                    WHERE provider = %s AND model = %s AND dim = %s
                          AND pipeline_version = %s
                    """,
                    (model.provider, model.model, model.dim, model.pipeline_version),
                ).fetchone()
            return int(row["n"]) if row else 0

    # --- search (LexicalSearcher / VectorSearcher) -----------------------

    def search_lexical(
        self, query: str, *, filters: SearchFilters, limit: int
    ) -> list[RankedChunk]:
        """Full-text search ranked by ``ts_rank_cd``.

        Tries the user's query as written first (``websearch_to_tsquery`` honours
        quoted phrases and ``-exclusions``), which requires every term to be
        present. Natural-language queries rarely satisfy that, so a second pass
        relaxes the conjunction to a disjunction — the same behaviour BM25 gives
        on the SQLite backend, and what makes the two backends comparable.
        ``ts_rank_cd`` still ranks documents matching more terms higher.
        """
        if not query.strip() or filters.excludes_everything or limit <= 0:
            return []
        with self._lock:
            conn = self._require_conn()
            where_extra, filter_params = self._filter_clauses(filters, table_alias="r")
            sql = f"""
                SELECT c.id AS chunk_id,
                       ts_rank_cd(c.search_vector, %s::tsquery) AS score
                FROM chunks c
                JOIN resources r ON r.id = c.resource_id
                WHERE c.search_vector @@ %s::tsquery
                {where_extra}
                ORDER BY score DESC, c.id ASC
                LIMIT %s
            """
            for tsquery in self._tsquery_variants(conn, query):
                bind: list[Any] = [tsquery, tsquery, *filter_params, limit]
                rows = conn.execute(sql, bind).fetchall()
                if rows:
                    return [
                        RankedChunk(
                            chunk_id=str(r["chunk_id"]),
                            score=float(r["score"]),
                            rank=i,
                        )
                        for i, r in enumerate(rows, start=1)
                    ]
            return []

    def _tsquery_variants(self, conn: psycopg.Connection[Any], query: str) -> list[str]:
        """Strict query first, then an OR-relaxed one. Empty when nothing parses.

        Both strings are produced by PostgreSQL's own parsers and re-bound as
        parameters cast to ``tsquery``, so no user text reaches SQL unescaped.
        """
        row = conn.execute(
            "SELECT websearch_to_tsquery('english', %s)::text AS strict, "
            "plainto_tsquery('english', %s)::text AS plain",
            (query, query),
        ).fetchone()
        if row is None:
            return []
        variants: list[str] = []
        strict = row["strict"]
        if strict:
            variants.append(str(strict))
        plain = row["plain"]
        if plain:
            relaxed = str(plain).replace(" & ", " | ")
            if relaxed not in variants:
                variants.append(relaxed)
        return variants

    def search_vector(
        self,
        embedding: Sequence[float],
        *,
        filters: SearchFilters,
        limit: int,
        model: EmbeddingModelRef,
    ) -> list[RankedChunk]:
        """Rank by cosine similarity: ``score = 1 - (embedding <=> query)``.

        pgvector's ``<=>`` operator is cosine *distance* (0 = identical); we
        convert to a higher-is-better similarity for consistent ranking.

        Only rows whose provider/model/dim/pipeline_version match ``model``
        participate — mixed identities must never share a ranking.
        """
        if filters.excludes_everything or limit <= 0:
            return []
        schema_dim = self._schema_dim()
        if len(embedding) != schema_dim:
            raise ValueError(
                _dim_mismatch_message(
                    expected=schema_dim,
                    actual=len(embedding),
                    context="search_vector query embedding",
                )
            )
        if model.dim != schema_dim:
            raise ValueError(
                _dim_mismatch_message(
                    expected=schema_dim,
                    actual=model.dim,
                    context="search_vector model.dim",
                )
            )
        with self._lock:
            conn = self._require_conn()
            count_row = conn.execute(
                """
                SELECT COUNT(*) AS n FROM embeddings
                WHERE provider = %s AND model = %s AND dim = %s
                  AND pipeline_version = %s
                """,
                (model.provider, model.model, model.dim, model.pipeline_version),
            ).fetchone()
            if not count_row or int(count_row["n"]) == 0:
                return []

            where_extra, filter_params = self._filter_clauses(filters, table_alias="r")
            vec = list(embedding)
            sql = f"""
                SELECT e.chunk_id,
                       (1 - (e.embedding <=> %s::vector)) AS score
                FROM embeddings e
                JOIN chunks c ON c.id = e.chunk_id
                JOIN resources r ON r.id = c.resource_id
                WHERE e.provider = %s
                  AND e.model = %s
                  AND e.dim = %s
                  AND e.pipeline_version = %s
                {where_extra}
                ORDER BY e.embedding <=> %s::vector ASC, e.chunk_id ASC
                LIMIT %s
            """
            bind: list[Any] = [
                vec,
                model.provider,
                model.model,
                model.dim,
                model.pipeline_version,
                *filter_params,
                vec,
                limit,
            ]
            rows = conn.execute(sql, bind).fetchall()
            return [
                RankedChunk(
                    chunk_id=str(r["chunk_id"]),
                    score=float(r["score"]),
                    rank=i,
                )
                for i, r in enumerate(rows, start=1)
            ]

    # --- introspection ---------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._require_conn()
            resources_row = conn.execute(
                "SELECT COUNT(*) AS n FROM resources"
            ).fetchone()
            chunks_row = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
            embeddings_row = conn.execute(
                "SELECT COUNT(*) AS n FROM embeddings"
            ).fetchone()
            models = conn.execute(
                """
                SELECT DISTINCT provider, model, dim, pipeline_version
                FROM embeddings
                ORDER BY provider, model, dim, pipeline_version
                """
            ).fetchall()
            ext = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            return {
                "backend": "postgres",
                "resource_count": int(resources_row["n"]) if resources_row else 0,
                "chunk_count": int(chunks_row["n"]) if chunks_row else 0,
                "embedding_count": int(embeddings_row["n"]) if embeddings_row else 0,
                "embedding_dim": self._schema_dim(),
                "embedding_models": [
                    {
                        "provider": str(m["provider"]),
                        "model": str(m["model"]),
                        "dim": int(m["dim"]),
                        "pipeline_version": int(m["pipeline_version"]),
                    }
                    for m in models
                ],
                "pgvector_version": str(ext["extversion"]) if ext else None,
            }

    # --- internals -------------------------------------------------------

    def _require_conn(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            raise RuntimeError(
                "PostgresStore is closed; call open() before using the store."
            )
        return self._conn

    def _commit_if_needed(self, conn: psycopg.Connection[Any]) -> None:
        if self._txn_depth == 0:
            conn.commit()

    def _schema_dim(self) -> int:
        if self._schema_embedding_dim is None:
            raise RuntimeError("PostgresStore is not open (schema dim unknown).")
        return self._schema_embedding_dim

    def _verify_vector_extension(self) -> None:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT 1 AS ok FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "PostgreSQL extension 'vector' (pgvector) is not installed. "
                "Run: CREATE EXTENSION vector; "
                "or apply migrations with `alembic upgrade head`."
            )

    def _verify_tables(self) -> None:
        assert self._conn is not None
        rows = self._conn.execute(
            """
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public' AND tablename = ANY(%s)
            """,
            (list(_REQUIRED_TABLES),),
        ).fetchall()
        found = {str(r["tablename"]) for r in rows}
        missing = [t for t in _REQUIRED_TABLES if t not in found]
        if missing:
            raise RuntimeError(
                "PostgreSQL schema is incomplete "
                f"(missing tables: {', '.join(missing)}). "
                "Run migrations: `alembic upgrade head` "
                "(requires FRONT_DESIGN_DATABASE_URL)."
            )

    def _read_schema_embedding_dim(self) -> int:
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM store_metadata WHERE key = 'embedding_dim'"
        ).fetchone()
        if row is None:
            raise RuntimeError(
                "store_metadata is missing key 'embedding_dim'. "
                "Re-run `alembic upgrade head`."
            )
        return int(row["value"])

    def _filter_clauses(
        self, filters: SearchFilters, *, table_alias: str
    ) -> tuple[str, list[Any]]:
        """Build ``AND …`` SQL fragments applied before LIMIT."""
        parts: list[str] = []
        params: list[Any] = []
        a = table_alias
        if filters.source_id is not None:
            parts.append(f"AND {a}.source_id = %s")
            params.append(filters.source_id)
        if filters.kind is not None:
            parts.append(f"AND {a}.kind = %s")
            params.append(filters.kind)
        if filters.tags:
            parts.append(
                f"AND (SELECT array_agg(lower(t)) FROM unnest({a}.tags) AS t) "
                f"&& %s::text[]"
            )
            params.append(list(filters.tags))
        if filters.resource_ids is not None:
            parts.append(f"AND {a}.id = ANY(%s)")
            params.append(list(filters.resource_ids))
        return (" ".join(parts), params)

    @staticmethod
    def _resource_params(resource: FrontendResource) -> dict[str, Any]:
        return {
            "id": resource.id,
            "kind": resource.kind.value,
            "name": resource.name,
            "description": resource.description,
            "source_id": resource.source.source_id,
            "source_json": Jsonb(resource.source.model_dump(mode="json")),
            "homepage_url": resource.homepage_url,
            "docs_url": resource.docs_url,
            "install_command": resource.install_command,
            "license_json": (
                Jsonb(resource.license.model_dump(mode="json"))
                if resource.license
                else None
            ),
            "supported_frameworks": list(resource.supported_frameworks),
            "tags": list(resource.tags),
            "capabilities": list(resource.capabilities),
            "accessibility_notes": resource.accessibility_notes,
            "performance_notes": resource.performance_notes,
            "last_indexed_at": resource.last_indexed_at,
            "attribution": resource.attribution,
            "raw_refs_json": Jsonb(resource.raw_refs),
        }

    @staticmethod
    def _chunk_params(chunk: DocumentationChunk) -> dict[str, Any]:
        return {
            "id": chunk.id,
            "resource_id": chunk.resource_id,
            "title": chunk.title,
            "content": chunk.content,
            "source_url": chunk.source_url,
            "version": chunk.version,
            "license_json": (
                Jsonb(chunk.license.model_dump(mode="json")) if chunk.license else None
            ),
            "tags": list(chunk.tags),
            "content_sha256": chunk.content_sha256,
            "last_indexed_at": chunk.last_indexed_at,
        }

    @staticmethod
    def _row_to_resource(row: dict[str, Any]) -> FrontendResource:
        source_raw = row["source_json"]
        source = (
            SourceRef.model_validate(source_raw)
            if not isinstance(source_raw, str)
            else SourceRef.model_validate_json(source_raw)
        )
        license_raw = row["license_json"]
        license_info: LicenseInfo | None
        if license_raw is None:
            license_info = None
        elif isinstance(license_raw, str):
            license_info = LicenseInfo.model_validate_json(license_raw)
        else:
            license_info = LicenseInfo.model_validate(license_raw)
        raw_refs = row["raw_refs_json"] or {}
        if isinstance(raw_refs, str):
            raw_refs = json.loads(raw_refs)
        last_indexed: datetime | None = row["last_indexed_at"]
        return FrontendResource(
            id=str(row["id"]),
            kind=ResourceKind(row["kind"]),
            name=str(row["name"]),
            description=str(row["description"] or ""),
            source=source,
            homepage_url=row["homepage_url"],
            docs_url=row["docs_url"],
            install_command=row["install_command"],
            license=license_info,
            supported_frameworks=_as_str_list(row["supported_frameworks"]),
            tags=_as_str_list(row["tags"]),
            capabilities=_as_str_list(row["capabilities"]),
            accessibility_notes=row["accessibility_notes"],
            performance_notes=row["performance_notes"],
            last_indexed_at=last_indexed,
            attribution=row["attribution"],
            raw_refs=dict(raw_refs),
        )

    @staticmethod
    def _row_to_chunk(row: dict[str, Any]) -> DocumentationChunk:
        license_raw = row["license_json"]
        license_info: LicenseInfo | None
        if license_raw is None:
            license_info = None
        elif isinstance(license_raw, str):
            license_info = LicenseInfo.model_validate_json(license_raw)
        else:
            license_info = LicenseInfo.model_validate(license_raw)
        return DocumentationChunk(
            id=str(row["id"]),
            resource_id=str(row["resource_id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            source_url=row["source_url"],
            version=row["version"],
            license=license_info,
            tags=_as_str_list(row["tags"]),
            last_indexed_at=row["last_indexed_at"],
            content_sha256=str(row["content_sha256"]),
        )


__all__ = ["PostgresStore"]
