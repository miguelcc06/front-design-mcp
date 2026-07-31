"""SQLite schema migration tests — forward-only via PRAGMA user_version."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from front_design_mcp.store.sqlite_schema import SCHEMA_VERSION, migrate
from front_design_mcp.store.sqlite_store import SqliteStore

# v0.1 DDL (pre-versioning): no created_at/updated_at on resources/chunks,
# and the stub embeddings table with dims/blob columns.
_LEGACY_DDL = """
CREATE TABLE resources (
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

CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_url TEXT,
    version TEXT,
    license_json TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    last_indexed_at TEXT,
    content_sha256 TEXT NOT NULL
);

CREATE TABLE embeddings (
    chunk_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    dims INTEGER NOT NULL,
    blob BLOB NOT NULL,
    created_at TEXT
);
"""

_EXPECTED_RESOURCE_COLS = {
    "id",
    "kind",
    "name",
    "description",
    "source_id",
    "source_json",
    "homepage_url",
    "docs_url",
    "install_command",
    "license_json",
    "supported_frameworks",
    "tags",
    "capabilities",
    "accessibility_notes",
    "performance_notes",
    "last_indexed_at",
    "attribution",
    "raw_refs_json",
    "created_at",
    "updated_at",
}

_EXPECTED_CHUNK_COLS = {
    "id",
    "resource_id",
    "title",
    "content",
    "source_url",
    "version",
    "license_json",
    "tags",
    "last_indexed_at",
    "content_sha256",
    "created_at",
    "updated_at",
}

_EXPECTED_EMBEDDING_COLS = {
    "chunk_id",
    "provider",
    "model",
    "dim",
    "pipeline_version",
    "content_sha256",
    "vector",
    "created_at",
}


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def test_brand_new_database_has_schema_version_and_tables(tmp_path: Path) -> None:
    path = tmp_path / "new.db"
    store = SqliteStore(path)
    try:
        conn = sqlite3.connect(str(path))
        try:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            assert version == SCHEMA_VERSION
            tables = {
                str(r[0])
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            assert {"resources", "chunks", "embeddings", "store_metadata"} <= tables
            assert _columns(conn, "resources") == _EXPECTED_RESOURCE_COLS
            assert _columns(conn, "chunks") == _EXPECTED_CHUNK_COLS
            assert _columns(conn, "embeddings") == _EXPECTED_EMBEDDING_COLS
            assert "key" in _columns(conn, "store_metadata")
            assert "value" in _columns(conn, "store_metadata")
        finally:
            conn.close()
    finally:
        store.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "idem.db"
    conn = sqlite3.connect(str(path))
    try:
        v1 = migrate(conn)
        assert v1 == SCHEMA_VERSION
        cols_before = {
            t: _columns(conn, t) for t in ("resources", "chunks", "embeddings")
        }
        v2 = migrate(conn)
        assert v2 == SCHEMA_VERSION
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
        for table, cols in cols_before.items():
            assert _columns(conn, table) == cols
    finally:
        conn.close()


def test_legacy_v0_1_upgrade_preserves_data(tmp_path: Path) -> None:
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(_LEGACY_DDL)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO resources (id, kind, name, description, source_id, source_json, "
            "tags, supported_frameworks, capabilities, raw_refs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy:one",
                "library",
                "Legacy One",
                "old resource",
                "legacy-src",
                '{"source_id":"legacy-src","source_name":"Legacy"}',
                '["old"]',
                '["react"]',
                '["docs"]',
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO resources (id, kind, name, description, source_id, source_json, "
            "tags, supported_frameworks, capabilities, raw_refs_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy:two",
                "component",
                "Legacy Two",
                "second",
                "legacy-src",
                '{"source_id":"legacy-src","source_name":"Legacy"}',
                "[]",
                "[]",
                "[]",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO chunks (id, resource_id, title, content, tags, content_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy:one#1", "legacy:one", "Intro", "legacy chunk body", "[]", "sha-a"),
        )
        conn.execute(
            "INSERT INTO chunks (id, resource_id, title, content, tags, content_sha256) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("legacy:two#1", "legacy:two", "Usage", "second body", '["x"]', "sha-b"),
        )
        conn.execute(
            "INSERT INTO embeddings (chunk_id, provider, dims, blob, created_at) "
            "VALUES (?, ?, ?, ?, datetime('now'))",
            ("legacy:one#1", "stub", 3, b"\x00\x00\x00"),
        )
        # user_version left at 0 intentionally
        assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == 0
        conn.commit()
    finally:
        conn.close()

    store = SqliteStore(path)
    try:
        r1 = store.get_resource("legacy:one")
        r2 = store.get_resource("legacy:two")
        assert r1 is not None
        assert r1.name == "Legacy One"
        assert r1.description == "old resource"
        assert r1.tags == ["old"]
        assert r1.supported_frameworks == ["react"]
        assert r2 is not None
        assert r2.name == "Legacy Two"

        c1 = store.get_chunk("legacy:one#1")
        c2 = store.get_chunk("legacy:two#1")
        assert c1 is not None
        assert c1.title == "Intro"
        assert c1.content == "legacy chunk body"
        assert c1.content_sha256 == "sha-a"
        assert c2 is not None
        assert c2.content == "second body"

        conn = sqlite3.connect(str(path))
        try:
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == SCHEMA_VERSION
            assert _columns(conn, "embeddings") == _EXPECTED_EMBEDDING_COLS
            for table in ("resources", "chunks"):
                row = conn.execute(
                    f"SELECT created_at, updated_at FROM {table} WHERE id = ?",
                    ("legacy:one" if table == "resources" else "legacy:one#1",),
                ).fetchone()
                assert row is not None
                assert row[0]  # created_at populated
                assert row[1]  # updated_at populated
            # Stub embedding rows were dropped during upgrade
            assert (
                conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 0
            )
        finally:
            conn.close()
    finally:
        store.close()


def test_newer_user_version_raises(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 5}")
        conn.commit()
        with pytest.raises(RuntimeError, match="newer than this build"):
            migrate(conn)
    finally:
        conn.close()
