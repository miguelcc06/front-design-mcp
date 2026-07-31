"""Integration tests for :class:`PostgresStore` against a live PostgreSQL.

Skipped entirely when ``FRONT_DESIGN_TEST_DATABASE_URL`` is unset or the
server is unreachable so ``uv run pytest -q`` stays green offline.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest

from front_design_mcp.models import (
    DocumentationChunk,
    FrontendResource,
    LicenseInfo,
    ResourceKind,
    SourceRef,
)
from front_design_mcp.search.base import SearchFilters
from front_design_mcp.store.base import EmbeddingModelRef, EmbeddingRecord
from front_design_mcp.store.postgres_store import PostgresStore

# ---------------------------------------------------------------------------
# Module-level skip — must not fail machines without PostgreSQL.
# ---------------------------------------------------------------------------

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


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _postgres_reachable(_TEST_DSN),
        reason=(
            "FRONT_DESIGN_TEST_DATABASE_URL unset or PostgreSQL unreachable"
        ),
    ),
]

_EMBED_DIM = 8
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _admin_dsn(dsn: str) -> str:
    """Point the DSN at the maintenance DB so we can CREATE/DROP databases."""
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path="/postgres"))


def _scratch_dsn(dsn: str, db_name: str) -> str:
    parts = urlparse(dsn)
    return urlunparse(parts._replace(path=f"/{db_name}"))


@pytest.fixture(scope="session")
def scratch_database_url() -> Iterator[str]:
    """Create a dedicated DB, migrate with dim=8, drop on teardown."""
    import psycopg
    from alembic import command
    from alembic.config import Config

    assert _TEST_DSN
    db_name = f"front_design_pgstore_{os.getpid()}"
    admin = _admin_dsn(_TEST_DSN)
    scratch = _scratch_dsn(_TEST_DSN, db_name)

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')

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


@pytest.fixture
def store(scratch_database_url: str) -> Iterator[PostgresStore]:
    """Fresh :class:`PostgresStore` with truncated tables between tests."""
    import psycopg

    with psycopg.connect(scratch_database_url, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE embeddings, chunks, resources RESTART IDENTITY CASCADE"
        )

    s = PostgresStore(
        scratch_database_url,
        embedding_dim=_EMBED_DIM,
        statement_timeout_ms=15_000,
        auto_open=True,
    )
    try:
        yield s
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resource(
    rid: str,
    *,
    name: str | None = None,
    source_id: str = "src-a",
    kind: str = "library",
    tags: list[str] | None = None,
    license: LicenseInfo | None = None,
) -> FrontendResource:
    return FrontendResource(
        id=rid,
        kind=ResourceKind(kind),
        name=name or rid,
        description=f"Description for {rid}",
        source=SourceRef(
            source_id=source_id,
            source_name="Test Source",
            homepage_url="https://example.com",
            registry_url="https://example.com/registry",
            attribution="Test",
        ),
        homepage_url="https://example.com/home",
        docs_url="https://example.com/docs",
        install_command="npm i example",
        license=license,
        supported_frameworks=["react"],
        tags=tags or [],
        capabilities=["a11y"],
        accessibility_notes="wcag",
        performance_notes="fast",
        last_indexed_at=datetime(2026, 1, 15, tzinfo=UTC),
        attribution="attrib",
        raw_refs={"k": "v"},
    )


def _chunk(
    cid: str,
    resource_id: str,
    *,
    title: str = "Title",
    content: str = "Content about buttons and forms",
    tags: list[str] | None = None,
) -> DocumentationChunk:
    return DocumentationChunk(
        id=cid,
        resource_id=resource_id,
        title=title,
        content=content,
        source_url="https://example.com/chunk",
        version="1.0.0",
        license=None,
        tags=tags or ["docs"],
        last_indexed_at=datetime(2026, 1, 15, tzinfo=UTC),
        content_sha256=f"sha-{cid}",
    )


def _unit(i: int, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic unit-ish vector with a spike at index ``i % dim``."""
    v = [0.0] * dim
    v[i % dim] = 1.0
    return v


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_schema_created_from_empty(scratch_database_url: str) -> None:
    import psycopg

    with psycopg.connect(scratch_database_url) as conn:
        tables = {
            str(r[0])
            for r in conn.execute(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                """
            ).fetchall()
        }
        assert {"resources", "chunks", "embeddings", "store_metadata"} <= tables
        dim = conn.execute(
            "SELECT value FROM store_metadata WHERE key = 'embedding_dim'"
        ).fetchone()
        assert dim is not None
        assert int(dim[0]) == _EMBED_DIM


def test_resource_chunk_round_trip(store: PostgresStore) -> None:
    res = _resource(
        "r1",
        tags=["React", "ui"],
        license=LicenseInfo(
            spdx_id="MIT",
            name="MIT License",
            url="https://opensource.org/licenses/MIT",
            redistributable=True,
            notes="permissive",
        ),
    )
    chunk = _chunk("c1", "r1", title="Button API", content="How to use buttons")
    store.upsert_resources([res])
    store.upsert_chunks([chunk])

    got_r = store.get_resource("r1")
    assert got_r is not None
    assert got_r.id == "r1"
    assert got_r.kind.value == "library"
    assert got_r.name == "r1"
    assert got_r.description.startswith("Description")
    assert got_r.source.source_id == "src-a"
    assert got_r.homepage_url == "https://example.com/home"
    assert got_r.docs_url == "https://example.com/docs"
    assert got_r.install_command == "npm i example"
    assert got_r.license is not None
    assert got_r.license.spdx_id == "MIT"
    assert got_r.supported_frameworks == ["react"]
    assert got_r.tags == ["React", "ui"]
    assert got_r.capabilities == ["a11y"]
    assert got_r.accessibility_notes == "wcag"
    assert got_r.performance_notes == "fast"
    assert got_r.attribution == "attrib"
    assert got_r.raw_refs == {"k": "v"}
    assert got_r.last_indexed_at is not None

    got_c = store.get_chunk("c1")
    assert got_c is not None
    assert got_c.resource_id == "r1"
    assert got_c.title == "Button API"
    assert got_c.content == "How to use buttons"
    assert got_c.source_url == "https://example.com/chunk"
    assert got_c.version == "1.0.0"
    assert got_c.tags == ["docs"]
    assert got_c.content_sha256 == "sha-c1"


def test_transaction_batch_rollback(store: PostgresStore) -> None:
    store.upsert_resources([_resource("r-ok")])
    assert store.get_resource("r-ok") is not None

    with pytest.raises(RuntimeError, match="boom"), store.transaction():
        store.upsert_resources([_resource("r-tx")])
        store.upsert_chunks([_chunk("c-tx", "r-tx")])
        raise RuntimeError("boom")

    assert store.get_resource("r-tx") is None
    assert store.get_chunk("c-tx") is None
    assert store.get_resource("r-ok") is not None


def test_list_resources_tags_before_limit(store: PostgresStore) -> None:
    # Insert more than `limit` rows; only late rows match the tag filter.
    # Names are sorted alphabetically — non-matching "aaa-*" would win LIMIT
    # if the filter were applied in Python after LIMIT.
    resources = [_resource(f"aaa-{i:02d}", tags=["noise"]) for i in range(5)]
    resources += [_resource(f"zzz-{i:02d}", tags=["target"]) for i in range(3)]
    store.upsert_resources(resources)

    found = store.list_resources(tags=["TARGET"], limit=2, offset=0)
    assert len(found) == 2
    assert all("target" in {t.lower() for t in r.tags} for r in found)
    assert all(r.id.startswith("zzz-") for r in found)


def test_list_chunk_fingerprints(store: PostgresStore) -> None:
    store.upsert_resources(
        [_resource("r1", source_id="s1"), _resource("r2", source_id="s2")]
    )
    store.upsert_chunks([_chunk("c1", "r1"), _chunk("c2", "r2")])
    all_fp = store.list_chunk_fingerprints()
    assert all_fp == {"c1": "sha-c1", "c2": "sha-c2"}
    s1 = store.list_chunk_fingerprints(source_id="s1")
    assert s1 == {"c1": "sha-c1"}


def test_cascade_delete_resource(store: PostgresStore) -> None:
    store.upsert_resources([_resource("r1")])
    store.upsert_chunks([_chunk("c1", "r1")])
    model = EmbeddingModelRef(provider="test", model="tiny", dim=_EMBED_DIM)
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=_unit(0),
                content_sha256="sha-c1",
                model=model,
            )
        ]
    )
    assert store.count_embeddings() == 1
    deleted = store.delete_resources(["r1"])
    assert deleted == 1
    assert store.get_resource("r1") is None
    assert store.get_chunk("c1") is None
    assert store.count_embeddings() == 0


def test_embeddings_metadata_round_trip(store: PostgresStore) -> None:
    store.upsert_resources([_resource("r1")])
    store.upsert_chunks([_chunk("c1", "r1"), _chunk("c2", "r1")])
    model = EmbeddingModelRef(
        provider="test", model="tiny", dim=_EMBED_DIM, pipeline_version=2
    )
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=_unit(1),
                content_sha256="sha-c1",
                model=model,
            ),
            EmbeddingRecord(
                chunk_id="c2",
                vector=_unit(2),
                content_sha256="sha-c2",
                model=model,
            ),
        ]
    )
    meta = store.get_embedding_metadata()
    assert set(meta) == {"c1", "c2"}
    assert meta["c1"].provider == "test"
    assert meta["c1"].model == "tiny"
    assert meta["c1"].dim == _EMBED_DIM
    assert meta["c1"].pipeline_version == 2
    assert meta["c1"].content_sha256 == "sha-c1"
    assert meta["c1"].matches(model, "sha-c1")

    only = store.get_embedding_metadata(["c2"])
    assert set(only) == {"c2"}


def test_upsert_embeddings_wrong_dim_raises(store: PostgresStore) -> None:
    store.upsert_resources([_resource("r1")])
    store.upsert_chunks([_chunk("c1", "r1")])

    bad_model = EmbeddingModelRef(provider="t", model="m", dim=3)
    with pytest.raises(ValueError, match="dimension mismatch"):
        store.upsert_embeddings(
            [
                EmbeddingRecord(
                    chunk_id="c1",
                    vector=[0.1, 0.2, 0.3],
                    content_sha256="sha-c1",
                    model=bad_model,
                )
            ]
        )

    ok_model = EmbeddingModelRef(provider="t", model="m", dim=_EMBED_DIM)
    with pytest.raises(ValueError, match="dimension mismatch"):
        store.upsert_embeddings(
            [
                EmbeddingRecord(
                    chunk_id="c1",
                    vector=[0.1, 0.2, 0.3],
                    content_sha256="sha-c1",
                    model=ok_model,
                )
            ]
        )


def test_search_lexical_ranked_and_filters(store: PostgresStore) -> None:
    store.upsert_resources(
        [
            _resource("r1", source_id="s1", kind="library", tags=["react"]),
            _resource("r2", source_id="s2", kind="component", tags=["vue"]),
        ]
    )
    store.upsert_chunks(
        [
            _chunk(
                "c1",
                "r1",
                title="Accessible buttons",
                content="Use semantic button elements for accessibility",
            ),
            _chunk(
                "c2",
                "r2",
                title="Button styles",
                content="CSS for decorative buttons only",
            ),
        ]
    )

    hits = store.search_lexical(
        "accessible button",
        filters=SearchFilters.build(),
        limit=10,
    )
    assert hits
    assert hits[0].rank == 1
    assert all(h.rank == i for i, h in enumerate(hits, start=1))

    filtered = store.search_lexical(
        "button",
        filters=SearchFilters.build(source_id="s1", tags=["react"]),
        limit=10,
    )
    assert filtered
    assert all(h.chunk_id == "c1" for h in filtered)

    empty_ids = store.search_lexical(
        "button",
        filters=SearchFilters.build(resource_ids=[]),
        limit=10,
    )
    assert empty_ids == []


def test_search_lexical_blank_query(store: PostgresStore) -> None:
    assert store.search_lexical("  ", filters=SearchFilters.build(), limit=5) == []


def test_search_lexical_relaxes_conjunction(store: PostgresStore) -> None:
    """A natural-language query must not return nothing just because one term is absent.

    ``websearch_to_tsquery`` ANDs every term, so "accessible button gradient"
    matches no chunk; the OR-relaxed second pass is what keeps recall usable and
    keeps this backend comparable with BM25 on SQLite.
    """
    store.upsert_resources([_resource("r1", source_id="s1", kind="library")])
    store.upsert_chunks(
        [
            _chunk(
                "c1",
                "r1",
                title="Accessible buttons",
                content="Use semantic button elements for accessibility",
            )
        ]
    )

    strict_terms_all_present = store.search_lexical(
        "accessible button", filters=SearchFilters.build(), limit=5
    )
    assert [h.chunk_id for h in strict_terms_all_present] == ["c1"]

    # "gradient" appears nowhere, so the strict pass yields zero rows.
    relaxed = store.search_lexical(
        "accessible button gradient", filters=SearchFilters.build(), limit=5
    )
    assert [h.chunk_id for h in relaxed] == ["c1"]

    # Relaxation must still respect pre-ranking filters.
    assert (
        store.search_lexical(
            "accessible button gradient",
            filters=SearchFilters.build(source_id="other"),
            limit=5,
        )
        == []
    )

    # A query with no indexable lexemes stays empty rather than matching everything.
    assert store.search_lexical("!!! ???", filters=SearchFilters.build(), limit=5) == []


def test_search_vector_ranked_and_filters(store: PostgresStore) -> None:
    store.upsert_resources(
        [
            _resource("r1", source_id="s1", tags=["react"]),
            _resource("r2", source_id="s2", tags=["vue"]),
        ]
    )
    store.upsert_chunks([_chunk("c1", "r1"), _chunk("c2", "r2")])
    model = EmbeddingModelRef(provider="test", model="tiny", dim=_EMBED_DIM)
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=_unit(0),
                content_sha256="sha-c1",
                model=model,
            ),
            EmbeddingRecord(
                chunk_id="c2",
                vector=_unit(3),
                content_sha256="sha-c2",
                model=model,
            ),
        ]
    )

    hits = store.search_vector(
        _unit(0),
        filters=SearchFilters.build(),
        limit=10,
        model=model,
    )
    assert len(hits) == 2
    assert hits[0].chunk_id == "c1"
    assert hits[0].rank == 1
    assert hits[0].score >= hits[1].score

    filtered = store.search_vector(
        _unit(0),
        filters=SearchFilters.build(source_id="s2"),
        limit=10,
        model=model,
    )
    assert len(filtered) == 1
    assert filtered[0].chunk_id == "c2"

    with pytest.raises(ValueError, match="dimension mismatch"):
        store.search_vector(
            [0.0, 1.0], filters=SearchFilters.build(), limit=5, model=model
        )


def test_search_vector_filters_by_model_identity(store: PostgresStore) -> None:
    """Mixed identities must never share one cosine ranking."""
    store.upsert_resources(
        [
            _resource("r1", source_id="s1"),
            _resource("r2", source_id="s1"),
        ]
    )
    store.upsert_chunks([_chunk("c1", "r1"), _chunk("c2", "r2")])
    matching = EmbeddingModelRef(provider="test", model="tiny", dim=_EMBED_DIM)
    foreign = EmbeddingModelRef(provider="test", model="other", dim=_EMBED_DIM)
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=_unit(0),
                content_sha256="sha-c1",
                model=matching,
            ),
            EmbeddingRecord(
                chunk_id="c2",
                vector=_unit(0),
                content_sha256="sha-c2",
                model=foreign,
            ),
        ]
    )

    hits = store.search_vector(
        _unit(0),
        filters=SearchFilters.build(),
        limit=10,
        model=matching,
    )
    assert [h.chunk_id for h in hits] == ["c1"]

    foreign_hits = store.search_vector(
        _unit(0),
        filters=SearchFilters.build(),
        limit=10,
        model=foreign,
    )
    assert [h.chunk_id for h in foreign_hits] == ["c2"]

    absent = EmbeddingModelRef(provider="test", model="missing", dim=_EMBED_DIM)
    assert (
        store.search_vector(
            _unit(0), filters=SearchFilters.build(), limit=10, model=absent
        )
        == []
    )


def test_search_vector_empty_when_no_embeddings(store: PostgresStore) -> None:
    store.upsert_resources([_resource("r1")])
    store.upsert_chunks([_chunk("c1", "r1")])
    model = EmbeddingModelRef(provider="test", model="tiny", dim=_EMBED_DIM)
    assert (
        store.search_vector(
            _unit(0), filters=SearchFilters.build(), limit=5, model=model
        )
        == []
    )


def test_constructor_dim_mismatch(scratch_database_url: str) -> None:
    with pytest.raises(ValueError, match="dimension mismatch"):
        PostgresStore(scratch_database_url, embedding_dim=999, auto_open=True)


def test_capabilities_and_stats(store: PostgresStore) -> None:
    caps = store.capabilities()
    assert caps.backend == "postgres"
    assert caps.lexical_search is True
    assert caps.vector_search is True
    assert caps.embedding_dim == _EMBED_DIM

    stats = store.stats()
    assert stats["backend"] == "postgres"
    assert stats["embedding_dim"] == _EMBED_DIM
    assert "password" not in str(stats).lower()
    assert stats["pgvector_version"] is not None
