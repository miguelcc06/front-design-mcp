"""Intent coverage — hero/pricing/navbar/dashboard must return ≥1 hit."""

from __future__ import annotations

import pytest

from front_design_mcp.config import Settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.tools import handlers
from front_design_mcp.tools.runtime import reset_runtime


@pytest.fixture()
def ingested(tmp_path, monkeypatch):
    reset_runtime()
    db_path = tmp_path / "intent.db"
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(db_path))
    settings = Settings(data_dir=tmp_path, db_path=db_path, enable_network_ingest=False)
    report = run_ingest(sources=None, online=False, settings=settings)
    assert report.ok
    assert report.total_resources > 0
    yield settings
    reset_runtime()


@pytest.mark.parametrize("intent", ["hero", "pricing", "navbar", "dashboard"])
def test_intent_returns_at_least_one(ingested, intent: str) -> None:
    _ = ingested
    result = handlers.find_components(intent=intent, limit=5)
    assert result["ok"] is True
    assert len(result["items"]) >= 1, f"Expected ≥1 hit for intent={intent!r}"


def test_scroll_storytelling_intent(ingested) -> None:
    _ = ingested
    result = handlers.find_components(intent="scroll storytelling", limit=5)
    assert len(result["items"]) >= 1


def test_onboarding_intent(ingested) -> None:
    _ = ingested
    result = handlers.find_components(intent="onboarding", limit=5)
    assert len(result["items"]) >= 1
