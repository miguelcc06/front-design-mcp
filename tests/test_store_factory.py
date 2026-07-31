"""Tests for store factory and Settings database URL helpers."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from pydantic import ValidationError

from front_design_mcp.config import Settings
from front_design_mcp.store.factory import _expected_embedding_dim, create_store
from front_design_mcp.store.sqlite_store import SqliteStore

_TEST_DSN = os.environ.get("FRONT_DESIGN_TEST_DATABASE_URL", "").strip()


def _postgres_reachable(dsn: str) -> bool:
    if not dsn:
        return False
    try:
        import psycopg

        with psycopg.connect(dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:
        return False


def test_create_store_default_sqlite(tmp_path: Path) -> None:
    db_path = tmp_path / "data" / "store.db"
    cfg = Settings(
        data_dir=tmp_path,
        db_path=db_path,
        store_backend="sqlite",
        embedding_provider="none",
    )
    store = create_store(cfg)
    try:
        assert isinstance(store, SqliteStore)
        assert store.db_path == db_path.expanduser().resolve()
        store.open()
        assert store.capabilities().backend == "sqlite"
    finally:
        store.close()


def test_postgres_without_database_url_raises() -> None:
    cfg = Settings(store_backend="postgres", database_url=None, embedding_provider="none")
    with pytest.raises(ValueError, match="FRONT_DESIGN_DATABASE_URL"):
        create_store(cfg)


def test_invalid_database_url_scheme_rejected() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(database_url="mysql://user:pass@localhost/db")


def test_redacted_database_url_strips_password() -> None:
    cfg = Settings(
        database_url="postgresql://front_design:secretpass@127.0.0.1:5432/app"
    )
    redacted = cfg.redacted_database_url()
    assert redacted is not None
    assert "secretpass" not in redacted
    assert "front_design" in redacted
    assert "127.0.0.1" in redacted
    assert "5432" in redacted
    assert "/app" in redacted
    assert "***" in redacted

    no_pass = Settings(database_url="postgresql://127.0.0.1:5432/app")
    assert no_pass.redacted_database_url() == "postgresql://127.0.0.1:5432/app"


def test_require_and_sqlalchemy_database_url_dialect() -> None:
    cfg = Settings(
        database_url="postgresql+psycopg://u:p@localhost:5432/db",
        store_backend="postgres",
    )
    libpq = cfg.require_database_url()
    assert libpq.startswith("postgresql://")
    assert "+psycopg" not in libpq
    sa = cfg.sqlalchemy_database_url()
    assert sa.startswith("postgresql+psycopg://")


def test_expected_embedding_dim_none_and_known_providers() -> None:
    none_cfg = Settings(embedding_provider="none", embedding_dimensions=None)
    assert _expected_embedding_dim(none_cfg) is None

    none_override = Settings(embedding_provider="none", embedding_dimensions=768)
    assert _expected_embedding_dim(none_override) == 768

    openai_cfg = Settings(embedding_provider="openai", embedding_model=None)
    assert _expected_embedding_dim(openai_cfg) == 1536

    fastembed_cfg = Settings(embedding_provider="fastembed", embedding_model=None)
    assert _expected_embedding_dim(fastembed_cfg) == 384


# ---------------------------------------------------------------------------
# Live PostgreSQL (skipped when FRONT_DESIGN_TEST_DATABASE_URL unset)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EMBED_DIM = 8


def _admin_dsn(dsn: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path="/postgres"))


def _scratch_dsn(dsn: str, db_name: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{db_name}"))


@pytest.fixture
def factory_scratch_url() -> Iterator[str]:
    if not _postgres_reachable(_TEST_DSN):
        pytest.skip("FRONT_DESIGN_TEST_DATABASE_URL unset or PostgreSQL unreachable")

    import psycopg
    from alembic import command
    from alembic.config import Config

    assert _TEST_DSN
    db_name = f"front_design_factory_{os.getpid()}"
    admin = _admin_dsn(_TEST_DSN)
    scratch = _scratch_dsn(_TEST_DSN, db_name)

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')

    # Alembic reads FRONT_DESIGN_DATABASE_URL; set only for the upgrade call.
    prev_url = os.environ.get("FRONT_DESIGN_DATABASE_URL")
    prev_dim = os.environ.get("FRONT_DESIGN_EMBEDDING_DIMENSIONS")
    os.environ["FRONT_DESIGN_DATABASE_URL"] = scratch
    os.environ["FRONT_DESIGN_EMBEDDING_DIMENSIONS"] = str(_EMBED_DIM)
    try:
        cfg = Config(str(_REPO_ROOT / "alembic.ini"))
        command.upgrade(cfg, "head")
        yield scratch
    finally:
        if prev_url is None:
            os.environ.pop("FRONT_DESIGN_DATABASE_URL", None)
        else:
            os.environ["FRONT_DESIGN_DATABASE_URL"] = prev_url
        if prev_dim is None:
            os.environ.pop("FRONT_DESIGN_EMBEDDING_DIMENSIONS", None)
        else:
            os.environ["FRONT_DESIGN_EMBEDDING_DIMENSIONS"] = prev_dim
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


@pytest.mark.postgres
def test_create_store_postgres_against_migrated_scratch(
    factory_scratch_url: str,
) -> None:
    from front_design_mcp.store.postgres_store import PostgresStore

    cfg = Settings(
        store_backend="postgres",
        database_url=factory_scratch_url,
        embedding_provider="none",
        embedding_dimensions=_EMBED_DIM,
    )
    store = create_store(cfg)
    try:
        assert isinstance(store, PostgresStore)
        store.open()
        caps = store.capabilities()
        assert caps.backend == "postgres"
        assert store.count_resources() == 0
        stats = store.stats()
        assert stats["backend"] == "postgres"
    finally:
        store.close()
