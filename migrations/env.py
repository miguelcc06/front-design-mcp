"""Alembic environment — URL from FRONT_DESIGN_DATABASE_URL via Settings."""

from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

# No ORM metadata — schema is created via raw SQL in migrations.
target_metadata = None


def _resolve_database_url() -> str:
    """Prefer FRONT_DESIGN_DATABASE_URL; fall back to alembic.ini sqlalchemy.url."""
    import os

    if os.environ.get("FRONT_DESIGN_DATABASE_URL"):
        from front_design_mcp.config import get_settings

        settings = get_settings()
        # Never log the URL — it may contain a password.
        return settings.sqlalchemy_database_url()

    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError(
            "No database URL configured. Set FRONT_DESIGN_DATABASE_URL or "
            "sqlalchemy.url in alembic.ini."
        )
    return url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live database."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
