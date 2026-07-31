"""Shared fixtures for front-design-mcp tests.

Postgres-specific session fixtures live in ``tests/test_postgres_store.py`` so the
default offline suite never imports psycopg / alembic unless those tests run.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Settings are read from the ambient environment and from a local ``.env``, so a
# developer (or a CI job) with FRONT_DESIGN_* exported would otherwise silently
# change what the tests assert. Tests that need a setting must set it explicitly.
_PRESERVED = {"FRONT_DESIGN_TEST_DATABASE_URL"}


@pytest.fixture(autouse=True)
def isolated_settings_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Remove ambient FRONT_DESIGN_* configuration for the duration of a test."""
    for key in list(os.environ):
        if key.startswith("FRONT_DESIGN_") and key not in _PRESERVED:
            monkeypatch.delenv(key, raising=False)
    yield
