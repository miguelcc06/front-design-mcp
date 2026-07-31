"""Framework token normalization and alias matching.

Lives outside the ``tools`` package so retrieval code can use it without
importing the MCP tool surface (which would be circular).
"""

from __future__ import annotations

from front_design_mcp.models import FrontendResource

# Alias map: normalized key → canonical token set used for intersection matching.
# nextjs implies React ecosystem compatibility for filtering purposes.
_FRAMEWORK_ALIASES: dict[str, set[str]] = {
    "next": {"next", "react", "nextjs"},
    "nextjs": {"next", "react", "nextjs"},
    "next.js": {"next", "react", "nextjs"},
    "nextjs.app": {"next", "react", "nextjs"},
    "react": {"react"},
    "reactjs": {"react"},
    "react.js": {"react"},
    "vue": {"vue"},
    "vue3": {"vue"},
    "vue.js": {"vue"},
    "nuxt": {"vue"},
    "svelte": {"svelte"},
    "sveltekit": {"svelte"},
    "angular": {"angular"},
    "vanilla": {"javascript"},
    "js": {"javascript"},
    "javascript": {"javascript"},
}


def normalize_framework_token(s: str) -> set[str]:
    """Lowercase/strip a framework string and expand known aliases.

    Returns a set of comparable tokens. Unknown tokens return ``{token}`` so
    exact matches still work for custom labels.
    """
    token = (s or "").lower().strip()
    if not token:
        return set()

    if token in _FRAMEWORK_ALIASES:
        return set(_FRAMEWORK_ALIASES[token])

    # Collapse punctuation/spaces for common variants (e.g. "Next JS" → "nextjs")
    compact = (
        token.replace(" ", "")
        .replace("_", "")
        .replace("-", "")
    )
    if compact in _FRAMEWORK_ALIASES:
        return set(_FRAMEWORK_ALIASES[compact])

    # "next.js" already handled; also try stripping dots only
    no_dots = token.replace(".", "")
    if no_dots in _FRAMEWORK_ALIASES:
        return set(_FRAMEWORK_ALIASES[no_dots])

    return {token}


def resource_matches_framework(resource: FrontendResource, framework: str | None) -> bool:
    """True when target framework aliases intersect resource frameworks.

    Empty ``supported_frameworks`` does **not** exclude the resource
    (unknown != incompatible). Callers should add an inference note when
    recommending such resources against a target framework.
    """
    if not framework:
        return True
    target = normalize_framework_token(framework)
    if not target:
        return True
    if not resource.supported_frameworks:
        return True
    resource_tokens: set[str] = set()
    for labeled in resource.supported_frameworks:
        resource_tokens |= normalize_framework_token(labeled)
    return bool(target & resource_tokens)


__all__ = ["normalize_framework_token", "resource_matches_framework"]
