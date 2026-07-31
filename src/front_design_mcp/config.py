"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

StoreBackend = Literal["sqlite", "postgres"]
EmbeddingProviderName = Literal["none", "openai", "fastembed"]
SearchMode = Literal["auto", "lexical", "vector", "hybrid"]


def _default_data_dir() -> Path:
    """Prefer repo/cwd ``./data`` (fixtures + store); fall back stays local-first."""
    cwd_data = Path.cwd() / "data"
    return cwd_data


def _strip_sqlalchemy_driver(url: str) -> str:
    """Turn ``postgresql+psycopg://…`` into a libpq-compatible ``postgresql://…``."""
    scheme, _, rest = url.partition("://")
    base = scheme.split("+", 1)[0]
    if base in {"postgres", "postgresql"}:
        base = "postgresql"
    return f"{base}://{rest}" if rest else url


class Settings(BaseSettings):
    """Runtime settings for front-design-mcp (local-first defaults)."""

    model_config = SettingsConfigDict(
        env_prefix="FRONT_DESIGN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path | None = Field(
        default=None,
        description="Root data directory for fixtures, cache, and store artifacts.",
    )
    db_path: Path | None = Field(
        default=None,
        description="SQLite database path. Defaults under data_dir/store.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    http_timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    enable_network_ingest: bool = False

    # --- Storage backend -------------------------------------------------
    store_backend: StoreBackend = Field(
        default="sqlite",
        description="Storage/search backend. 'sqlite' is the offline default.",
    )
    database_url: str | None = Field(
        default=None,
        description=(
            "PostgreSQL URL, e.g. postgresql+psycopg://user:pass@host:5432/db. "
            "Required when store_backend=postgres."
        ),
    )
    postgres_statement_timeout_ms: int = Field(default=15_000, ge=0, le=600_000)

    # --- Embeddings ------------------------------------------------------
    embedding_provider: EmbeddingProviderName = Field(
        default="none",
        description="Embedding provider. 'none' disables vector search entirely.",
    )
    embedding_model: str | None = Field(
        default=None,
        description="Model id for the selected provider (provider default when unset).",
    )
    embedding_dimensions: int | None = Field(
        default=None,
        ge=1,
        le=4096,
        description=(
            "Optional dimension override. Must be supported by the model; the "
            "provider is the source of truth and mismatches fail fast."
        ),
    )
    embedding_api_key: SecretStr | None = Field(
        default=None, description="API key for remote embedding providers."
    )
    embedding_base_url: str | None = Field(
        default=None, description="Override base URL for OpenAI-compatible endpoints."
    )
    embedding_batch_size: int = Field(default=32, ge=1, le=512)
    embedding_timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    embedding_max_retries: int = Field(default=3, ge=0, le=10)
    embedding_pipeline_version: int = Field(
        default=1,
        ge=1,
        description="Bump to force re-embedding when chunking/normalization changes.",
    )

    # --- Search ----------------------------------------------------------
    search_mode: SearchMode = Field(
        default="auto",
        description=(
            "auto = hybrid when backend and embeddings allow it, else lexical. "
            "lexical/vector/hybrid force a specific strategy."
        ),
    )
    rrf_k: int = Field(
        default=60,
        ge=1,
        le=1000,
        description="Reciprocal Rank Fusion smoothing constant.",
    )
    rrf_lexical_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    rrf_vector_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    search_candidates: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Per-branch candidate pool size before fusion.",
    )

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        url = value.strip()
        scheme = url.partition("://")[0].split("+", 1)[0]
        if scheme not in {"postgres", "postgresql"}:
            raise ValueError(
                "database_url must be a PostgreSQL URL "
                "(postgresql:// or postgresql+psycopg://)"
            )
        return url

    def resolved_data_dir(self) -> Path:
        if self.data_dir is not None:
            return self.data_dir.expanduser().resolve()
        return _default_data_dir().expanduser().resolve()

    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path.expanduser().resolve()
        return self.resolved_data_dir() / "store" / "front_design.db"

    def resolve_db_path(self) -> Path:
        """Alias used by CLI / validation scripts."""
        return self.resolved_db_path()

    def resolve_fixtures_dir(self) -> Path:
        return self.resolved_data_dir() / "fixtures"

    def require_database_url(self) -> str:
        """libpq-style DSN for psycopg. Raises when postgres is not configured."""
        if not self.database_url:
            raise ValueError(
                "FRONT_DESIGN_DATABASE_URL is required when "
                "FRONT_DESIGN_STORE_BACKEND=postgres"
            )
        return _strip_sqlalchemy_driver(self.database_url)

    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy/Alembic URL pinned to the psycopg (v3) driver."""
        dsn = self.require_database_url()
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)

    def redacted_database_url(self) -> str | None:
        """Database URL safe for logs and error messages (password removed)."""
        if not self.database_url:
            return None
        parts = urlsplit(self.database_url)
        if parts.password is None:
            return self.database_url
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        user = f"{parts.username}:***@" if parts.username else ""
        return urlunsplit((parts.scheme, f"{user}{host}", parts.path, "", ""))


def get_settings() -> Settings:
    """Load settings from environment / .env."""
    return Settings()
