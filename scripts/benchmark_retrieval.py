#!/usr/bin/env python3
"""Compare retrieval configurations on the hand-labelled eval query set.

Builds SearchService instances directly (no tools.runtime singleton).
PostgreSQL configs skip cleanly when FRONT_DESIGN_EVAL_DATABASE_URL is unset
or unreachable. Exit 0 unless a selected configuration errors unexpectedly.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Phrases that look like hard compatibility claims without a citation.
HARD_COMPAT = re.compile(
    r"\b(fully compatible|guaranteed compatible|always works with|"
    r"100% compatible|verified compatible with)\b",
    re.IGNORECASE,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUERIES = REPO_ROOT / "data" / "eval" / "queries.json"
EVAL_DATABASE_URL_ENV = "FRONT_DESIGN_EVAL_DATABASE_URL"

CONFIG_IDS = (
    "sqlite-bm25",
    "postgres-lexical",
    "postgres-vector",
    "postgres-hybrid",
)


@dataclass(frozen=True)
class EvalQuery:
    id: str
    query: str
    lang: str
    category: str
    filters: dict[str, Any]
    relevant_resource_ids: list[str]
    notes: str = ""

    @property
    def answerable(self) -> bool:
        return len(self.relevant_resource_ids) > 0

    @property
    def unanswerable(self) -> bool:
        return not self.answerable


@dataclass
class QueryRun:
    query_id: str
    resource_ids: list[str]
    latency_ms: float
    citation_ok_hits: int
    total_hits: int
    uncited_hard_claims: int
    mode: str
    notes: list[str] = field(default_factory=list)


@dataclass
class ConfigMetrics:
    config_id: str
    available: bool
    skip_reason: str | None = None
    recall_at_k: dict[int, float] = field(default_factory=dict)
    mrr_at_k: dict[int, float] = field(default_factory=dict)
    ndcg_at_k: dict[int, float] = field(default_factory=dict)
    latency_mean_ms: float | None = None
    latency_p95_ms: float | None = None
    empty_result_rate: float | None = None
    correct_abstention_rate: float | None = None
    citation_coverage: float | None = None
    uncited_hard_claims: int = 0
    n_queries: int = 0
    n_answerable: int = 0
    n_unanswerable: int = 0
    corpus: dict[str, int] = field(default_factory=dict)
    describe: dict[str, Any] = field(default_factory=dict)
    per_query: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Metrics (resource-level after dedup)
# ---------------------------------------------------------------------------


def dedupe_resource_ids(resource_ids: Sequence[str]) -> list[str]:
    """Keep first occurrence of each resource id (chunk hits collapse).

    Several chunks of one resource must not occupy multiple top-K slots for
    rank metrics — ranking quality is judged at resource granularity.
    """
    seen: set[str] = set()
    out: list[str] = []
    for rid in resource_ids:
        if rid in seen:
            continue
        seen.add(rid)
        out.append(rid)
    return out


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall_at_k is undefined for empty relevant set")
    top = list(ranked)[:k]
    hit = sum(1 for rid in top if rid in relevant)
    return hit / len(relevant)


def mrr_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """1/rank of first relevant in top K; 0 if none."""
    for i, rid in enumerate(list(ranked)[:k], start=1):
        if rid in relevant:
            return 1.0 / i
    return 0.0


def _dcg_at_k(gains: Sequence[float], k: int) -> float:
    total = 0.0
    for i, gain in enumerate(list(gains)[:k], start=1):
        total += gain / math.log2(i + 1)
    return total


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-gain nDCG@K with log2 discount; ideal DCG from |relevant| ones.

    Ideal ranking places min(k, |relevant|) relevant items first. When there
    are no relevant items, returns 1.0 only if the ranking is empty (perfect
    abstention); otherwise 0.0.
    """
    if not relevant:
        return 1.0 if len(list(ranked)[:k]) == 0 else 0.0
    gains = [1.0 if rid in relevant else 0.0 for rid in list(ranked)[:k]]
    dcg = _dcg_at_k(gains, k)
    ideal_gains = [1.0] * min(k, len(relevant))
    idcg = _dcg_at_k(ideal_gains, k)
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return ordered[lo]
    frac = rank - lo
    return ordered[lo] * (1 - frac) + ordered[hi] * frac


def count_uncited_hard_claims(
    facts: Sequence[str], *, has_citation: bool
) -> int:
    count = 0
    for fact in facts:
        if HARD_COMPAT.search(str(fact)) and not has_citation:
            count += 1
    return count


def hit_has_citation(hit: Any) -> bool:
    citation = getattr(hit, "citation", None)
    if citation is None:
        return False
    resource_id = getattr(citation, "resource_id", None) or ""
    url = getattr(citation, "url", None) or ""
    return bool(resource_id) and bool(url)


# ---------------------------------------------------------------------------
# Query loading
# ---------------------------------------------------------------------------


def load_queries(path: Path) -> list[EvalQuery]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["queries"] if isinstance(raw, dict) else raw
    queries: list[EvalQuery] = []
    for item in items:
        filters = item.get("filters") or {}
        queries.append(
            EvalQuery(
                id=str(item["id"]),
                query=str(item["query"]),
                lang=str(item["lang"]),
                category=str(item["category"]),
                filters={
                    "kind": filters.get("kind"),
                    "source_id": filters.get("source_id"),
                    "tags": list(filters.get("tags") or []),
                    "framework": filters.get("framework"),
                },
                relevant_resource_ids=list(item.get("relevant_resource_ids") or []),
                notes=str(item.get("notes") or ""),
            )
        )
    return queries


# ---------------------------------------------------------------------------
# Config builders
# ---------------------------------------------------------------------------


def _workspace_data_dir() -> Path:
    return REPO_ROOT / "data"


def build_sqlite_bm25() -> tuple[Any, Any, Any, Path]:
    """Return (settings, store, search, temp_dir_to_cleanup)."""
    from front_design_mcp.config import Settings
    from front_design_mcp.embeddings.base import NullEmbeddingProvider
    from front_design_mcp.ingest.pipeline import run_ingest
    from front_design_mcp.search.service import SearchService
    from front_design_mcp.store.factory import create_store

    td = Path(tempfile.mkdtemp(prefix="front-design-bench-sqlite-"))
    settings = Settings(
        data_dir=_workspace_data_dir(),
        db_path=td / "store" / "bench.db",
        enable_network_ingest=False,
        store_backend="sqlite",
        embedding_provider="none",
        search_mode="lexical",
    )
    store = create_store(settings)
    store.open()
    embedder = NullEmbeddingProvider()
    if store.count_resources() == 0:
        run_ingest(
            sources=None,
            online=False,
            settings=settings,
            store=store,
            embedder=embedder,
        )
    search = SearchService(
        store,
        embedder=embedder,
        search_mode="lexical",
        rrf_k=settings.rrf_k,
        rrf_lexical_weight=settings.rrf_lexical_weight,
        rrf_vector_weight=settings.rrf_vector_weight,
        candidates=settings.search_candidates,
    )
    search.rebuild()
    return settings, store, search, td


def _postgres_reachable(url: str) -> tuple[bool, str | None]:
    try:
        import psycopg
    except ImportError:
        return False, "psycopg is not installed (postgres extra missing)"
    from front_design_mcp.config import _strip_sqlalchemy_driver

    dsn = _strip_sqlalchemy_driver(url)
    try:
        with (
            psycopg.connect(dsn, connect_timeout=3) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1")
            cur.fetchone()
        return True, None
    except Exception as exc:  # noqa: BLE001 — report any connect failure
        return False, f"unreachable: {type(exc).__name__}: {exc}"


def build_postgres(
    *, search_mode: str, database_url: str
) -> tuple[Any, Any, Any]:
    from front_design_mcp.config import Settings
    from front_design_mcp.embeddings.factory import create_embedding_provider
    from front_design_mcp.search.service import SearchService
    from front_design_mcp.store.factory import create_store

    needs_vectors = search_mode in {"vector", "hybrid"}
    settings = Settings(
        data_dir=_workspace_data_dir(),
        enable_network_ingest=False,
        store_backend="postgres",
        database_url=database_url,
        embedding_provider="fastembed" if needs_vectors else "none",
        embedding_model="BAAI/bge-small-en-v1.5" if needs_vectors else None,
        search_mode=search_mode,  # type: ignore[arg-type]
    )
    store = create_store(settings)
    store.open()
    embedder = create_embedding_provider(settings)
    search = SearchService(
        store,
        embedder=embedder,
        search_mode=search_mode,
        rrf_k=settings.rrf_k,
        rrf_lexical_weight=settings.rrf_lexical_weight,
        rrf_vector_weight=settings.rrf_vector_weight,
        candidates=settings.search_candidates,
    )
    search.rebuild()
    return settings, store, search


def corpus_counts(store: Any) -> dict[str, int]:
    counts = {
        "resources": int(store.count_resources()),
        "chunks": int(store.count_chunks()),
    }
    count_emb = getattr(store, "count_embeddings", None)
    if callable(count_emb):
        try:
            counts["embeddings"] = int(count_emb())
        except Exception:  # noqa: BLE001
            counts["embeddings"] = 0
    else:
        # SQLite path may not expose embeddings when provider=none.
        counts["embeddings"] = 0
    return counts


# ---------------------------------------------------------------------------
# Running queries + aggregating
# ---------------------------------------------------------------------------


def run_one_query(search: Any, eq: EvalQuery, *, limit: int) -> QueryRun:
    filters = eq.filters
    t0 = time.perf_counter()
    outcome = search.search_detailed(
        eq.query,
        limit=limit,
        source_id=filters.get("source_id"),
        kind=filters.get("kind"),
        tags=filters.get("tags") or None,
        framework=filters.get("framework"),
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0

    resource_ids: list[str] = []
    citation_ok = 0
    uncited = 0
    for hit in outcome.hits:
        rid = hit.resource.id
        resource_ids.append(rid)
        cited = hit_has_citation(hit)
        if cited:
            citation_ok += 1
        facts = list(hit.facts or [])
        uncited += count_uncited_hard_claims(facts, has_citation=cited)

    return QueryRun(
        query_id=eq.id,
        resource_ids=dedupe_resource_ids(resource_ids),
        latency_ms=latency_ms,
        citation_ok_hits=citation_ok,
        total_hits=len(outcome.hits),
        uncited_hard_claims=uncited,
        mode=str(outcome.mode),
        notes=list(outcome.notes or []),
    )


def aggregate_metrics(
    *,
    config_id: str,
    queries: Sequence[EvalQuery],
    runs: Sequence[QueryRun],
    ks: Sequence[int],
    corpus: dict[str, int],
    describe: dict[str, Any],
) -> ConfigMetrics:
    by_id = {r.query_id: r for r in runs}
    answerable = [q for q in queries if q.answerable]
    unanswerable = [q for q in queries if q.unanswerable]

    recall: dict[int, float] = {}
    mrr: dict[int, float] = {}
    ndcg: dict[int, float] = {}
    for k in ks:
        if answerable:
            recall[k] = statistics.mean(
                recall_at_k(
                    by_id[q.id].resource_ids,
                    set(q.relevant_resource_ids),
                    k,
                )
                for q in answerable
            )
            mrr[k] = statistics.mean(
                mrr_at_k(
                    by_id[q.id].resource_ids,
                    set(q.relevant_resource_ids),
                    k,
                )
                for q in answerable
            )
            ndcg[k] = statistics.mean(
                ndcg_at_k(
                    by_id[q.id].resource_ids,
                    set(q.relevant_resource_ids),
                    k,
                )
                for q in answerable
            )
        else:
            recall[k] = 0.0
            mrr[k] = 0.0
            ndcg[k] = 0.0

    latencies = [by_id[q.id].latency_ms for q in queries]
    empty = sum(1 for q in queries if by_id[q.id].total_hits == 0)
    abstain_ok = (
        sum(1 for q in unanswerable if by_id[q.id].total_hits == 0)
        / len(unanswerable)
        if unanswerable
        else 1.0
    )
    total_hits = sum(by_id[q.id].total_hits for q in queries)
    cited_hits = sum(by_id[q.id].citation_ok_hits for q in queries)
    citation_coverage = cited_hits / total_hits if total_hits else 1.0
    hard = sum(by_id[q.id].uncited_hard_claims for q in queries)

    per_query = []
    for q in queries:
        run = by_id[q.id]
        relevant = set(q.relevant_resource_ids)
        entry: dict[str, Any] = {
            "id": q.id,
            "category": q.category,
            "lang": q.lang,
            "answerable": q.answerable,
            "hits": run.total_hits,
            "resource_ids": run.resource_ids,
            "latency_ms": round(run.latency_ms, 3),
            "mode": run.mode,
        }
        if q.answerable:
            for k in ks:
                entry[f"recall@{k}"] = recall_at_k(run.resource_ids, relevant, k)
                entry[f"mrr@{k}"] = mrr_at_k(run.resource_ids, relevant, k)
                entry[f"ndcg@{k}"] = ndcg_at_k(run.resource_ids, relevant, k)
        per_query.append(entry)

    return ConfigMetrics(
        config_id=config_id,
        available=True,
        recall_at_k=recall,
        mrr_at_k=mrr,
        ndcg_at_k=ndcg,
        latency_mean_ms=statistics.mean(latencies) if latencies else 0.0,
        latency_p95_ms=percentile(latencies, 95) if latencies else 0.0,
        empty_result_rate=empty / len(queries) if queries else 0.0,
        correct_abstention_rate=abstain_ok,
        citation_coverage=citation_coverage,
        uncited_hard_claims=hard,
        n_queries=len(queries),
        n_answerable=len(answerable),
        n_unanswerable=len(unanswerable),
        corpus=corpus,
        describe=describe,
        per_query=per_query,
    )


def run_config(
    config_id: str,
    queries: Sequence[EvalQuery],
    *,
    k_max: int,
    ks: Sequence[int],
) -> ConfigMetrics:
    store = None
    td: Path | None = None
    try:
        if config_id == "sqlite-bm25":
            _settings, store, search, td = build_sqlite_bm25()
        elif config_id.startswith("postgres-"):
            url = os.environ.get(EVAL_DATABASE_URL_ENV, "").strip()
            if not url:
                return ConfigMetrics(
                    config_id=config_id,
                    available=False,
                    skip_reason=(
                        f"{EVAL_DATABASE_URL_ENV} is unset; skipping PostgreSQL "
                        "configuration"
                    ),
                )
            ok, reason = _postgres_reachable(url)
            if not ok:
                return ConfigMetrics(
                    config_id=config_id,
                    available=False,
                    skip_reason=reason,
                )
            mode = config_id.removeprefix("postgres-")
            _settings, store, search = build_postgres(
                search_mode=mode, database_url=url
            )
        else:
            return ConfigMetrics(
                config_id=config_id,
                available=False,
                skip_reason=f"unknown configuration id: {config_id}",
            )

        corpus = corpus_counts(store)
        describe = dict(search.describe())
        runs = [run_one_query(search, q, limit=k_max) for q in queries]
        return aggregate_metrics(
            config_id=config_id,
            queries=queries,
            runs=runs,
            ks=ks,
            corpus=corpus,
            describe=describe,
        )
    finally:
        if store is not None:
            with contextlib.suppress(Exception):
                store.close()
        # Temp SQLite dirs are left for the OS; no shared developer DB is touched.


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def metrics_to_dict(m: ConfigMetrics) -> dict[str, Any]:
    return asdict(m)


def print_human(results: Sequence[ConfigMetrics], ks: Sequence[int]) -> None:
    print("=== retrieval benchmark ===")
    print(
        "Latency is single-process, cold-cache, tiny-corpus on one machine — "
        "NOT a PostgreSQL database benchmark."
    )
    print(
        "Rank metrics use resource-level deduplication before @K "
        "(multiple chunks of one resource count once)."
    )
    print(
        "nDCG uses binary gains and log2(i+1) discount; ideal DCG assumes "
        "min(K, |relevant|) relevant items first."
    )
    print()
    for m in results:
        print(f"--- {m.config_id} ---")
        if not m.available:
            print(f"  SKIPPED: {m.skip_reason}")
            continue
        d = m.describe
        print(
            f"  provider={d.get('embedding_provider')} "
            f"model={d.get('embedding_model')} "
            f"dim={d.get('embedding_dim')} "
            f"rrf_k={d.get('rrf_k')} "
            f"backend={d.get('backend')} "
            f"effective_mode={d.get('effective_mode')}"
        )
        print(
            f"  corpus resources={m.corpus.get('resources')} "
            f"chunks={m.corpus.get('chunks')} "
            f"embeddings={m.corpus.get('embeddings')}"
        )
        for k in ks:
            print(
                f"  Recall@{k}={m.recall_at_k[k]:.4f}  "
                f"MRR@{k}={m.mrr_at_k[k]:.4f}  "
                f"nDCG@{k}={m.ndcg_at_k[k]:.4f}"
            )
        print(
            f"  latency mean={m.latency_mean_ms:.2f}ms "
            f"p95={m.latency_p95_ms:.2f}ms"
        )
        print(
            f"  empty_result_rate={m.empty_result_rate:.4f}  "
            f"correct_abstention={m.correct_abstention_rate:.4f}  "
            f"citation_coverage={m.citation_coverage:.4f}  "
            f"uncited_hard_claims={m.uncited_hard_claims}"
        )
        print()


def print_markdown(results: Sequence[ConfigMetrics], ks: Sequence[int]) -> None:
    headers = [
        "config",
        "available",
        *[f"Recall@{k}" for k in ks],
        *[f"MRR@{k}" for k in ks],
        *[f"nDCG@{k}" for k in ks],
        "lat_mean_ms",
        "lat_p95_ms",
        "empty_rate",
        "abstention",
        "citation",
        "uncited_hard",
    ]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for m in results:
        if not m.available:
            row = [
                m.config_id,
                "skip",
                *["—" for _ in ks],
                *["—" for _ in ks],
                *["—" for _ in ks],
                "—",
                "—",
                "—",
                "—",
                "—",
                "—",
            ]
        else:
            row = [
                m.config_id,
                "yes",
                *[f"{m.recall_at_k[k]:.3f}" for k in ks],
                *[f"{m.mrr_at_k[k]:.3f}" for k in ks],
                *[f"{m.ndcg_at_k[k]:.3f}" for k in ks],
                f"{m.latency_mean_ms:.1f}",
                f"{m.latency_p95_ms:.1f}",
                f"{m.empty_result_rate:.3f}",
                f"{m.correct_abstention_rate:.3f}",
                f"{m.citation_coverage:.3f}",
                str(m.uncited_hard_claims),
            ]
        print("| " + " | ".join(row) + " |")
    # Reproducibility footer: one line per available configuration.
    available = [m for m in results if m.available]
    if available:
        print()
        for m in available:
            d = m.describe
            print(
                f"{m.config_id}: resources={m.corpus.get('resources')}, "
                f"chunks={m.corpus.get('chunks')}, "
                f"embeddings={m.corpus.get('embeddings')}; "
                f"provider={d.get('embedding_provider')}, "
                f"model={d.get('embedding_model')}, "
                f"dim={d.get('embedding_dim')}, "
                f"rrf_k={d.get('rrf_k')}, "
                f"effective_mode={d.get('effective_mode')}."
            )
        print(
            "Latency: single-process, cold-cache, tiny corpus — "
            "not a PostgreSQL benchmark."
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=[5, 10],
        help="K values for rank metrics (default: 5 10)",
    )
    p.add_argument(
        "--config",
        action="append",
        dest="configs",
        choices=list(CONFIG_IDS),
        help="Configuration to run (repeatable; default: all)",
    )
    p.add_argument(
        "--queries",
        type=Path,
        default=DEFAULT_QUERIES,
        help="Path to queries.json",
    )
    p.add_argument("--json", action="store_true", help="Machine-readable JSON")
    p.add_argument(
        "--markdown",
        action="store_true",
        help="Emit a markdown comparison table",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    ks = sorted({int(k) for k in args.k if int(k) > 0})
    if not ks:
        print("error: at least one positive --k required", file=sys.stderr)
        return 1
    k_max = max(ks)
    configs = args.configs or list(CONFIG_IDS)
    queries = load_queries(args.queries)

    results: list[ConfigMetrics] = []
    for cid in configs:
        try:
            results.append(run_config(cid, queries, k_max=k_max, ks=ks))
        except Exception as exc:  # noqa: BLE001
            print(
                f"error: configuration {cid} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    if args.json:
        payload = {
            "ks": ks,
            "queries_path": str(args.queries),
            "eval_database_url_env": EVAL_DATABASE_URL_ENV,
            "results": [metrics_to_dict(m) for m in results],
        }
        print(json.dumps(payload, indent=2, default=str))
    elif args.markdown:
        print_markdown(results, ks)
    else:
        print_human(results, ks)
        print_markdown(results, ks)

    return 0


if __name__ == "__main__":
    sys.exit(main())
