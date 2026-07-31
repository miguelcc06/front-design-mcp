"""SQLite-backed store — minimal schema and CRUD for Package A."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.store.base import Store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_id TEXT NOT NULL,
    source_json TEXT NOT NULL,
    homepage_url TEXT,
    docs_url TEXT,
    install_command TEXT,
    license_json TEXT,
    supported_frameworks TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    capabilities TEXT NOT NULL DEFAULT '[]',
    accessibility_notes TEXT,
    performance_notes TEXT,
    last_indexed_at TEXT,
    attribution TEXT,
    raw_refs_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source_id);
CREATE INDEX IF NOT EXISTS idx_resources_kind ON resources(kind);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT,
    version TEXT,
    license_json TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    last_indexed_at TEXT,
    content_sha256 TEXT NOT NULL,
    FOREIGN KEY (resource_id) REFERENCES resources(id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_resource ON chunks(resource_id);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    dims INTEGER NOT NULL DEFAULT 0,
    blob BLOB,
    created_at TEXT,
    PRIMARY KEY (chunk_id, provider),
    FOREIGN KEY (chunk_id) REFERENCES chunks(id)
);
"""


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


class SqliteStore(Store):
    """Minimal SQLite store that can open a DB and upsert/list resources & chunks."""

    def __init__(self, db_path: Path | str, *, auto_open: bool = True) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        if auto_open:
            self.open()

    def open(self) -> None:
        if self._conn is not None:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.open()
        assert self._conn is not None
        return self._conn

    def upsert_resource(self, resource: FrontendResource) -> None:
        conn = self._require_conn()
        conn.execute(
            """
            INSERT INTO resources (
                id, kind, name, description, source_id, source_json,
                homepage_url, docs_url, install_command, license_json,
                supported_frameworks, tags, capabilities,
                accessibility_notes, performance_notes, last_indexed_at,
                attribution, raw_refs_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                raw_refs_json=excluded.raw_refs_json
            """,
            (
                resource.id,
                resource.kind.value,
                resource.name,
                resource.description,
                resource.source.source_id,
                resource.source.model_dump_json(),
                resource.homepage_url,
                resource.docs_url,
                resource.install_command,
                resource.license.model_dump_json() if resource.license else None,
                _dumps(resource.supported_frameworks),
                _dumps(resource.tags),
                _dumps(resource.capabilities),
                resource.accessibility_notes,
                resource.performance_notes,
                _dt_to_str(resource.last_indexed_at),
                resource.attribution,
                _dumps(resource.raw_refs),
            ),
        )
        conn.commit()

    def get_resource(self, resource_id: str) -> FrontendResource | None:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT * FROM resources WHERE id = ?", (resource_id,)
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
        conn = self._require_conn()
        clauses: list[str] = []
        params: list[Any] = []
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = conn.execute(
            f"SELECT * FROM resources {where} ORDER BY name LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        resources = [self._row_to_resource(r) for r in rows]
        if tags:
            wanted = {t.lower() for t in tags}
            resources = [
                r for r in resources if wanted.intersection({t.lower() for t in r.tags})
            ]
        return resources

    def upsert_chunk(self, chunk: DocumentationChunk) -> None:
        conn = self._require_conn()
        conn.execute(
            """
            INSERT INTO chunks (
                id, resource_id, title, content, source_url, version,
                license_json, tags, last_indexed_at, content_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                resource_id=excluded.resource_id,
                title=excluded.title,
                content=excluded.content,
                source_url=excluded.source_url,
                version=excluded.version,
                license_json=excluded.license_json,
                tags=excluded.tags,
                last_indexed_at=excluded.last_indexed_at,
                content_sha256=excluded.content_sha256
            """,
            (
                chunk.id,
                chunk.resource_id,
                chunk.title,
                chunk.content,
                chunk.source_url,
                chunk.version,
                chunk.license.model_dump_json() if chunk.license else None,
                _dumps(chunk.tags),
                _dt_to_str(chunk.last_indexed_at),
                chunk.content_sha256,
            ),
        )
        conn.commit()

    def get_chunk(self, chunk_id: str) -> DocumentationChunk | None:
        conn = self._require_conn()
        row = conn.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_chunk(row)

    def list_chunks(
        self,
        *,
        resource_id: str | None = None,
        limit: int = 50_000,
        offset: int = 0,
    ) -> list[DocumentationChunk]:
        conn = self._require_conn()
        if resource_id is not None:
            rows = conn.execute(
                "SELECT * FROM chunks WHERE resource_id = ? ORDER BY title LIMIT ? OFFSET ?",
                (resource_id, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM chunks ORDER BY title LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def count_resources(self, *, source_id: str | None = None) -> int:
        conn = self._require_conn()
        if source_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM resources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS n FROM resources").fetchone()
        return int(row["n"]) if row else 0

    def count_chunks(self) -> int:
        conn = self._require_conn()
        row = conn.execute("SELECT COUNT(*) AS n FROM chunks").fetchone()
        return int(row["n"]) if row else 0

    def upsert_embedding_stub(
        self,
        chunk_id: str,
        provider: str,
        dims: int,
        blob: bytes | None = None,
    ) -> None:
        conn = self._require_conn()
        conn.execute(
            """
            INSERT INTO embeddings (chunk_id, provider, dims, blob, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id, provider) DO UPDATE SET
                dims=excluded.dims,
                blob=excluded.blob,
                created_at=excluded.created_at
            """,
            (chunk_id, provider, dims, blob, datetime.now(UTC).isoformat()),
        )
        conn.commit()

    def get_embedding_stub(self, chunk_id: str, provider: str) -> dict[str, Any] | None:
        conn = self._require_conn()
        row = conn.execute(
            "SELECT chunk_id, provider, dims, blob, created_at FROM embeddings "
            "WHERE chunk_id = ? AND provider = ?",
            (chunk_id, provider),
        ).fetchone()
        if row is None:
            return None
        return {
            "chunk_id": row["chunk_id"],
            "provider": row["provider"],
            "dims": row["dims"],
            "blob": row["blob"],
            "created_at": row["created_at"],
        }

    def _row_to_resource(self, row: sqlite3.Row) -> FrontendResource:
        source = SourceRef.model_validate_json(row["source_json"])
        license_info = (
            LicenseInfo.model_validate_json(row["license_json"])
            if row["license_json"]
            else None
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
            LicenseInfo.model_validate_json(row["license_json"])
            if row["license_json"]
            else None
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
