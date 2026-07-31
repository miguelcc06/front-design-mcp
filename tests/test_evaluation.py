# Evaluation tests — offline RAG / tool metrics
from __future__ import annotations

from scripts.evaluate_rag import QUERIES, run_evaluation


def test_evaluation_query_set() -> None:
    ids = [q["id"] for q in QUERIES]
    assert ids == [
        "hero-reduced-motion",
        "motion-vs-gsap",
        "pricing-a11y-tailwind",
        "saas-dashboard-stack",
    ]


def test_evaluation_offline_passes() -> None:
    results, passed = run_evaluation()
    assert len(results) == 4
    failed = [r.query_id for r in results if not r.passed]
    assert passed, f"evaluation failures: {failed} detail={[r for r in results if not r.passed]}"
    for r in results:
        assert r.citations_present
        assert r.uncited_hard_claims == 0
        assert r.relevant_hits >= 1 or r.recommend_nonempty
