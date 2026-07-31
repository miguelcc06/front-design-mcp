"""SQLite-backed store — the offline default backend.

Lexical retrieval for this backend is the in-process BM25 index
(:mod:`front_design_mcp.search.lexical`); the store's job is to persist rows and
to resolve filters *in SQL* so ranking never sees excluded chunks. Vectors can be
persisted here but there is no ANN index, so vector search is not offered.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from array import array
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.store.base import (
    EmbeddingMeta,
    EmbeddingModelRef,
    EmbeddingRecord,
    Store,
    StoreCapabilities,
)
from front_design_mcp.store.sqlite_schema import SCHEMA_VERSION, migrate

if TYPE_CHECKING:
    from front_design_mcp.search.base import SearchFilters


def _dt_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _dumps(obj: Any) -> str:
    return json.dumps(obj, default=str)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    return json.loads(raw)


def _pack_vector(vector: Sequence[float]) -> bytes:
    return array("f", vector).tobytes()


def _unpack_vector(blob: bytes) -> list[float]:
    values = array("f")
    values.frombytes(blob)
    return list(values)


class SqliteStore(Store):
    """SQLite store with batched writes, hash fingerprints, and real embeddings."""

    backend: str = "sqlite"

    def __init__(self, db_path: Path | str, *, auto_open: bool = True) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._txn_depth = 0
        if auto_open:
            self.open()

    # --- lifecycle -------------------------------------------------------

    def open(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            migrate(conn)
            self._conn = conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
                self._txn_depth = 0

    @contextlib.contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit on success, roll back on error; nested calls join the outer one."""
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
            backend="sqlite",
            lexical_search=True,
            vector_search=False,
            embedding_dim=self._stored_embedding_dim(),
        )

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    def _commit_if_needed(self, conn: sqlite3.Connection) -> None:
        if self._txn_depth == 0:
            conn.commit()

    # --- resources -------------------------------------------------------

    _RESOURCE_UPSERT = """
        INSERT INTO resources (
            id, kind, name, description, source_id, source_json,
            homepage_url, docs_url, install_command, license_json,
            supported_frameworks, tags, capabilities,
            accessibility_notes, performance_notes, last_indexed_at,
            attribution, raw_refs_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            kind=excluded.kind,
            name=excluded.name,
            description=excluded.description,
            source_id=excluded.source_id,
            source_json=excluded.source_json,
            homepage_url=excluded.homepage_url,
            docs_url=excluded.docs_url,
            install_command=excluded.install_command,
            license_json=excluded.license_json,
            supported_frameworks=excluded.supported_frameworks,
            tags=excluded.tags,
            capabilities=excluded.capabilities,
            accessibility_notes=excluded.accessibility_notes,
            performance_notes=excluded.performance_notes,
            last_indexed_at=excluded.last_indexed_at,
            attribution=excluded.attribution,
            raw_refs_json=excluded.raw_refs_json,
            updated_at=excluded.updated_at
    """

    def upsert_resources(self, resources: Sequence[FrontendResource]) -> None:
        if not resources:
            return
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                r.id,
                r.kind.value,
                r.name,
                r.description,
                r.source.source_id,
                r.source.model_dump_json(),
                r.homepage_url,
                r.docs_url,
                r.install_command,
                r.license.model_dump_json() if r.license else None,
                _dumps(r.supported_frameworks),
                _dumps(r.tags),
                _dumps(r.capabilities),
                r.accessibility_notes,
                r.performance_notes,
                _dt_to_str(r.last_indexed_at),
                r.attribution,
                _dumps(r.raw_refs),
                now,
                now,
            )
            for r in resources
        ]
        with self._lock:
            conn = self._require_conn()
            conn.executemany(self._RESOURCE_UPSERT, rows)
            self._commit_if_needed(conn)

    def get_resource(self, resource_id: str) -> FrontendResource | None:
        with self._lock:
            conn = self._require_conn()
            row = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
            return self._row_to_resource(row) if row is not None else None

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
            clauses.append("source_id = ?")
            params.append(source_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        wanted = sorted({t.lower().strip() for t in (tags or []) if t.strip()})
        if wanted:
            # Tags are a JSON array; match with a lowercased LIKE per tag so the
            # filter runs before LIMIT/OFFSET instead of after (v0.1 bug).
            tag_clauses = " OR ".join(["lower(tags) LIKE ?"] * len(wanted))
            clauses.append(f"({tag_clauses})")
            params.extend([f'%"{t}"%' for t in wanted])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT * FROM resources {where} ORDER BY name LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        resources = [self._row_to_resource(r) for r in rows]
        if not wanted:
            return resources
        # LIKE is a coarse pre-filter (substring match inside the JSON array);
        # re-check exactly so semantics equal the PostgreSQL array overlap.
        wanted_set = set(wanted)
        return [r for r in resources if wanted_set & {t.lower() for t in r.tags}]

    def list_resource_ids(self, *, source_id: str | None = None) -> set[str]:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                rows = conn.execute(
                    "SELECT id FROM resources WHERE source_id = ?", (source_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT id FROM resources").fetchall()
        return {str(r["id"]) for r in rows}

    def delete_resources(self, resource_ids: Sequence[str]) -> int:
        if not resource_ids:
            return 0
        ids = list(resource_ids)
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            conn = self._require_conn()
            cur = conn.execute(f"DELETE FROM resources WHERE id IN ({placeholders})", ids)
            deleted = cur.rowcount or 0
            self._commit_if_needed(conn)
        return int(deleted)

    def count_resources(self, *, source_id: str | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM resources WHERE source_id = ?", (source_id,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM resources").fetchone()
        return int(row["n"]) if row else 0

    # --- chunks ----------------------------------------------------------

    _CHUNK_UPSERT = """
        INSERT INTO chunks (
            id, resource_id, title, content, source_url, version,
            license_json, tags, last_indexed_at, content_sha256,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            resource_id=excluded.resource_id,
            title=excluded.title,
            content=excluded.content,
            source_url=excluded.source_url,
            version=excluded.version,
            license_json=excluded.license_json,
            tags=excluded.tags,
            last_indexed_at=excluded.last_indexed_at,
            content_sha256=excluded.content_sha256,
            updated_at=excluded.updated_at
    """

    def upsert_chunks(self, chunks: Sequence[DocumentationChunk]) -> None:
        if not chunks:
            return
        now = datetime.now(UTC).isoformat()
        rows = [
            (
                c.id,
                c.resource_id,
                c.title,
                c.content,
                c.source_url,
                c.version,
                c.license.model_dump_json() if c.license else None,
                _dumps(c.tags),
                _dt_to_str(c.last_indexed_at),
                c.content_sha256,
                now,
                now,
            )
            for c in chunks
        ]
        with self._lock:
            conn = self._require_conn()
            conn.executemany(self._CHUNK_UPSERT, rows)
            self._commit_if_needed(conn)

    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        with self._lock:
            conn = self._require_conn()
            row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return self._row_to_chunk(row) if row is not None else None

    def get_chunks(self, chunk_ids: Sequence[str]) -> list[DocumentationChunk]:
        if not chunk_ids:
            return []
        ids = list(chunk_ids)
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT * FROM chunks WHERE id IN ({placeholders})", ids
            ).fetchall()
        by_id = {str(r["id"]): self._row_to_chunk(r) for r in rows}
        return [by_id[cid] for cid in ids if cid in by_id]

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
            clauses.append("c.resource_id = ?")
            params.append(resource_id)
        if source_id is not None:
            join = "JOIN resources r ON r.id = c.resource_id"
            clauses.append("r.source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT c.* FROM chunks c {join} {where} ORDER BY c.title LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def list_chunk_fingerprints(self, *, source_id: str | None = None) -> dict[str, str]:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                rows = conn.execute(
                    "SELECT c.id, c.content_sha256 FROM chunks c "
                    "JOIN resources r ON r.id = c.resource_id WHERE r.source_id = ?",
                    (source_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT id, content_sha256 FROM chunks").fetchall()
        return {str(r["id"]): str(r["content_sha256"]) for r in rows}

    def delete_chunks(self, chunk_ids: Sequence[str]) -> int:
        if not chunk_ids:
            return 0
        ids = list(chunk_ids)
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            conn = self._require_conn()
            cur = conn.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)
            deleted = cur.rowcount or 0
            self._commit_if_needed(conn)
        return int(deleted)

    def count_chunks(self, *, source_id: str | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if source_id is not None:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM chunks c "
                    "JOIN resources r ON r.id = c.resource_id WHERE r.source_id = ?",
                    (source_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return int(row["n"]) if row else 0

    # --- filter resolution ----------------------------------------------

    def resolve_filtered_chunk_ids(self, filters: SearchFilters) -> frozenset[str] | None:
        """Chunk ids allowed by ``filters``, or None when nothing is filtered.

        Resolved in SQL so the BM25 index only ever ranks eligible chunks.
        """
        if filters.is_empty:
            return None
        if filters.excludes_everything:
            return frozenset()

        clauses: list[str] = []
        params: list[Any] = []
        if filters.source_id is not None:
            clauses.append("r.source_id = ?")
            params.append(filters.source_id)
        if filters.kind is not None:
            clauses.append("r.kind = ?")
            params.append(filters.kind)
        if filters.resource_ids is not None:
            ids = sorted(filters.resource_ids)
            placeholders = ",".join("?" * len(ids))
            clauses.append(f"r.id IN ({placeholders})")
            params.extend(ids)
        if filters.tags:
            # Tags may live on the resource or the chunk; either may match.
            tag_clauses = " OR ".join(
                ["lower(r.tags) LIKE ?"] * len(filters.tags)
                + ["lower(c.tags) LIKE ?"] * len(filters.tags)
            )
            clauses.append(f"({tag_clauses})")
            params.extend([f'%"{t}"%' for t in filters.tags] * 2)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(
                f"SELECT c.id, c.tags AS chunk_tags, r.tags AS resource_tags "
                f"FROM chunks c JOIN resources r ON r.id = c.resource_id {where}",
                params,
            ).fetchall()

        if not filters.tags:
            return frozenset(str(r["id"]) for r in rows)
        wanted = set(filters.tags)
        allowed: set[str] = set()
        for row in rows:
            chunk_tags = {str(t).lower() for t in _loads(row["chunk_tags"], [])}
            resource_tags = {str(t).lower() for t in _loads(row["resource_tags"], [])}
            if wanted & (chunk_tags | resource_tags):
                allowed.add(str(row["id"]))
        return frozenset(allowed)

    # --- embeddings ------------------------------------------------------

    def upsert_embeddings(self, records: Sequence[EmbeddingRecord]) -> None:
        if not records:
            return
        stored_dim = self._stored_embedding_dim()
        rows: list[tuple[Any, ...]] = []
        now = datetime.now(UTC).isoformat()
        for rec in records:
            vector = list(rec.vector)
            if len(vector) != rec.model.dim:
                raise ValueError(
                    f"Embedding for chunk {rec.chunk_id!r} has {len(vector)} values but "
                    f"model {rec.model.key} declares dim={rec.model.dim}."
                )
            if stored_dim is not None and rec.model.dim != stored_dim:
                raise ValueError(
                    f"Embedding dimension mismatch: store already holds "
                    f"{stored_dim}-dimensional vectors, got {rec.model.dim} for chunk "
                    f"{rec.chunk_id!r}. Re-embed the corpus or clear the embeddings table."
                )
            rows.append(
                (
                    rec.chunk_id,
                    rec.model.provider,
                    rec.model.model,
                    rec.model.dim,
                    rec.model.pipeline_version,
                    rec.content_sha256,
                    _pack_vector(vector),
                    now,
                )
            )
        with self._lock:
            conn = self._require_conn()
            conn.executemany(
                """
                INSERT INTO embeddings (
                    chunk_id, provider, model, dim, pipeline_version,
                    content_sha256, vector, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    provider=excluded.provider,
                    model=excluded.model,
                    dim=excluded.dim,
                    pipeline_version=excluded.pipeline_version,
                    content_sha256=excluded.content_sha256,
                    vector=excluded.vector,
                    created_at=excluded.created_at
                """,
                rows,
            )
            self._commit_if_needed(conn)

    def get_embedding_metadata(
        self, chunk_ids: Sequence[str] | None = None
    ) -> dict[str, EmbeddingMeta]:
        sql = (
            "SELECT chunk_id, provider, model, dim, pipeline_version, "
            "content_sha256, created_at FROM embeddings"
        )
        params: list[Any] = []
        if chunk_ids is not None:
            ids = list(chunk_ids)
            if not ids:
                return {}
            sql += f" WHERE chunk_id IN ({','.join('?' * len(ids))})"
            params = ids
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(sql, params).fetchall()
        return {
            str(r["chunk_id"]): EmbeddingMeta(
                chunk_id=str(r["chunk_id"]),
                provider=str(r["provider"]),
                model=str(r["model"]),
                dim=int(r["dim"]),
                pipeline_version=int(r["pipeline_version"]),
                content_sha256=str(r["content_sha256"]),
                created_at=_str_to_dt(r["created_at"]),
            )
            for r in rows
        }

    def get_embedding_vectors(
        self, chunk_ids: Sequence[str] | None = None
    ) -> dict[str, list[float]]:
        """Raw vectors by chunk id. Used by tests and offline evaluation."""
        sql = "SELECT chunk_id, vector FROM embeddings"
        params: list[Any] = []
        if chunk_ids is not None:
            ids = list(chunk_ids)
            if not ids:
                return {}
            sql += f" WHERE chunk_id IN ({','.join('?' * len(ids))})"
            params = ids
        with self._lock:
            conn = self._require_conn()
            rows = conn.execute(sql, params).fetchall()
        return {str(r["chunk_id"]): _unpack_vector(bytes(r["vector"])) for r in rows}

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
            ids = list(chunk_ids)
            if not ids:
                return 0
            clauses.append(f"chunk_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        if not_matching is not None:
            clauses.append(
                "NOT (provider = ? AND model = ? AND dim = ? AND pipeline_version = ?)"
            )
            params.extend(
                [
                    not_matching.provider,
                    not_matching.model,
                    not_matching.dim,
                    not_matching.pipeline_version,
                ]
            )
        with self._lock:
            conn = self._require_conn()
            cur = conn.execute(
                f"DELETE FROM embeddings WHERE {' AND '.join(clauses)}", params
            )
            deleted = cur.rowcount or 0
            self._commit_if_needed(conn)
        return int(deleted)

    def count_embeddings(self, *, model: EmbeddingModelRef | None = None) -> int:
        with self._lock:
            conn = self._require_conn()
            if model is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM embeddings WHERE provider = ? AND model = ? "
                    "AND dim = ? AND pipeline_version = ?",
                    (model.provider, model.model, model.dim, model.pipeline_version),
                ).fetchone()
        return int(row["n"]) if row else 0

    def _stored_embedding_dim(self) -> int | None:
        with self._lock:
            conn = self._require_conn()
            row = conn.execute("SELECT DISTINCT dim FROM embeddings LIMIT 2").fetchall()
        if len(row) == 1:
            return int(row[0]["dim"])
        return None

    # --- introspection ---------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._require_conn()
            models = conn.execute(
                "SELECT DISTINCT provider, model, dim, pipeline_version FROM embeddings "
                "ORDER BY provider, model, dim, pipeline_version"
            ).fetchall()
            version_row = conn.execute("PRAGMA user_version").fetchone()
        return {
            "backend": "sqlite",
            "db_path": str(self.db_path),
            "schema_version": int(version_row[0]) if version_row else SCHEMA_VERSION,
            "resource_count": self.count_resources(),
            "chunk_count": self.count_chunks(),
            "embedding_count": self.count_embeddings(),
            "embedding_dim": self._stored_embedding_dim(),
            "embedding_models": [
                {
                    "provider": str(m["provider"]),
                    "model": str(m["model"]),
                    "dim": int(m["dim"]),
                    "pipeline_version": int(m["pipeline_version"]),
                }
                for m in models
            ],
        }

    # --- row mapping -----------------------------------------------------

    def _row_to_resource(self, row: sqlite3.Row) -> FrontendResource:
        source = SourceRef.model_validate_json(row["source_json"])
        license_info = (
            LicenseInfo.model_validate_json(row["license_json"]) if row["license_json"] else None
        )
        return FrontendResource(
            id=row["id"],
            kind=ResourceKind(row["kind"]),
            name=row["name"],
            description=row["description"] or "",
            source=source,
            homepage_url=row["homepage_url"],
            docs_url=row["docs_url"],
            install_command=row["install_command"],
            license=license_info,
            supported_frameworks=_loads(row["supported_frameworks"], []),
            tags=_loads(row["tags"], []),
            capabilities=_loads(row["capabilities"], []),
            accessibility_notes=row["accessibility_notes"],
            performance_notes=row["performance_notes"],
            last_indexed_at=_str_to_dt(row["last_indexed_at"]),
            attribution=row["attribution"],
            raw_refs=_loads(row["raw_refs_json"], {}),
        )

    def _row_to_chunk(self, row: sqlite3.Row) -> DocumentationChunk:
        license_info = (
            LicenseInfo.model_validate_json(row["license_json"]) if row["license_json"] else None
        )
        return DocumentationChunk(
            id=row["id"],
            resource_id=row["resource_id"],
            title=row["title"],
            content=row["content"],
            source_url=row["source_url"],
            version=row["version"],
            license=license_info,
            tags=_loads(row["tags"], []),
            last_indexed_at=_str_to_dt(row["last_indexed_at"]),
            content_sha256=row["content_sha256"],
        )


__all__ = ["SqliteStore"]
