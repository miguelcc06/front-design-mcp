"""Source adapter protocol and shared types.

Package B will implement concrete adapters (motion, magicui, shadcn, radix, gsap).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from front_design_mcp.models import FrontendResource, LicenseInfo, SourceRef


class SourceAdapter(ABC):
    """Protocol/ABC for ingesting an upstream frontend catalog."""

    @property
    @abstractmethod
    def source_id(self) -> str:
        """Stable identifier used in the adapter registry (e.g. ``motion``)."""

    @property
    @abstractmethod
    def source_ref(self) -> SourceRef:
        """Human-facing source metadata and attribution."""

    @property
    @abstractmethod
    def license_info(self) -> LicenseInfo:
        """Default license metadata for items from this source."""

    @abstractmethod
    def fetch_catalog(self, *, offline: bool = True) -> list[dict[str, Any]]:
        """Fetch raw catalog entries (online or from fixtures)."""

    @abstractmethod
    def fetch_details(self, item_id: str, *, offline: bool = True) -> dict[str, Any]:
        """Fetch raw details for a single catalog item."""

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> FrontendResource:
        """Normalize a raw catalog/detail payload into ``FrontendResource``."""
