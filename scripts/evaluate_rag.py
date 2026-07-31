#!/usr/bin/env python3
"""Offline RAG / tool evaluation for front-design-mcp (Package D).

Runs fixed Spanish/English product queries against local handlers (no network).
Metrics are intentionally basic — see docs/evaluation.md for limitations.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QUERIES: list[dict[str, Any]] = [
    {
        "id": "hero-reduced-motion",
        "query": (
            "Necesito un hero animado para Next.js que respete prefers-reduced-motion"
        ),
        "mode": "recommend",
        "target_framework": "nextjs",
        "accessibility": "prefers-reduced-motion",
    },
    {
        "id": "motion-vs-gsap",
        "query": "Compara Motion y GSAP para una landing con scroll storytelling",
        "mode": "compare",
        "options": ["motion:motion-library", "gsap:gsap-library"],
        "criteria": ["license", "accessibility", "performance", "frameworks"],
    },
    {
        "id": "pricing-a11y-tailwind",
        "query": "Encuentra componentes de pricing accesibles compatibles con Tailwind",
        "mode": "find_components",
        "intent": "pricing",
        "framework": "react",
    },
    {
        "id": "saas-dashboard-stack",
        "query": "Recomienda stack para un dashboard SaaS sobrio, rápido y responsive",
        "mode": "recommend",
        "target_framework": "react",
        "aesthetics": "sobrio responsive",
        "performance": "rápido",
    },
]

# Phrases that look like hard compatibility claims if they appear in facts without citation.
_HARD_COMPAT = re.compile(
    r"\b(fully compatible|guaranteed compatible|always works with|"
    r"100% compatible|verified compatible with)\b",
    re.IGNORECASE,
)


@dataclass
class QueryResult:
    query_id: str
    ok: bool
    relevant_hits: int = 0
    recommend_nonempty: bool = False
    citations_present: bool = False
    uncited_hard_claims: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        relevance_ok = self.relevant_hits >= 1 or self.recommend_nonempty
        return (
            self.ok
            and relevance_ok
            and self.citations_present
            and self.uncited_hard_claims == 0
        )


def _setup_offline_env() -> Path:
    td = Path(tempfile.mkdtemp(prefix="front-design-eval-"))
    os.environ["FRONT_DESIGN_DATA_DIR"] = str(td)
    os.environ["FRONT_DESIGN_DB_PATH"] = str(td / "store" / "eval.db")
    os.environ["FRONT_DESIGN_ENABLE_NETWORK_INGEST"] = "false"
    return td


def _has_citations(payload: dict[str, Any]) -> bool:
    if payload.get("citations"):
        return True
    for hit in payload.get("hits") or []:
        if isinstance(hit, dict) and hit.get("citation"):
            return True
    for item in payload.get("items") or []:
        if isinstance(item, dict) and (item.get("citation") or item.get("provenance")):
            return True
    for rec in payload.get("recommendation") or []:
        if isinstance(rec, dict) and (rec.get("citations") or rec.get("provenance")):
            return True
    return bool(payload.get("sources"))


def _count_uncited_hard_claims(payload: dict[str, Any]) -> int:
    facts = payload.get("facts") or []
    citations_ok = _has_citations(payload)
    count = 0
    for fact in facts:
        text = str(fact)
        if _HARD_COMPAT.search(text) and not citations_ok:
            count += 1
    return count


def _run_one(spec: dict[str, Any]) -> QueryResult:
    from front_design_mcp.tools import handlers

    qid = str(spec["id"])
    mode = spec["mode"]
    result = QueryResult(query_id=qid, ok=False)

    if mode == "recommend":
        payload = handlers.recommend_frontend_stack(
            requirements=str(spec["query"]),
            target_framework=spec.get("target_framework"),
            aesthetics=spec.get("aesthetics"),
            accessibility=spec.get("accessibility"),
            performance=spec.get("performance"),
            limit=5,
        )
        result.ok = bool(payload.get("ok"))
        recs = payload.get("recommendation") or []
        result.recommend_nonempty = len(recs) >= 1
        result.relevant_hits = len(recs)
        result.citations_present = _has_citations(payload)
        result.uncited_hard_claims = _count_uncited_hard_claims(payload)
        if not result.recommend_nonempty:
            result.notes.append("empty recommendation")
    elif mode == "compare":
        payload = handlers.compare_frontend_options(
            options=list(spec.get("options") or []),
            criteria=list(spec.get("criteria") or []),
        )
        result.ok = bool(payload.get("ok"))
        items = payload.get("items") or []
        result.relevant_hits = len(items)
        result.recommend_nonempty = len(items) >= 1
        result.citations_present = _has_citations(payload)
        result.uncited_hard_claims = _count_uncited_hard_claims(payload)
        if "facts" not in payload or "inferences" not in payload:
            result.notes.append("missing facts/inferences separation")
            result.ok = False
    elif mode == "find_components":
        payload = handlers.find_components(
            intent=str(spec.get("intent") or "pricing"),
            framework=spec.get("framework"),
            limit=5,
        )
        result.ok = bool(payload.get("ok"))
        items = payload.get("items") or []
        result.relevant_hits = len(items)
        result.citations_present = _has_citations(payload)
        result.uncited_hard_claims = _count_uncited_hard_claims(payload)
    else:
        result.notes.append(f"unknown mode {mode}")
        return result

    if not result.citations_present:
        result.notes.append("no citations")
    if result.uncited_hard_claims:
        result.notes.append(f"uncited hard claims={result.uncited_hard_claims}")
    return result


def run_evaluation() -> tuple[list[QueryResult], bool]:
    from front_design_mcp.tools.runtime import ensure_ready, reset_runtime

    _setup_offline_env()
    reset_runtime()
    ensure_ready()

    results = [_run_one(spec) for spec in QUERIES]
    passed = all(r.passed for r in results)
    return results, passed


def print_summary(results: list[QueryResult], passed: bool) -> None:
    print("=== front-design-mcp offline evaluation ===")
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(
            f"[{status}] {r.query_id}: hits={r.relevant_hits} "
            f"recommend_nonempty={r.recommend_nonempty} "
            f"citations={r.citations_present} "
            f"uncited_hard={r.uncited_hard_claims}"
            + (f" notes={r.notes}" if r.notes else "")
        )
    n_pass = sum(1 for r in results if r.passed)
    print(f"SUMMARY {n_pass}/{len(results)} passed; overall={'PASS' if passed else 'FAIL'}")


def main() -> int:
    results, passed = run_evaluation()
    print_summary(results, passed)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
