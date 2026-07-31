"""Bilingual recommend/brief — Spanish SaaS + Next.js must return hits."""

from __future__ import annotations

import pytest

from front_design_mcp.config import Settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.tools import handlers
from front_design_mcp.tools.lexicon import (
    detect_intents,
    expand_query_lexicon,
    select_component_intents,
)
from front_design_mcp.tools.runtime import reset_runtime


@pytest.fixture()
def ingested(tmp_path, monkeypatch):
    reset_runtime()
    db_path = tmp_path / "i18n.db"
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(db_path))
    settings = Settings(data_dir=tmp_path, db_path=db_path, enable_network_ingest=False)
    report = run_ingest(sources=None, online=False, settings=settings)
    assert report.ok
    yield settings
    reset_runtime()


def test_lexicon_expands_spanish_saas_terms() -> None:
    expanded = expand_query_lexicon("SaaS dashboard sobrio y rápido")
    lower = expanded.lower()
    assert "minimal" in lower or "clean" in lower
    assert "fast" in lower or "performance" in lower
    assert "dashboard" in detect_intents("SaaS dashboard sobrio y rápido")


def test_select_intents_spanish_landing() -> None:
    intents = select_component_intents(
        "Landing con hero animado y pricing para Next.js"
    )
    assert "hero" in intents
    assert "pricing" in intents


def test_recommend_spanish_saas_dashboard_nextjs(ingested) -> None:
    _ = ingested
    result = handlers.recommend_frontend_stack(
        requirements="SaaS dashboard sobrio y rápido",
        target_framework="nextjs",
        accessibility="WCAG AA",
        limit=5,
    )
    assert result["ok"] is True
    recs = result.get("recommendation") or []
    assert len(recs) >= 1, f"Expected ≥1 recommendation, got message={result.get('message')!r}"


def test_brief_spanish_landing_hero_pricing_nextjs(ingested) -> None:
    _ = ingested
    result = handlers.build_frontend_brief(
        product_description="Landing con hero animado y pricing para Next.js",
        target_framework="nextjs",
    )
    assert result["ok"] is True
    stack = result.get("stack") or []
    components = result.get("components") or []
    assert len(stack) >= 1, "Expected non-empty stack"
    assert len(components) >= 1, "Expected non-empty components"
