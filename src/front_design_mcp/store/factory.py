"""Backend selection: build a :class:`Store` from configuration alone.

Nothing outside this module imports a concrete store class, so ``sqlite`` stays
the default and the PostgreSQL dependencies remain optional.
"""

from __future__ import annotations

from front_design_mcp.config import Settings, get_settings
from front_design_mcp.store.base import Store
from front_design_mcp.store.sqlite_store import SqliteStore


class StoreBackendError(RuntimeError):
    """The requested backend cannot be constructed."""


def create_store(settings: Settings | None = None) -> Store:
    """Instantiate the configured backend.

    ``FRONT_DESIGN_STORE_BACKEND=sqlite`` (default) needs no extra packages.
    ``postgres`` requires the ``postgres`` extra and ``FRONT_DESIGN_DATABASE_URL``.
    """
    cfg = settings or get_settings()

    if cfg.store_backend == "sqlite":
        return SqliteStore(cfg.resolve_db_path())

    if cfg.store_backend == "postgres":
        dsn = cfg.require_database_url()
        try:
            from front_design_mcp.store.postgres_store import PostgresStore
        except ImportError as exc:  # pragma: no cover - depends on install extras
            raise StoreBackendError(
                "FRONT_DESIGN_STORE_BACKEND=postgres requires the 'postgres' extra. "
                "Install it with: uv sync --extra postgres"
            ) from exc
        return PostgresStore(
            dsn,
            embedding_dim=cfg.embedding_dimensions,
            statement_timeout_ms=cfg.postgres_statement_timeout_ms,
        )

    raise StoreBackendError(f"Unknown store backend: {cfg.store_backend!r}")


__all__ = ["StoreBackendError", "create_store"]
