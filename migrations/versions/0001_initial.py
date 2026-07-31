"""Initial PostgreSQL schema: resources, chunks, embeddings, store_metadata.

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-31

The ``embeddings.embedding`` column dimension is taken from
``FRONT_DESIGN_EMBEDDING_DIMENSIONS`` (documented default: 1536 when unset).
The chosen value is also written to ``store_metadata`` so ``PostgresStore``
can detect dimension mismatches without parsing DDL.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.migration")

# Documented default when FRONT_DESIGN_EMBEDDING_DIMENSIONS is unset.
_DEFAULT_EMBEDDING_DIM = 1536


def _embedding_dim() -> int:
    raw = os.environ.get("FRONT_DESIGN_EMBEDDING_DIMENSIONS")
    if raw is None or not raw.strip():
        dim = _DEFAULT_EMBEDDING_DIM
        logger.info(
            "FRONT_DESIGN_EMBEDDING_DIMENSIONS unset; using documented default %s",
            dim,
        )
        return dim
    dim = int(raw.strip())
    if dim < 1:
        raise ValueError(
            f"FRONT_DESIGN_EMBEDDING_DIMENSIONS must be >= 1, got {dim}"
        )
    logger.info(
        "Creating embeddings.embedding as vector(%s) from FRONT_DESIGN_EMBEDDING_DIMENSIONS",
        dim,
    )
    return dim


def upgrade() -> None:
    dim = _embedding_dim()

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.execute(
        """
        CREATE TABLE resources (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            source_id TEXT NOT NULL,
            source_json JSONB NOT NULL,
            homepage_url TEXT,
            docs_url TEXT,
            install_command TEXT,
            license_json JSONB,
            supported_frameworks TEXT[] NOT NULL DEFAULT '{}',
            tags TEXT[] NOT NULL DEFAULT '{}',
            capabilities TEXT[] NOT NULL DEFAULT '{}',
            accessibility_notes TEXT,
            performance_notes TEXT,
            last_indexed_at TIMESTAMPTZ,
            attribution TEXT,
            raw_refs_json JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_resources_source_id ON resources (source_id)")
    op.execute("CREATE INDEX ix_resources_kind ON resources (kind)")
    op.execute("CREATE INDEX ix_resources_tags ON resources USING gin (tags)")

    # array_to_string(anyarray, text) is STABLE in PostgreSQL, which cannot appear
    # in a GENERATED column. This thin IMMUTABLE wrapper is the standard workaround
    # so tags can participate in the stored tsvector.
    op.execute(
        """
        CREATE FUNCTION front_design_array_to_text(arr text[])
        RETURNS text
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$ SELECT coalesce(array_to_string(arr, ' '), '') $$
        """
    )

    op.execute(
        """
        CREATE TABLE chunks (
            id TEXT PRIMARY KEY,
            resource_id TEXT NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            source_url TEXT,
            version TEXT,
            license_json JSONB,
            tags TEXT[] NOT NULL DEFAULT '{}',
            content_sha256 TEXT NOT NULL,
            last_indexed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            search_vector tsvector GENERATED ALWAYS AS (
                to_tsvector(
                    'english'::regconfig,
                    coalesce(title, '') || ' ' || coalesce(content, '')
                    || ' ' || front_design_array_to_text(tags)
                )
            ) STORED
        )
        """
    )
    op.execute("CREATE INDEX ix_chunks_resource_id ON chunks (resource_id)")
    op.execute("CREATE INDEX ix_chunks_content_sha256 ON chunks (content_sha256)")
    op.execute("CREATE INDEX ix_chunks_search_vector ON chunks USING gin (search_vector)")

    # Cosine distance + HNSW: chosen for semantic similarity retrieval.
    # No benchmark has justified switching to IVFFlat for this workload.
    op.execute(
        f"""
        CREATE TABLE embeddings (
            chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            pipeline_version INTEGER NOT NULL DEFAULT 1,
            content_sha256 TEXT NOT NULL,
            embedding vector({dim}) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX ix_embeddings_hnsw
            ON embeddings USING hnsw (embedding vector_cosine_ops)
        """
    )
    op.execute(
        """
        CREATE INDEX ix_embeddings_model
            ON embeddings (provider, model, dim, pipeline_version)
        """
    )

    op.execute(
        """
        CREATE TABLE store_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    op.execute(
        f"""
        INSERT INTO store_metadata (key, value)
        VALUES ('embedding_dim', '{dim}')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embeddings")
    op.execute("DROP TABLE IF EXISTS chunks")
    op.execute("DROP TABLE IF EXISTS resources")
    op.execute("DROP TABLE IF EXISTS store_metadata")
    op.execute("DROP FUNCTION IF EXISTS front_design_array_to_text(text[])")
    # Leave the vector extension installed — other DBs/roles may depend on it.
