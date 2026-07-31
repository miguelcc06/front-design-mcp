"""SQLite store integration tests against real temp-file databases."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

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
from front_design_mcp.store.sqlite_schema import SCHEMA_VERSION
from front_design_mcp.store.sqlite_store import SqliteStore


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _resource(
    rid: str,
    *,
    name: str | None = None,
    source_id: str = "src-a",
    kind: ResourceKind = ResourceKind.LIBRARY,
    tags: list[str] | None = None,
    frameworks: list[str] | None = None,
    capabilities: list[str] | None = None,
) -> FrontendResource:
    return FrontendResource(
        id=rid,
        kind=kind,
        name=name or rid,
        description=f"desc-{rid}",
        source=SourceRef(
            source_id=source_id,
            source_name=f"{source_id}-name",
            homepage_url=f"https://example.com/{source_id}",
            attribution="Attrib",
        ),
        homepage_url=f"https://example.com/{rid}",
        docs_url=f"https://docs.example.com/{rid}",
        install_command=f"npm i {rid}",
        license=LicenseInfo(name="MIT", spdx_id="MIT", url="https://mit.example", notes="ok"),
        supported_frameworks=frameworks or ["react", "vue"],
        tags=tags or ["ui", "component"],
        capabilities=capabilities or ["a11y", "theming"],
        accessibility_notes="keyboard nav",
        performance_notes="lazy",
        last_indexed_at=datetime(2024, 6, 15, 12, 0, tzinfo=UTC),
        attribution="Author",
        raw_refs={"style_tags": ["minimal"], "maturity": "stable"},
    )


def _chunk(
    cid: str,
    resource_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    tags: list[str] | None = None,
) -> DocumentationChunk:
    body = content or f"body-{cid}"
    return DocumentationChunk(
        id=cid,
        resource_id=resource_id,
        title=title or cid,
        content=body,
        source_url=f"https://docs.example.com/{cid}",
        version="1.0.0",
        license=LicenseInfo(name="MIT", spdx_id="MIT"),
        tags=tags or ["docs"],
        last_indexed_at=datetime(2024, 6, 15, 12, 0, tzinfo=UTC),
        content_sha256=_sha(body),
    )


@pytest.fixture
def store(tmp_path: Path) -> SqliteStore:
    s = SqliteStore(tmp_path / "store.db")
    yield s
    s.close()


def test_resource_and_chunk_round_trip(store: SqliteStore) -> None:
    resource = _resource("lib:widget")
    chunk = _chunk("lib:widget#1", "lib:widget", tags=["api", "hook"])
    store.upsert_resources([resource])
    store.upsert_chunks([chunk])

    got_r = store.get_resource("lib:widget")
    assert got_r is not None
    assert got_r.id == resource.id
    assert got_r.kind == resource.kind
    assert got_r.name == resource.name
    assert got_r.description == resource.description
    assert got_r.source == resource.source
    assert got_r.homepage_url == resource.homepage_url
    assert got_r.docs_url == resource.docs_url
    assert got_r.install_command == resource.install_command
    assert got_r.license is not None
    assert got_r.license.spdx_id == "MIT"
    assert got_r.license.name == "MIT"
    assert got_r.supported_frameworks == ["react", "vue"]
    assert got_r.tags == ["ui", "component"]
    assert got_r.capabilities == ["a11y", "theming"]
    assert got_r.accessibility_notes == "keyboard nav"
    assert got_r.performance_notes == "lazy"
    assert got_r.last_indexed_at == resource.last_indexed_at
    assert got_r.attribution == "Author"
    assert got_r.raw_refs == {"style_tags": ["minimal"], "maturity": "stable"}

    got_c = store.get_chunk("lib:widget#1")
    assert got_c is not None
    assert got_c.model_dump() == chunk.model_dump()


def test_transaction_batch_rollback_and_nesting(store: SqliteStore) -> None:
    store.upsert_resources([_resource("r-outside")])
    assert store.count_resources() == 1

    with pytest.raises(RuntimeError, match="boom"), store.transaction():
        store.upsert_resources([_resource("r-inner-a"), _resource("r-inner-b")])
        store.upsert_chunks([_chunk("c-a", "r-inner-a")])
        raise RuntimeError("boom")

    assert store.get_resource("r-inner-a") is None
    assert store.get_chunk("c-a") is None
    assert store.count_resources() == 1

    # Nested: inner exits cleanly; outer raises → nothing committed.
    with pytest.raises(RuntimeError, match="outer"), store.transaction():
        store.upsert_resources([_resource("r-nested")])
        with store.transaction():
            store.upsert_chunks([_chunk("c-nested", "r-nested")])
        raise RuntimeError("outer")

    assert store.get_resource("r-nested") is None
    assert store.get_chunk("c-nested") is None


def test_writes_inside_transaction_not_visible_to_second_connection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "vis.db"
    writer = SqliteStore(path)
    reader = SqliteStore(path)
    try:
        with writer.transaction():
            writer.upsert_resources([_resource("hidden")])
            # Second independent connection must not see uncommitted rows.
            assert reader.get_resource("hidden") is None
            assert reader.count_resources() == 0
        assert reader.get_resource("hidden") is not None
        assert reader.count_resources() == 1
    finally:
        writer.close()
        reader.close()


def test_list_resources_tag_filter_before_limit(store: SqliteStore) -> None:
    # Non-matching names sort earlier (aaa-*); matching have zzz-* names.
    non_match = [
        _resource(f"n-{i}", name=f"aaa-noise-{i:02d}", tags=["other"]) for i in range(15)
    ]
    match = [
        _resource(f"m-{i}", name=f"zzz-match-{i:02d}", tags=["wanted"]) for i in range(3)
    ]
    store.upsert_resources([*non_match, *match])
    found = store.list_resources(tags=["wanted"], limit=2)
    assert len(found) == 2
    assert all("wanted" in r.tags for r in found)


def test_list_resources_and_chunks_filters(store: SqliteStore) -> None:
    store.upsert_resources(
        [
            _resource("a1", source_id="src-a", kind=ResourceKind.LIBRARY, tags=["x"]),
            _resource("a2", source_id="src-a", kind=ResourceKind.COMPONENT, tags=["y"]),
            _resource("b1", source_id="src-b", kind=ResourceKind.LIBRARY, tags=["x"]),
        ]
    )
    store.upsert_chunks(
        [
            _chunk("c-a1", "a1"),
            _chunk("c-a2", "a2"),
            _chunk("c-b1", "b1"),
        ]
    )
    assert {r.id for r in store.list_resources(source_id="src-a")} == {"a1", "a2"}
    assert {r.id for r in store.list_resources(kind="library")} == {"a1", "b1"}
    assert {r.id for r in store.list_resources(source_id="src-a", kind="library")} == {"a1"}
    assert {c.id for c in store.list_chunks(resource_id="a1")} == {"c-a1"}
    assert {c.id for c in store.list_chunks(source_id="src-b")} == {"c-b1"}


def test_resolve_filtered_chunk_ids(store: SqliteStore) -> None:
    store.upsert_resources(
        [
            _resource("r1", source_id="s1", kind=ResourceKind.LIBRARY, tags=["alpha"]),
            _resource("r2", source_id="s1", kind=ResourceKind.COMPONENT, tags=["beta"]),
            _resource("r3", source_id="s2", kind=ResourceKind.LIBRARY, tags=[]),
        ]
    )
    store.upsert_chunks(
        [
            _chunk("c1", "r1", tags=[]),
            _chunk("c2", "r2", tags=["gamma"]),
            _chunk("c3", "r3", tags=["alpha"]),  # tag on chunk, not resource
        ]
    )
    assert store.resolve_filtered_chunk_ids(SearchFilters.build()) is None
    assert store.resolve_filtered_chunk_ids(
        SearchFilters.build(resource_ids=frozenset())
    ) == frozenset()
    assert store.resolve_filtered_chunk_ids(
        SearchFilters.build(source_id="s1")
    ) == frozenset({"c1", "c2"})
    assert store.resolve_filtered_chunk_ids(
        SearchFilters.build(kind="component")
    ) == frozenset({"c2"})
    # Tag on resource
    assert store.resolve_filtered_chunk_ids(
        SearchFilters.build(tags=["alpha"])
    ) == frozenset({"c1", "c3"})
    # Tag on chunk only
    assert store.resolve_filtered_chunk_ids(
        SearchFilters.build(tags=["gamma"])
    ) == frozenset({"c2"})


def test_list_chunk_fingerprints(store: SqliteStore) -> None:
    store.upsert_resources(
        [_resource("r1", source_id="s1"), _resource("r2", source_id="s2")]
    )
    c1 = _chunk("c1", "r1", content="one")
    c2 = _chunk("c2", "r2", content="two")
    store.upsert_chunks([c1, c2])
    all_fp = store.list_chunk_fingerprints()
    assert all_fp == {"c1": c1.content_sha256, "c2": c2.content_sha256}
    assert store.list_chunk_fingerprints(source_id="s1") == {"c1": c1.content_sha256}


def test_cascading_delete_removes_chunks_and_embeddings(store: SqliteStore) -> None:
    store.upsert_resources([_resource("r1")])
    chunk = _chunk("c1", "r1")
    store.upsert_chunks([chunk])
    model = EmbeddingModelRef(provider="fake", model="m", dim=4)
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=[0.1, 0.2, 0.3, 0.4],
                content_sha256=chunk.content_sha256,
                model=model,
            )
        ]
    )
    assert store.count_embeddings() == 1
    store.delete_resources(["r1"])
    assert store.get_resource("r1") is None
    assert store.get_chunk("c1") is None
    assert store.count_embeddings() == 0
    assert store.get_embedding_metadata(["c1"]) == {}


def test_embeddings_round_trip_and_guards(store: SqliteStore) -> None:
    store.upsert_resources([_resource("r1"), _resource("r2")])
    c1 = _chunk("c1", "r1", content="alpha")
    c2 = _chunk("c2", "r2", content="beta")
    store.upsert_chunks([c1, c2])

    model = EmbeddingModelRef(provider="fake", model="m", dim=3, pipeline_version=1)
    other = EmbeddingModelRef(provider="fake", model="other", dim=3, pipeline_version=1)
    vec = [0.125, -0.5, 1.0]
    store.upsert_embeddings(
        [
            EmbeddingRecord(
                chunk_id="c1",
                vector=vec,
                content_sha256=c1.content_sha256,
                model=model,
            ),
            EmbeddingRecord(
                chunk_id="c2",
                vector=[0.0, 0.0, 1.0],
                content_sha256=c2.content_sha256,
                model=other,
            ),
        ]
    )
    meta = store.get_embedding_metadata(["c1"])
    assert "c1" in meta
    assert meta["c1"].matches(model, c1.content_sha256) is True
    assert meta["c1"].matches(model, "wrong-sha") is False
    assert meta["c1"].matches(other, c1.content_sha256) is False

    vectors = store.get_embedding_vectors(["c1"])
    assert vectors["c1"] == pytest.approx(vec, abs=1e-6)

    with pytest.raises(ValueError, match="declares dim"):
        store.upsert_embeddings(
            [
                EmbeddingRecord(
                    chunk_id="c1",
                    vector=[1.0, 2.0],  # len 2 != dim 3
                    content_sha256=c1.content_sha256,
                    model=model,
                )
            ]
        )

    wide = EmbeddingModelRef(provider="fake", model="wide", dim=8)
    with pytest.raises(ValueError, match="dimension mismatch"):
        store.upsert_embeddings(
            [
                EmbeddingRecord(
                    chunk_id="c1",
                    vector=[0.0] * 8,
                    content_sha256=c1.content_sha256,
                    model=wide,
                )
            ]
        )

    deleted = store.delete_embeddings(not_matching=model)
    assert deleted == 1
    assert store.count_embeddings(model=model) == 1
    assert store.count_embeddings(model=other) == 0
    assert store.count_embeddings() == 1


def test_capabilities_and_stats(store: SqliteStore) -> None:
    caps = store.capabilities()
    assert caps.vector_search is False
    assert caps.lexical_search is True
    assert caps.backend == "sqlite"

    store.upsert_resources([_resource("r1")])
    store.upsert_chunks([_chunk("c1", "r1")])
    stats = store.stats()
    json.dumps(stats)  # must be JSON-serialisable
    assert stats["schema_version"] == SCHEMA_VERSION
    assert stats["resource_count"] == 1
    assert stats["chunk_count"] == 1
    assert stats["backend"] == "sqlite"
