"""Versioned SQLite schema migrations driven by ``PRAGMA user_version``.

The minimal mode must not pull SQLAlchemy/Alembic into the dependency tree, so
the SQLite backend ships a small forward-only migration runner instead. The
PostgreSQL backend uses real Alembic migrations (see ``migrations/``). ADR 0005
records this trade-off.
"""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2

_V2_TABLES = """
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
    raw_refs_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source_id);
CREATE INDEX IF NOT EXISTS idx_resources_kind ON resources(kind);

CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT,
    version TEXT,
    license_json TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    last_indexed_at TEXT,
    content_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_resource ON chunks(resource_id);
CREATE INDEX IF NOT EXISTS idx_chunks_sha ON chunks(content_sha256);

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    pipeline_version INTEGER NOT NULL DEFAULT 1,
    content_sha256 TEXT NOT NULL,
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_embeddings_model
    ON embeddings(provider, model, dim, pipeline_version);

CREATE TABLE IF NOT EXISTS store_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_LEGACY_EMBEDDING_COLUMNS = {"chunk_id", "provider", "dims", "blob", "created_at"}


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _columns(conn, table)
    for column, ddl in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _upgrade_legacy_to_v2(conn: sqlite3.Connection) -> None:
    """Bring a pre-versioning database (v0.1 schema) up to v2.

    The legacy ``embeddings`` table only ever held stub rows that nothing read,
    so it is dropped and recreated rather than migrated.
    """
    # SQLite cannot add a column with a non-constant default, so timestamps are
    # backfilled instead of defaulted for existing rows.
    _add_missing_columns(conn, "resources", {"created_at": "TEXT", "updated_at": "TEXT"})
    _add_missing_columns(conn, "chunks", {"created_at": "TEXT", "updated_at": "TEXT"})
    conn.execute(
        "UPDATE resources SET created_at = COALESCE(created_at, datetime('now')), "
        "updated_at = COALESCE(updated_at, datetime('now'))"
    )
    conn.execute(
        "UPDATE chunks SET created_at = COALESCE(created_at, datetime('now')), "
        "updated_at = COALESCE(updated_at, datetime('now'))"
    )

    if _table_exists(conn, "embeddings") and _columns(conn, "embeddings") != {
        "chunk_id",
        "provider",
        "model",
        "dim",
        "pipeline_version",
        "content_sha256",
        "vector",
        "created_at",
    }:
        conn.execute("DROP TABLE embeddings")

    conn.executescript(_V2_TABLES)


def migrate(conn: sqlite3.Connection) -> int:
    """Bring ``conn`` to :data:`SCHEMA_VERSION`. Returns the version applied."""
    row = conn.execute("PRAGMA user_version").fetchone()
    current = int(row[0]) if row else 0

    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"SQLite database schema version {current} is newer than this build "
            f"supports ({SCHEMA_VERSION}). Upgrade front-design-mcp."
        )

    if current == SCHEMA_VERSION:
        return current

    if current == 0 and _table_exists(conn, "resources"):
        _upgrade_legacy_to_v2(conn)
    else:
        conn.executescript(_V2_TABLES)

    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    return SCHEMA_VERSION


__all__ = ["SCHEMA_VERSION", "migrate"]
