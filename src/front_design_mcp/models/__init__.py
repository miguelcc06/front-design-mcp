"""Pydantic domain models for frontend resources, search, and tool envelopes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl


class RetrievalMode(StrEnum):
    """How a result set was retrieved."""

    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"
    NONE = "none"


class ResourceKind(StrEnum):
    """Kinds of indexed frontend resources."""

    FRAMEWORK = "framework"
    LIBRARY = "library"
    COMPONENT = "component"
    ANIMATION = "animation"
    PATTERN = "pattern"
    TEMPLATE = "template"
    DOCUMENTATION_CHUNK = "documentation_chunk"


class LicenseInfo(BaseModel):
    """License metadata for a resource or chunk."""

    spdx_id: str | None = None
    name: str
    url: str | None = None
    redistributable: bool = True
    notes: str | None = None


class SourceRef(BaseModel):
    """Pointer to an upstream catalog / docs source."""

    source_id: str
    source_name: str
    homepage_url: str | None = None
    registry_url: str | None = None
    attribution: str | None = None


class VersionInfo(BaseModel):
    """Version metadata when known."""

    version: str | None = None
    released_at: datetime | None = None
    is_latest: bool | None = None


class FrontendResource(BaseModel):
    """Normalized frontend resource (component, library, pattern, etc.)."""

    id: str
    kind: ResourceKind
    name: str
    description: str = ""
    source: SourceRef
    homepage_url: str | None = None
    docs_url: str | None = None
    install_command: str | None = None
    license: LicenseInfo | None = None
    supported_frameworks: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    accessibility_notes: str | None = None
    performance_notes: str | None = None
    last_indexed_at: datetime | None = None
    attribution: str | None = None
    raw_refs: dict[str, Any] = Field(default_factory=dict)


class DocumentationChunk(BaseModel):
    """Indexed documentation snippet linked to a resource."""

    id: str
    resource_id: str
    title: str
    content: str
    source_url: str | None = None
    version: str | None = None
    license: LicenseInfo | None = None
    tags: list[str] = Field(default_factory=list)
    last_indexed_at: datetime | None = None
    content_sha256: str


class Citation(BaseModel):
    """Citation pointing back to an indexed chunk or resource."""

    resource_id: str | None = None
    chunk_id: str | None = None
    title: str
    url: str | None = None
    source_id: str | None = None
    excerpt: str | None = None


class SearchHit(BaseModel):
    """A single search result with score, ranking provenance, and citation.

    ``score`` is the final score of whichever strategy produced the hit. For
    hybrid results it is the Reciprocal Rank Fusion score, which is *not*
    comparable with raw BM25 or cosine values — the per-branch ranks and scores
    are reported separately so callers can audit the fusion.
    """

    resource: FrontendResource | None = None
    chunk: DocumentationChunk | None = None
    score: float
    citation: Citation | None = None
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    mode: RetrievalMode | None = None
    backend: str | None = None
    lexical_rank: int | None = None
    vector_rank: int | None = None
    lexical_score: float | None = None
    vector_score: float | None = None


class CompareResult(BaseModel):
    """Side-by-side comparison of resources."""

    items: list[FrontendResource]
    dimensions: list[str] = Field(default_factory=list)
    matrix: dict[str, dict[str, str]] = Field(default_factory=dict)
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class Recommendation(BaseModel):
    """A ranked recommendation with rationale split into facts vs inferences."""

    resource: FrontendResource
    rank: int
    rationale: str
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)


class FrontendBrief(BaseModel):
    """Structured brief for a UI/UX ask (inputs + constraints)."""

    goal: str
    frameworks: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    accessibility_requirements: list[str] = Field(default_factory=list)
    performance_budget: str | None = None
    tags: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)


class ToolResponseEnvelope(BaseModel):
    """Generic tool response separating grounded facts from inferences."""

    ok: bool = True
    message: str | None = None
    facts: list[str] = Field(default_factory=list)
    inferences: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


# Convenience re-export alias for HttpUrl typing in adapters
Url = HttpUrl

__all__ = [
    "RetrievalMode",
    "ResourceKind",
    "LicenseInfo",
    "SourceRef",
    "VersionInfo",
    "FrontendResource",
    "DocumentationChunk",
    "Citation",
    "SearchHit",
    "CompareResult",
    "Recommendation",
    "FrontendBrief",
    "ToolResponseEnvelope",
    "Url",
]
