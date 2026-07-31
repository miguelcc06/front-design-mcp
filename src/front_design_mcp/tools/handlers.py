"""MCP tool handlers for front-design-mcp (Package C product surface)."""

from __future__ import annotations

from typing import Any, Literal

from front_design_mcp.models import FrontendResource, ResourceKind
from front_design_mcp.tools.runtime import (
    chunk_to_dict,
    citation_to_dict,
    empty_results_hint,
    ensure_ready,
    hit_to_dict,
    provenance_from_resource,
    resource_matches_framework,
    resource_text_blob,
    resource_to_dict,
    unknown_id_hint,
)

DetailLevel = Literal["brief", "standard", "full"]


def _filter_resources(
    resources: list[FrontendResource],
    *,
    kind: str | None = None,
    framework: str | None = None,
    tags: list[str] | None = None,
    style_tags: list[str] | None = None,
    license: str | None = None,
    accessibility: bool | None = None,
    accessibility_text: str | None = None,
    animation: bool | None = None,
    maturity: str | None = None,
    source_id: str | None = None,
) -> list[FrontendResource]:
    tag_set = {t.lower() for t in (tags or [])}
    style_set = {t.lower() for t in (style_tags or [])}
    license_q = license.lower().strip() if license else None
    a11y_q = accessibility_text.lower().strip() if accessibility_text else None
    maturity_q = maturity.lower().strip() if maturity else None

    out: list[FrontendResource] = []
    for r in resources:
        if source_id and r.source.source_id != source_id:
            continue
        if kind and r.kind.value != kind:
            continue
        if not resource_matches_framework(r, framework):
            continue
        rtags = {t.lower() for t in r.tags}
        if tag_set and not tag_set.intersection(rtags):
            continue
        if style_set:
            style_raw = {
                str(t).lower() for t in (r.raw_refs.get("style_tags") or [])
            } | rtags
            if not style_set.intersection(style_raw):
                continue
        if license_q:
            lic = r.license
            blob = " ".join(
                filter(
                    None,
                    [
                        lic.spdx_id if lic else None,
                        lic.name if lic else None,
                        lic.notes if lic else None,
                    ],
                )
            ).lower()
            if license_q not in blob:
                continue
        if accessibility is True and not (r.accessibility_notes or "").strip():
            continue
        if accessibility is False and (r.accessibility_notes or "").strip():
            continue
        if a11y_q:
            notes = (r.accessibility_notes or "").lower()
            if a11y_q not in notes and a11y_q not in " ".join(r.tags).lower():
                continue
        if animation is not None:
            has_anim = bool(r.raw_refs.get("animation")) or (
                r.kind == ResourceKind.ANIMATION
                or "animation" in rtags
                or "motion" in rtags
                or "scroll" in rtags
            )
            if animation and not has_anim:
                continue
            if not animation and has_anim and r.kind == ResourceKind.ANIMATION:
                continue
        if maturity_q:
            mat = str(r.raw_refs.get("maturity") or "").lower()
            if maturity_q not in mat and maturity_q not in rtags:
                continue
        out.append(r)
    return out


def discover_frontend_resources(
    *,
    category: str | None = None,
    kind: str | None = None,
    framework: str | None = None,
    style: str | None = None,
    tags: list[str] | None = None,
    license: str | None = None,
    accessibility: bool | None = None,
    accessibility_text: str | None = None,
    animation: bool | None = None,
    maturity: str | None = None,
    source_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Browse/filter indexed frontend resources with pagination and provenance."""
    store, _search = ensure_ready()
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    kind_filter = kind or category
    style_tags = [style] if style else None
    all_resources = store.list_resources(limit=50_000, offset=0)
    filtered = _filter_resources(
        all_resources,
        kind=kind_filter,
        framework=framework,
        tags=tags,
        style_tags=style_tags,
        license=license,
        accessibility=accessibility,
        accessibility_text=accessibility_text,
        animation=animation,
        maturity=maturity,
        source_id=source_id,
    )
    total = len(filtered)
    page = filtered[offset : offset + limit]
    has_more = offset + limit < total
    next_offset = offset + limit if has_more else None

    items = []
    for r in page:
        items.append(
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind.value,
                "description": r.description[:400],
                "tags": r.tags,
                "supported_frameworks": r.supported_frameworks,
                "docs_url": r.docs_url,
                "install_command": r.install_command,
                "provenance": provenance_from_resource(r),
                "citation": {
                    "resource_id": r.id,
                    "title": r.name,
                    "url": r.docs_url or r.homepage_url,
                    "source_id": r.source.source_id,
                },
            }
        )

    message = None
    if total == 0:
        message = empty_results_hint("discover filters")

    return {
        "ok": True,
        "message": message,
        "items": items,
        "total_count": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset,
        "facts": [f"Matched {total} resources after filters."],
        "inferences": [],
    }


def search_frontend_knowledge(
    *,
    query: str,
    kind: str | None = None,
    framework: str | None = None,
    tags: list[str] | None = None,
    source_id: str | None = None,
    limit: int = 10,
    detail_level: DetailLevel = "standard",
) -> dict[str, Any]:
    """BM25 search over documentation chunks with scores, citations, provenance."""
    store, search = ensure_ready()
    q = (query or "").strip()
    limit = max(1, min(int(limit), 50))
    if not q:
        return {
            "ok": False,
            "message": "query is required. Pass a non-empty search string.",
            "hits": [],
            "facts": [],
            "inferences": [],
        }

    detail = detail_level if detail_level in ("brief", "standard", "full") else "standard"
    raw_hits = search.search(
        q,
        limit=max(limit * 3, 20),
        source_id=source_id,
        kind=kind,
        tags=tags,
    )

    hits_out: list[dict[str, Any]] = []
    for hit in raw_hits:
        resource = hit.resource
        if resource is None:
            continue
        if not resource_matches_framework(resource, framework):
            continue
        hits_out.append(hit_to_dict(hit, detail=detail))
        if len(hits_out) >= limit:
            break

    message = None if hits_out else empty_results_hint(q)
    return {
        "ok": True,
        "message": message,
        "query": q,
        "detail_level": detail,
        "hits": hits_out,
        "total_returned": len(hits_out),
        "facts": [f"BM25 search returned {len(hits_out)} hit(s) for query {q!r}."],
        "inferences": [],
        "store_resources": store.count_resources(),
    }


def get_resource_details(*, id: str) -> dict[str, Any]:
    """Return a normalized FrontendResource plus related sanitized chunks."""
    store, _search = ensure_ready()
    rid = (id or "").strip()
    if not rid:
        return {
            "ok": False,
            "message": "id is required.",
            "facts": [],
            "inferences": [],
        }

    resource = store.get_resource(rid)
    if resource is None:
        # Allow bare name match as a convenience
        lowered = rid.lower()
        for r in store.list_resources(limit=50_000):
            if r.id.lower() == lowered or r.name.lower() == lowered:
                resource = r
                break

    if resource is None:
        return {
            "ok": False,
            "message": unknown_id_hint(rid),
            "facts": [],
            "inferences": [],
            "suggestions": ["discover_frontend_resources", "search_frontend_knowledge"],
        }

    chunks = store.list_chunks(resource_id=resource.id, limit=20)
    return {
        "ok": True,
        "resource": resource_to_dict(resource),
        "chunks": [chunk_to_dict(c) for c in chunks],
        "license": resource.license.model_dump(mode="json") if resource.license else None,
        "attribution": resource.attribution or resource.source.attribution,
        "provenance": provenance_from_resource(resource),
        "facts": [
            f"Resource {resource.id} kind={resource.kind.value}",
            f"source={resource.source.source_id}",
            f"chunks={len(chunks)}",
        ],
        "inferences": [],
    }


def _resolve_resources(ids_or_names: list[str]) -> tuple[list[FrontendResource], list[str]]:
    store, _ = ensure_ready()
    found: list[FrontendResource] = []
    missing: list[str] = []
    catalog = store.list_resources(limit=50_000)
    by_id = {r.id.lower(): r for r in catalog}
    by_name = {r.name.lower(): r for r in catalog}

    for raw in ids_or_names:
        key = raw.strip().lower()
        if not key:
            continue
        resource = by_id.get(key) or by_name.get(key)
        if resource is None:
            # partial name contains
            resource = next(
                (r for r in catalog if key in r.name.lower() or key in r.id.lower()),
                None,
            )
        if resource is None:
            missing.append(raw)
        else:
            found.append(resource)
    return found, missing


_DEFAULT_COMPARE_CRITERIA = [
    "kind",
    "frameworks",
    "license",
    "accessibility",
    "performance",
    "install",
    "tags",
]


def compare_frontend_options(
    *,
    resources: list[str],
    criteria: list[str] | None = None,
) -> dict[str, Any]:
    """Structured comparison with facts vs inferences separated."""
    if not resources:
        return {
            "ok": False,
            "message": "Pass a list of resource ids or names to compare.",
            "facts": [],
            "inferences": [],
        }

    found, missing = _resolve_resources(resources)
    dims = list(criteria) if criteria else list(_DEFAULT_COMPARE_CRITERIA)
    matrix: dict[str, dict[str, str]] = {}
    facts: list[str] = []
    inferences: list[str] = []
    citations: list[dict[str, Any]] = []

    for r in found:
        row: dict[str, str] = {}
        for dim in dims:
            d = dim.lower()
            if d in ("kind", "type", "category"):
                row[dim] = r.kind.value
                facts.append(f"{r.id} kind={r.kind.value}")
            elif d in ("frameworks", "framework", "supported_frameworks"):
                row[dim] = ", ".join(r.supported_frameworks) or "unspecified"
                if r.supported_frameworks:
                    facts.append(f"{r.id} frameworks={r.supported_frameworks}")
                else:
                    inferences.append(
                        f"{r.id}: supported frameworks not recorded — do not assume compatibility."
                    )
            elif d in ("license",):
                if r.license:
                    row[dim] = r.license.spdx_id or r.license.name
                    facts.append(f"{r.id} license={row[dim]}")
                    if r.license.redistributable is False:
                        facts.append(f"{r.id} redistributable=false")
                else:
                    row[dim] = "unknown"
                    inferences.append(f"{r.id}: license unknown in index.")
            elif d in ("accessibility", "a11y"):
                if r.accessibility_notes:
                    row[dim] = r.accessibility_notes[:240]
                    facts.append(f"{r.id} has accessibility notes in index.")
                else:
                    row[dim] = "not documented in index"
                    inferences.append(
                        f"{r.id}: no accessibility notes indexed — do not claim a11y compliance."
                    )
            elif d in ("performance", "perf"):
                if r.performance_notes:
                    row[dim] = r.performance_notes[:240]
                    facts.append(f"{r.id} has performance notes in index.")
                else:
                    row[dim] = "not documented in index"
                    inferences.append(f"{r.id}: performance characteristics not verified in index.")
            elif d in ("install", "install_command"):
                row[dim] = r.install_command or "n/a"
                if r.install_command:
                    facts.append(f"{r.id} install={r.install_command}")
            elif d in ("tags", "style"):
                row[dim] = ", ".join(r.tags[:12])
            else:
                row[dim] = "n/a — criterion not mapped to indexed fields"
                inferences.append(f"Criterion {dim!r} has no verified field; skipped as fact.")
        matrix[r.id] = row
        citations.append(
            {
                "resource_id": r.id,
                "title": r.name,
                "url": r.docs_url or r.homepage_url,
                "source_id": r.source.source_id,
            }
        )

    message = None
    if missing:
        message = (
            "Some ids/names were not found: "
            + ", ".join(missing)
            + ". "
            + "Use discover_frontend_resources or search_frontend_knowledge."
        )
    if not found:
        return {
            "ok": False,
            "message": message or empty_results_hint("compare"),
            "items": [],
            "dimensions": dims,
            "matrix": {},
            "facts": facts,
            "inferences": inferences,
            "citations": citations,
        }

    inferences.append(
        "Compatibility between options is not verified unless explicitly stated in facts."
    )

    return {
        "ok": True,
        "message": message,
        "items": [resource_to_dict(r) for r in found],
        "dimensions": dims,
        "matrix": matrix,
        "facts": facts,
        "inferences": inferences,
        "citations": citations,
        "missing": missing,
    }


def recommend_frontend_stack(
    *,
    requirements: str,
    target_framework: str | None = None,
    constraints: list[str] | None = None,
    aesthetics: str | None = None,
    accessibility: str | None = None,
    performance: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Recommend a stack from indexed resources; separate facts from inferences."""
    store, search = ensure_ready()
    limit = max(1, min(int(limit), 15))
    req = (requirements or "").strip()
    if not req:
        return {
            "ok": False,
            "message": "requirements is required.",
            "facts": [],
            "inferences": [],
        }

    query_parts = [req]
    if aesthetics:
        query_parts.append(aesthetics)
    if accessibility:
        query_parts.append(accessibility)
    if performance:
        query_parts.append(performance)
    query = " ".join(query_parts)

    hits = search.search(query, limit=max(limit * 4, 20))
    recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()
    facts: list[str] = [f"Search query used: {query!r}"]
    inferences: list[str] = []
    sources: list[dict[str, Any]] = []

    for hit in hits:
        r = hit.resource
        if r is None or r.id in seen:
            continue
        if not resource_matches_framework(r, target_framework):
            continue
        seen.add(r.id)
        rank = len(recommendations) + 1
        item_facts = [
            f"Indexed as {r.kind.value} from {r.source.source_id}",
        ]
        if r.install_command:
            item_facts.append(f"Install: {r.install_command}")
        if r.license:
            item_facts.append(f"License: {r.license.spdx_id or r.license.name}")
        item_inferences = [
            "Fit to requirements is inferred from lexical overlap, not runtime verification.",
        ]
        if target_framework and not r.supported_frameworks:
            item_inferences.append(
                f"Target framework {target_framework!r} compatibility not verified in index."
            )
        recommendations.append(
            {
                "rank": rank,
                "resource": {
                    "id": r.id,
                    "name": r.name,
                    "kind": r.kind.value,
                    "description": r.description[:400],
                    "docs_url": r.docs_url,
                    "install_command": r.install_command,
                    "tags": r.tags,
                },
                "rationale": (
                    f"Lexical match score={hit.score:.3f} against requirements/aesthetics."
                ),
                "facts": item_facts,
                "inferences": item_inferences,
                "citations": [citation_to_dict(hit.citation)] if hit.citation else [],
                "provenance": provenance_from_resource(r),
            }
        )
        sources.append(provenance_from_resource(r))
        facts.extend(item_facts)
        inferences.extend(item_inferences)
        if len(recommendations) >= limit:
            break

    # Ensure library anchors appear when relevant
    libraries = [
        r
        for r in store.list_resources(kind="library", limit=50)
        if resource_matches_framework(r, target_framework)
    ]
    for lib in libraries[:3]:
        if lib.id in seen:
            continue
        facts.append(f"Available library in index: {lib.id}")

    constraint_notes = list(constraints or [])
    incompatibilities: list[str] = []
    for r in store.list_resources(limit=50_000):
        if (
            r.license
            and r.license.redistributable is False
            and any(r.id == rec["resource"]["id"] for rec in recommendations)
        ):
            incompatibilities.append(
                f"{r.id}: license not redistributable ({r.license.name}) — metadata use only."
            )
            facts.append(incompatibilities[-1])

    plan = [
        "Confirm license and install commands from facts below.",
        "Compose UI primitives (shadcn/radix) before decorative motion (magicui/motion/gsap).",
        "Validate accessibility and performance budgets in the target app — not assumed here.",
    ]
    if accessibility:
        plan.append(f"Accessibility constraint to verify in app: {accessibility}")
    if performance:
        plan.append(f"Performance constraint to verify in app: {performance}")

    inferences.append(
        "Stack ranking is heuristic BM25 guidance; verify compatibility before adopting."
    )

    message = None if recommendations else empty_results_hint(query)
    return {
        "ok": True,
        "message": message,
        "requirements": req,
        "target_framework": target_framework,
        "constraints": constraint_notes,
        "recommendation": recommendations,
        "trade_offs": [
            "Primitives (Radix/shadcn) prioritize a11y; Magic UI/Motion prioritize visual polish.",
            "GSAP entries are metadata-only; not redistributable (Standard No Charge).",
        ],
        "incompatibilities": incompatibilities,
        "plan": plan,
        "sources": sources,
        "facts": facts,
        "inferences": inferences,
    }


def find_components(
    *,
    intent: str,
    framework: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find components/patterns for an intent (hero, pricing, navbar, …)."""
    store, search = ensure_ready()
    intent_q = (intent or "").strip()
    limit = max(1, min(int(limit), 50))
    if not intent_q:
        return {
            "ok": False,
            "message": "intent is required (e.g. hero, pricing, navbar).",
            "items": [],
            "facts": [],
            "inferences": [],
        }

    intent_l = intent_q.lower()
    hits = search.search(intent_q, limit=max(limit * 5, 30))
    scored: dict[str, tuple[float, FrontendResource, dict[str, Any] | None]] = {}

    for hit in hits:
        r = hit.resource
        if r is None:
            continue
        if not resource_matches_framework(r, framework):
            continue
        scored[r.id] = (hit.score, r, citation_to_dict(hit.citation))

    # Direct tag/name/description match boost for intents
    for r in store.list_resources(limit=50_000):
        if not resource_matches_framework(r, framework):
            continue
        blob = resource_text_blob(r)
        if intent_l in blob or any(intent_l == t.lower() for t in r.tags):
            prev = scored.get(r.id)
            boost = 5.0 if intent_l in {t.lower() for t in r.tags} else 2.0
            score = (prev[0] if prev else 0.0) + boost
            citation = (
                prev[2]
                if prev
                else {
                    "resource_id": r.id,
                    "title": r.name,
                    "url": r.docs_url or r.homepage_url,
                    "source_id": r.source.source_id,
                }
            )
            scored[r.id] = (score, r, citation)

    ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)[:limit]
    items = []
    for score, r, citation in ranked:
        items.append(
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind.value,
                "description": r.description[:400],
                "tags": r.tags,
                "score": score,
                "docs_url": r.docs_url,
                "install_command": r.install_command,
                "provenance": provenance_from_resource(r),
                "citation": citation,
            }
        )

    message = None if items else empty_results_hint(intent_q)
    return {
        "ok": True,
        "message": message,
        "intent": intent_q,
        "framework": framework,
        "items": items,
        "total_returned": len(items),
        "facts": [f"Found {len(items)} component/pattern hit(s) for intent {intent_q!r}."],
        "inferences": [
            "Intent matching combines BM25 and tag/name contains; not a design-system guarantee."
        ],
    }


def find_animation_patterns(
    *,
    query: str,
    use_case: str | None = None,
    framework: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Find animation patterns with cost/a11y/reduced-motion notes when known."""
    store, search = ensure_ready()
    q = (query or use_case or "").strip()
    limit = max(1, min(int(limit), 50))
    if not q:
        return {
            "ok": False,
            "message": "query or use_case is required.",
            "items": [],
            "facts": [],
            "inferences": [],
        }

    search_q = " ".join(p for p in [query, use_case, "animation motion scroll"] if p)
    hits = search.search(search_q, limit=max(limit * 5, 40))
    scored: dict[str, tuple[float, FrontendResource, dict[str, Any] | None]] = {}

    anim_kinds = {ResourceKind.ANIMATION, ResourceKind.PATTERN, ResourceKind.LIBRARY}
    for hit in hits:
        r = hit.resource
        if r is None:
            continue
        if not resource_matches_framework(r, framework):
            continue
        tags = {t.lower() for t in r.tags}
        if r.kind not in anim_kinds and not (
            tags & {"animation", "motion", "scroll", "parallax", "gesture", "microinteraction"}
            or r.raw_refs.get("animation")
        ):
            continue
        scored[r.id] = (hit.score, r, citation_to_dict(hit.citation))

    q_l = q.lower()
    for r in store.list_resources(limit=50_000):
        if not resource_matches_framework(r, framework):
            continue
        tags = {t.lower() for t in r.tags}
        is_anim = (
            r.kind == ResourceKind.ANIMATION
            or bool(r.raw_refs.get("animation"))
            or bool(tags & {"animation", "motion", "scroll", "parallax", "gesture"})
        )
        if not is_anim:
            continue
        blob = resource_text_blob(r)
        if q_l in blob or any(tok in blob for tok in q_l.split() if len(tok) > 2):
            prev = scored.get(r.id)
            score = (prev[0] if prev else 0.0) + 3.0
            citation = (
                prev[2]
                if prev
                else {
                    "resource_id": r.id,
                    "title": r.name,
                    "url": r.docs_url or r.homepage_url,
                    "source_id": r.source.source_id,
                }
            )
            scored[r.id] = (score, r, citation)

    ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)[:limit]
    items = []
    facts: list[str] = []
    inferences: list[str] = []
    for score, r, citation in ranked:
        a11y = r.accessibility_notes
        perf = r.performance_notes
        reduced = None
        blob = (a11y or "") + " " + " ".join(r.tags)
        if "prefers-reduced-motion" in blob.lower() or "reduce-motion" in blob.lower():
            reduced = "Documented prefers-reduced-motion / reduced-motion support notes present."
            facts.append(f"{r.id}: {reduced}")
        elif a11y:
            reduced = (
                "Accessibility notes present; reduced-motion support not explicitly confirmed."
            )
            inferences.append(f"{r.id}: reduced-motion support not explicitly verified.")
        else:
            reduced = "Unknown — not documented in index."
            inferences.append(f"{r.id}: no a11y/reduced-motion notes in index.")

        cost_notes = perf or (
            "Cost not documented; prefer transform/opacity and limit concurrent effects "
            "(inference)."
        )
        if not perf:
            inferences.append(f"{r.id}: animation cost inferred — not measured.")
        else:
            facts.append(f"{r.id} performance notes indexed.")

        items.append(
            {
                "id": r.id,
                "name": r.name,
                "kind": r.kind.value,
                "description": r.description[:400],
                "score": score,
                "cost_notes": cost_notes,
                "accessibility_notes": a11y,
                "prefers_reduced_motion": reduced,
                "tags": r.tags,
                "docs_url": r.docs_url,
                "provenance": provenance_from_resource(r),
                "citation": citation,
            }
        )

    message = None if items else empty_results_hint(q)
    return {
        "ok": True,
        "message": message,
        "query": query,
        "use_case": use_case,
        "items": items,
        "total_returned": len(items),
        "facts": facts
        + [f"Returned {len(items)} animation-related hit(s)."],
        "inferences": inferences,
    }


def build_frontend_brief(
    *,
    product_description: str,
    constraints: list[str] | None = None,
    target_framework: str | None = None,
    aesthetics: str | None = None,
    accessibility: str | None = None,
    performance: str | None = None,
) -> dict[str, Any]:
    """Build an implementation brief; mark inferences clearly."""
    store, search = ensure_ready()
    desc = (product_description or "").strip()
    if not desc:
        return {
            "ok": False,
            "message": "product_description is required.",
            "facts": [],
            "inferences": [],
        }

    constraints = list(constraints or [])
    stack_resp = recommend_frontend_stack(
        requirements=desc,
        target_framework=target_framework,
        constraints=constraints,
        aesthetics=aesthetics,
        accessibility=accessibility,
        performance=performance,
        limit=6,
    )
    component_intents = [
        "hero",
        "navbar",
        "pricing",
        "dashboard",
        "onboarding",
        "scroll storytelling",
    ]
    # Pick intents that lexically touch the product description
    desc_l = desc.lower()
    selected = [i for i in component_intents if any(tok in desc_l for tok in i.split())]
    if not selected:
        selected = ["hero", "navbar", "onboarding"]

    components: list[dict[str, Any]] = []
    for intent in selected:
        found = find_components(intent=intent, framework=target_framework, limit=2)
        for item in found.get("items") or []:
            components.append({"intent": intent, **item})

    motion = find_animation_patterns(
        query=aesthetics or "scroll microinteraction",
        use_case=desc[:200],
        framework=target_framework,
        limit=4,
    )

    facts = list(stack_resp.get("facts") or [])
    inferences = list(stack_resp.get("inferences") or [])
    facts.append(f"Indexed store has {store.count_resources()} resources.")
    inferences.extend(
        [
            "Design tokens below are suggested defaults, not extracted from a brand system.",
            "Responsive behavior is a conventional recommendation, not measured.",
            "Acceptance criteria are proposed for agent follow-up — refine with product owners.",
        ]
    )

    tokens = {
        "color": {
            "background": "atmospheric gradient or photography plane (avoid flat single fill)",
            "foreground": "high-contrast text on hero",
            "accent": "single brand accent for CTAs",
        },
        "typography": {
            "display": "expressive display face for brand/hero (avoid Inter/Roboto/Arial defaults)",
            "body": "readable sans for supporting copy",
        },
        "space": {"section_y": "clamp(3rem, 8vw, 6rem)", "content_max": "72rem"},
        "motion": {
            "duration_fast": "150–200ms",
            "duration_section": "400–700ms",
            "respect": "prefers-reduced-motion → opacity-only or none",
        },
    }
    inferences.append("Token values are illustrative suggestions (inference).")

    acceptance = [
        "First viewport reads as one composition with brand as hero-level signal.",
        "Primary CTA is keyboard reachable with visible focus.",
        "Decorative motion disabled or reduced under prefers-reduced-motion.",
        "Cited components resolve to install/docs URLs from facts.",
        "No unverified compatibility claims between libraries.",
    ]
    if accessibility:
        acceptance.append(f"Meets stated accessibility constraint: {accessibility}")
    if performance:
        acceptance.append(f"Meets stated performance constraint: {performance}")

    return {
        "ok": True,
        "product_description": desc,
        "constraints": constraints,
        "stack": stack_resp.get("recommendation") or [],
        "components": components,
        "motion_system": {
            "patterns": motion.get("items") or [],
            "guidance": [
                "Prefer transform/opacity.",
                "Gate decorative motion behind prefers-reduced-motion.",
                "Limit concurrent scroll-linked layers.",
            ],
        },
        "design_tokens": tokens,
        "responsive_behavior": {
            "mobile_first": True,
            "breakpoints_inference": ["640px", "768px", "1024px", "1280px"],
            "notes": (
                "Collapse navbar to sheet/drawer on small screens; "
                "stack pricing tiers; keep hero full-bleed."
            ),
        },
        "acceptance_criteria": acceptance,
        "plan": stack_resp.get("plan") or [],
        "trade_offs": stack_resp.get("trade_offs") or [],
        "incompatibilities": stack_resp.get("incompatibilities") or [],
        "sources": stack_resp.get("sources") or [],
        "facts": facts,
        "inferences": inferences,
        "search_probe": {
            "sample_query": desc[:80],
            "hit_count": len(search.search(desc, limit=5)),
        },
    }
