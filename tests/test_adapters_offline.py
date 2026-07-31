"""Offline adapter fixture tests."""

from __future__ import annotations

import pytest

from front_design_mcp.adapters import ADAPTER_SOURCE_IDS, get_adapter_class
from front_design_mcp.models import FrontendResource


@pytest.mark.parametrize("source_id", list(ADAPTER_SOURCE_IDS))
def test_adapter_offline_returns_resources(source_id: str) -> None:
    adapter = get_adapter_class(source_id)()
    catalog = adapter.fetch_catalog(offline=True)
    assert isinstance(catalog, list)
    assert len(catalog) >= 1

    resources = [adapter.normalize(raw) for raw in catalog]
    assert all(isinstance(r, FrontendResource) for r in resources)
    assert all(r.source.source_id == source_id for r in resources)
    assert all(r.license is not None for r in resources)
    assert all(r.last_indexed_at is not None for r in resources)
    assert all(r.attribution for r in resources)


def test_magicui_has_enough_ui_items() -> None:
    adapter = get_adapter_class("magicui")()
    catalog = adapter.fetch_catalog(offline=True)
    ui = [i for i in catalog if i.get("type") == "registry:ui"]
    assert len(ui) >= 15


def test_shadcn_has_enough_components() -> None:
    adapter = get_adapter_class("shadcn")()
    catalog = adapter.fetch_catalog(offline=True)
    assert len(catalog) >= 20


def test_motion_has_animation_patterns() -> None:
    adapter = get_adapter_class("motion")()
    resources = [adapter.normalize(r) for r in adapter.fetch_catalog(offline=True)]
    assert len(resources) >= 11  # library + ≥10 patterns
    names = " ".join(r.name.lower() + " " + " ".join(r.tags) for r in resources)
    assert "spring" in names
    assert "scroll" in names


def test_radix_primitives() -> None:
    adapter = get_adapter_class("radix")()
    resources = [adapter.normalize(r) for r in adapter.fetch_catalog(offline=True)]
    assert len(resources) >= 11
    ids = " ".join(r.id for r in resources)
    assert "accordion" in ids
    assert "dialog" in ids


def test_gsap_license_not_redistributable() -> None:
    adapter = get_adapter_class("gsap")()
    assert adapter.license_info.redistributable is False
    assert adapter.license_info.spdx_id is None
    assert "Standard No Charge" in adapter.license_info.name
    resources = [adapter.normalize(r) for r in adapter.fetch_catalog(offline=True)]
    assert len(resources) >= 9
