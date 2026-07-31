# Evaluation tests — metrics, query set integrity, offline CI gate
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest
from scripts.benchmark_retrieval import (
    build_sqlite_bm25,
    dedupe_resource_ids,
    load_queries,
    mrr_at_k,
    ndcg_at_k,
    recall_at_k,
    run_one_query,
)
from scripts.evaluate_rag import QUERIES, run_evaluation

from front_design_mcp.config import Settings
from front_design_mcp.embeddings.base import NullEmbeddingProvider
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.store.factory import create_store

REPO_ROOT = Path(__file__).resolve().parents[1]
QUERIES_PATH = REPO_ROOT / "data" / "eval" / "queries.json"
REQUIRED_CATEGORIES = {
    "synonym",
    "conceptual",
    "typo",
    "filter",
    "unanswerable",
    "injection",
    "exact",
}
REQUIRED_KEYS = {
    "id",
    "query",
    "lang",
    "category",
    "filters",
    "relevant_resource_ids",
    "notes",
}


# --- metric unit tests (hand-computed) --------------------------------------


def test_recall_at_k_hand_computed() -> None:
    ranked = ["a", "b", "c", "d", "e"]
    relevant = {"a", "c", "z"}
    # top-2: only a → 1/3; top-3: a,c → 2/3; top-5: a,c → 2/3
    assert recall_at_k(ranked, relevant, 2) == pytest.approx(1 / 3)
    assert recall_at_k(ranked, relevant, 3) == pytest.approx(2 / 3)
    assert recall_at_k(ranked, relevant, 5) == pytest.approx(2 / 3)


def test_mrr_at_k_including_zero() -> None:
    ranked = ["x", "y", "a", "b"]
    relevant = {"a"}
    assert mrr_at_k(ranked, relevant, 10) == pytest.approx(1 / 3)
    assert mrr_at_k(ranked, relevant, 2) == 0.0  # first relevant beyond K
    assert mrr_at_k(["x", "y"], {"z"}, 5) == 0.0


def test_ndcg_at_k_perfect_and_hand_computed() -> None:
    relevant = {"a", "b"}
    perfect = ["a", "b", "c"]
    assert ndcg_at_k(perfect, relevant, 2) == pytest.approx(1.0)
    assert ndcg_at_k(perfect, relevant, 3) == pytest.approx(1.0)

    # ranked: b (rel), x (not), a (rel) — binary gains
    ranked = ["b", "x", "a"]
    # DCG = 1/log2(2) + 0/log2(3) + 1/log2(4) = 1 + 0 + 0.5 = 1.5
    # IDCG@3 with 2 relevant = 1/log2(2) + 1/log2(3) = 1 + 1/log2(3)
    dcg = 1.0 / math.log2(2) + 0.0 + 1.0 / math.log2(4)
    idcg = 1.0 / math.log2(2) + 1.0 / math.log2(3)
    expected = dcg / idcg
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(expected)


def test_ndcg_empty_relevant_abstention() -> None:
    assert ndcg_at_k([], set(), 5) == 1.0
    assert ndcg_at_k(["noise"], set(), 5) == 0.0


def test_resource_level_deduplication() -> None:
    chunk_hits = [
        "radix:radix-dialog",
        "radix:radix-dialog",  # second chunk of same resource
        "shadcn:dialog",
        "radix:radix-dialog",
        "shadcn:alert-dialog",
    ]
    deduped = dedupe_resource_ids(chunk_hits)
    assert deduped == [
        "radix:radix-dialog",
        "shadcn:dialog",
        "shadcn:alert-dialog",
    ]
    # After dedup, a single resource cannot fill three of the top-5 slots.
    assert len(deduped) == 3
    relevant = {"radix:radix-dialog", "shadcn:dialog"}
    assert recall_at_k(deduped, relevant, 5) == pytest.approx(1.0)
    # Without dedup, recall denominator is still |relevant| but ranking is polluted;
    # with dedup MRR sees dialog at rank 1.
    assert mrr_at_k(deduped, relevant, 5) == pytest.approx(1.0)


# --- query set integrity ----------------------------------------------------


def test_queries_json_schema_and_coverage() -> None:
    raw = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    items = raw["queries"]
    assert len(items) >= 24
    ids = [q["id"] for q in items]
    assert len(ids) == len(set(ids)), "query ids must be unique"
    cats: set[str] = set()
    for q in items:
        missing = REQUIRED_KEYS - set(q.keys())
        assert not missing, f"{q.get('id')}: missing keys {missing}"
        assert q["lang"] in {"en", "es"}
        assert q["category"] in REQUIRED_CATEGORIES
        cats.add(q["category"])
        filters = q["filters"]
        assert "kind" in filters and "source_id" in filters
        assert "tags" in filters and "framework" in filters
        assert isinstance(q["relevant_resource_ids"], list)
    assert cats >= REQUIRED_CATEGORIES, f"missing categories: {REQUIRED_CATEGORIES - cats}"
    unas = [q for q in items if q["category"] == "unanswerable"]
    assert len(unas) >= 3
    assert all(q["relevant_resource_ids"] == [] for q in unas)
    injections = [q for q in items if q["category"] == "injection"]
    assert len(injections) >= 2


def test_relevant_resource_ids_exist_in_offline_corpus() -> None:
    """Strict guard against stale judgements."""
    queries = load_queries(QUERIES_PATH)
    td = Path(tempfile.mkdtemp(prefix="front-design-eval-ids-"))
    settings = Settings(
        data_dir=REPO_ROOT / "data",
        db_path=td / "store" / "check.db",
        enable_network_ingest=False,
        store_backend="sqlite",
        embedding_provider="none",
    )
    store = create_store(settings)
    store.open()
    try:
        run_ingest(
            sources=None,
            online=False,
            settings=settings,
            store=store,
            embedder=NullEmbeddingProvider(),
        )
        known = {r.id for r in store.list_resources(limit=1_000_000)}
        assert len(known) == 90
        for q in queries:
            for rid in q.relevant_resource_ids:
                assert rid in known, f"{q.id}: unknown resource id {rid!r}"
    finally:
        store.close()


# --- tool cases + abstention behaviour --------------------------------------


def test_evaluation_tool_query_set() -> None:
    ids = [q["id"] for q in QUERIES]
    assert ids == [
        "hero-reduced-motion",
        "motion-vs-gsap",
        "pricing-a11y-tailwind",
        "saas-dashboard-stack",
    ]


def test_evaluation_offline_passes() -> None:
    results, passed, ranking = run_evaluation()
    assert len(results) == 4
    failed = [r.query_id for r in results if not r.passed]
    assert passed, (
        f"evaluation failures: {failed} "
        f"detail={[r for r in results if not r.passed]} "
        f"gate={getattr(ranking, '_gate_failures', None)}"
    )
    for r in results:
        assert r.citations_present
        assert r.uncited_hard_claims == 0
        assert r.relevant_hits >= 1 or r.recommend_nonempty
    assert ranking.citation_coverage == pytest.approx(1.0)
    assert ranking.uncited_hard_claims == 0


def test_unanswerable_queries_bm25_noise_documented() -> None:
    """BM25 returns lexical noise for all three unanswerable queries (measured).

    Do not treat empty results as the current SQLite behaviour — assert the
    real noise so regressions toward *more* silence are visible separately from
    the abstention metric printed by evaluate_rag / benchmark_retrieval.
    """
    queries = [q for q in load_queries(QUERIES_PATH) if q.unanswerable]
    assert len(queries) >= 3
    _settings, store, search, _td = build_sqlite_bm25()
    try:
        noisy: dict[str, list[str]] = {}
        for q in queries:
            run = run_one_query(search, q, limit=10)
            noisy[q.id] = run.resource_ids
            # Current measured behaviour: every unanswerable query returns hits.
            assert run.total_hits > 0, (
                f"{q.id} unexpectedly abstained; update docs/evaluation.md "
                f"and this assertion if retrieval improved"
            )
        # All three currently leak; correct_abstention_rate on sqlite-bm25 is 0.
        assert all(noisy[q.id] for q in queries)
    finally:
        store.close()
