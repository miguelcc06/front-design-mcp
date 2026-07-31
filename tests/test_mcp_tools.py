"""MCP tool/resource/prompt surface tests via FastMCP in-process Client."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from front_design_mcp.server import mcp
from front_design_mcp.tools.runtime import reset_runtime

EXPECTED_TOOLS = {
    "front_design_ping",
    "front_design_health",
    "discover_frontend_resources",
    "search_frontend_knowledge",
    "get_resource_details",
    "compare_frontend_options",
    "recommend_frontend_stack",
    "find_components",
    "find_animation_patterns",
    "build_frontend_brief",
}

@pytest.fixture(autouse=True)
def _ready_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    reset_runtime()
    monkeypatch.setenv("FRONT_DESIGN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FRONT_DESIGN_DB_PATH", str(tmp_path / "store" / "test.db"))
    monkeypatch.setenv("FRONT_DESIGN_ENABLE_NETWORK_INGEST", "false")
    monkeypatch.setenv("FRONT_DESIGN_EMBEDDING_PROVIDER", "none")
    monkeypatch.setenv("FRONT_DESIGN_STORE_BACKEND", "sqlite")
    yield tmp_path
    reset_runtime()


def _assert_no_secrets(payload: object, *, tmp_dir: Path) -> None:
    blob = json.dumps(payload, default=str) if not isinstance(payload, str) else payload
    assert "sk-" not in blob
    # Credential / password material must not appear (word "password" alone is ok
    # only if not paired with a value — reject common leak shapes).
    assert "password=" not in blob.lower()
    assert ":secret" not in blob.lower()
    assert "front_design:front_design" not in blob
    tmp_str = str(tmp_dir.resolve())
    for match in re.finditer(r"(/[\w./-]+\.db)", blob):
        path = match.group(1)
        assert path.startswith(tmp_str), f"db path outside tmp dir: {path}"


def _data(result: Any) -> dict[str, Any]:
    assert result.data is not None
    assert isinstance(result.data, dict)
    return result.data


@pytest.mark.asyncio
async def test_registered_tools_exact_set() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_health_payload(tmp_path: Path) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("front_design_health", {})
        data = _data(result)
        assert data.get("status") == "ok"
        assert data.get("backend") == "sqlite"
        assert "search" in data
        assert data["search"]["effective_mode"] == "lexical"
        caps = data["capabilities"]
        assert caps["vector_search"] is False
        assert caps["hybrid_search"] is False
        assert "store" in data
        assert data["store"]["resource_count"] >= 1
        blob = json.dumps(data, default=str)
        assert "sk-" not in blob
        assert "password=" not in blob.lower()
        _assert_no_secrets(data, tmp_dir=tmp_path)


@pytest.mark.asyncio
async def test_search_frontend_knowledge(tmp_path: Path) -> None:
    async with Client(mcp) as client:
        ok = await client.call_tool(
            "search_frontend_knowledge",
            {"query": "accordion", "limit": 5},
        )
        data = _data(ok)
        assert data.get("ok") is True
        hits = data.get("hits") or []
        assert len(hits) >= 1
        for hit in hits:
            citation = hit.get("citation") or {}
            assert citation.get("resource_id")
            retrieval = hit.get("retrieval") or {}
            assert retrieval.get("mode") == "lexical"
            assert retrieval.get("backend") == "sqlite"

        blank = await client.call_tool(
            "search_frontend_knowledge",
            {"query": "   "},
        )
        blank_data = _data(blank)
        assert blank_data.get("ok") is False
        assert blank_data.get("message")
        assert "query" in (blank_data.get("message") or "").lower()

        empty = await client.call_tool(
            "search_frontend_knowledge",
            {
                "query": "accordion",
                "framework": "definitely-not-a-real-framework-zzz",
            },
        )
        empty_data = _data(empty)
        assert empty_data.get("ok") is True
        assert (empty_data.get("hits") or []) == []
        assert empty_data.get("message") is not None
        _assert_no_secrets(data, tmp_dir=tmp_path)


@pytest.mark.asyncio
async def test_get_resource_details() -> None:
    async with Client(mcp) as client:
        by_id = await client.call_tool(
            "get_resource_details",
            {"id": "motion:motion-library"},
        )
        data = _data(by_id)
        assert data.get("ok") is True
        assert data["resource"]["id"] == "motion:motion-library"
        chunks = data.get("chunks") or []
        assert chunks
        for ch in chunks:
            content = ch.get("content") or ""
            assert content.startswith("[UNTRUSTED")

        # Bare name — Motion is a common fixture name
        by_name = await client.call_tool(
            "get_resource_details",
            {"id": data["resource"]["name"]},
        )
        assert _data(by_name).get("ok") is True

        missing = await client.call_tool(
            "get_resource_details",
            {"id": "no-such-resource-xyz"},
        )
        miss = _data(missing)
        assert miss.get("ok") is False
        assert miss.get("suggestions")


@pytest.mark.asyncio
async def test_compare_frontend_options() -> None:
    async with Client(mcp) as client:
        with_options = await client.call_tool(
            "compare_frontend_options",
            {
                "options": ["motion:motion-library", "gsap:gsap-library"],
                "criteria": ["license", "accessibility"],
            },
        )
        data = _data(with_options)
        assert data.get("ok") is True
        assert "facts" in data
        assert "inferences" in data

        deprecated = await client.call_tool(
            "compare_frontend_options",
            {
                "resources": ["motion:motion-library", "gsap:gsap-library"],
            },
        )
        dep = _data(deprecated)
        assert dep.get("ok") is True
        assert any("deprecated" in str(i).lower() for i in (dep.get("inferences") or []))

        unknown = await client.call_tool(
            "compare_frontend_options",
            {"options": ["motion:motion-library", "totally-unknown-id-zzz"]},
        )
        unk = _data(unknown)
        assert unk.get("ok") is True
        assert "totally-unknown-id-zzz" in (unk.get("missing") or [])


@pytest.mark.asyncio
async def test_product_tools_return_provenance(tmp_path: Path) -> None:
    async with Client(mcp) as client:
        find = _data(
            await client.call_tool(
                "find_components",
                {"intent": "pricing", "limit": 3},
            )
        )
        anim = _data(
            await client.call_tool(
                "find_animation_patterns",
                {"query": "scroll", "limit": 3},
            )
        )
        rec = _data(
            await client.call_tool(
                "recommend_frontend_stack",
                {
                    "requirements": "marketing site with motion",
                    "target_framework": "react",
                },
            )
        )
        brief = _data(
            await client.call_tool(
                "build_frontend_brief",
                {
                    "product_description": "SaaS marketing landing page",
                    "target_framework": "react",
                },
            )
        )

        assert find.get("ok") is True and find.get("items")
        assert anim.get("ok") is True and anim.get("items")
        assert rec.get("ok") is True and rec.get("recommendation")
        assert brief.get("ok") is True and (
            brief.get("components") or brief.get("stack")
        )

        for label, data in (
            ("find_components", find),
            ("find_animation_patterns", anim),
            ("recommend_frontend_stack", rec),
            ("build_frontend_brief", brief),
        ):
            assert "facts" in data, label
            assert "inferences" in data, label
            blob = json.dumps(data, default=str)
            assert (
                "citation" in blob
                or "provenance" in blob
                or "source_id" in blob
            ), label
            _assert_no_secrets(data, tmp_dir=tmp_path)


@pytest.mark.asyncio
async def test_resources_and_prompt() -> None:
    async with Client(mcp) as client:
        resources = await client.list_resources()
        uris = {str(r.uri) for r in resources}
        assert any("front-design://sources" in u for u in uris)

        sources = await client.read_resource("front-design://sources")
        # FastMCP may return a list of contents
        text = (
            sources[0].text
            if isinstance(sources, list) and sources
            else getattr(sources, "text", str(sources))
        )
        parsed = json.loads(text)
        assert parsed.get("count", 0) >= 1
        assert parsed.get("sources")

        resource = await client.read_resource(
            "front-design://resource/motion:motion-library"
        )
        rtext = (
            resource[0].text
            if isinstance(resource, list) and resource
            else getattr(resource, "text", str(resource))
        )
        rparsed = json.loads(rtext)
        assert rparsed.get("ok") is True
        assert rparsed["resource"]["id"] == "motion:motion-library"

        prompts = await client.list_prompts()
        names = {p.name for p in prompts}
        assert "frontend_implementation_brief" in names

        rendered = await client.get_prompt(
            "frontend_implementation_brief",
            {
                "product_description": "A docs site",
                "target_framework": "vue",
            },
        )
        # Message content should mention the product / framework / tools
        messages = getattr(rendered, "messages", None) or rendered
        blob = json.dumps(messages, default=str)
        assert "docs site" in blob.lower() or "A docs site" in blob
        assert "vue" in blob.lower()
        assert "build_frontend_brief" in blob
