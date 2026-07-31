"""Store package exports.

``PostgresStore`` is deliberately not re-exported here: importing it requires the
optional ``postgres`` extra. Use :func:`create_store` instead.
"""

from front_design_mcp.store.base import (
    EmbeddingMeta,
    EmbeddingModelRef,
    EmbeddingRecord,
    Store,
    StoreCapabilities,
    SyncOutcome,
)
from front_design_mcp.store.factory import StoreBackendError, create_store
from front_design_mcp.store.sqlite_store import SqliteStore

__all__ = [
    "EmbeddingMeta",
    "EmbeddingModelRef",
    "EmbeddingRecord",
    "SqliteStore",
    "Store",
    "StoreBackendError",
    "StoreCapabilities",
    "SyncOutcome",
    "create_store",
]
