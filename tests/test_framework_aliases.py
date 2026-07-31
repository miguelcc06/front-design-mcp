"""Framework alias matching — nextjs ↔ next/react, etc."""

from __future__ import annotations

import pytest

from front_design_mcp.config import Settings
from front_design_mcp.ingest.pipeline import run_ingest
from front_design_mcp.models import FrontendResource, ResourceKind, SourceRef
from front_design_mcp.tools import handlers
from front_design_mcp.tools.frameworks import normalize_framework_token
from front_design_mcp.tools.runtime import reset_runtime, resource_matches_framework


@pytest.fixture()
def ingested(tmp_path, monkeypatch):
    reset_runtime()
    db_path = tmp_path / "fw.db"
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(db_path))
    settings = Settings(data_dir=tmp_path, db_path=db_path, enable_network_ingest=False)
    report = run_ingest(sources=None, online=False, settings=settings)
    assert report.ok
    yield settings
    reset_runtime()


def _pricing_like() -> FrontendResource:
    return FrontendResource(
        id="pricing-table-pattern",
        name="Pricing table pattern",
        kind=ResourceKind.TEMPLATE,
        description="Pricing section",
        source=SourceRef(source_id="curated", source_name="curated"),
        tags=["pricing"],
        supported_frameworks=["react", "next"],
    )


def test_normalize_nextjs_aliases() -> None:
    for alias in ("nextjs", "next.js", "NextJS", "nextjs.app", "next"):
        tokens = normalize_framework_token(alias)
        assert "next" in tokens
        assert "react" in tokens


def test_normalize_react_aliases() -> None:
    for alias in ("react", "reactjs", "React", "react.js"):
        assert normalize_framework_token(alias) == {"react"}


def test_normalize_vue_svelte_angular_js() -> None:
    assert "vue" in normalize_framework_token("vue3")
    assert "vue" in normalize_framework_token("nuxt")
    assert "svelte" in normalize_framework_token("sveltekit")
    assert "angular" in normalize_framework_token("angular")
    assert "javascript" in normalize_framework_token("vanilla")
    assert "javascript" in normalize_framework_token("js")


def test_nextjs_matches_resource_tagged_next() -> None:
    resource = _pricing_like()
    assert resource_matches_framework(resource, "nextjs") is True
    assert resource_matches_framework(resource, "next") is True
    assert resource_matches_framework(resource, "react") is True


def test_empty_frameworks_not_excluded() -> None:
    resource = _pricing_like()
    resource.supported_frameworks = []
    assert resource_matches_framework(resource, "nextjs") is True


def test_find_components_pricing_nextjs(ingested) -> None:
    _ = ingested
    result = handlers.find_components(intent="pricing", framework="nextjs", limit=5)
    assert result["ok"] is True
    assert len(result["items"]) >= 1
