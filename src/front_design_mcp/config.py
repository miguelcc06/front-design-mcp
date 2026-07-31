"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from platformdirs import user_data_dir
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        description="SQLite database path. Defaults under data_dir.",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    http_timeout: float = Field(default=30.0, ge=1.0, le=300.0)
    enable_network_ingest: bool = False
    embedding_provider: Literal["none", "hashing"] = "none"

    def resolved_data_dir(self) -> Path:
        if self.data_dir is not None:
            return self.data_dir.expanduser().resolve()
        return Path(user_data_dir("front-design-mcp", "front-design-mcp"))

    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path.expanduser().resolve()
        return self.resolved_data_dir() / "store" / "front_design.db"


def get_settings() -> Settings:
    """Load settings from environment / .env."""
    return Settings()
