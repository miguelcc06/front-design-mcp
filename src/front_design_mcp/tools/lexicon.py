"""Lightweight ES/EN lexicon for query expansion and bilingual intent detection.

Not a translation service — fixed product-term mappings for BM25 against an
English-indexed corpus.
"""

from __future__ import annotations

# Common Spanish (and a few EN synonyms) product terms → English index terms.
_TERM_EXPANSIONS: dict[str, str] = {
    "sobrio": "minimal clean sober",
    "sóbrio": "minimal clean sober",
    "rápido": "fast performance",
    "rapido": "fast performance",
    "tablero": "dashboard",
    "panel": "dashboard",
    "animado": "animation motion",
    "animación": "animation motion",
    "animacion": "animation motion",
    "accesible": "accessibility a11y",
    "accesibilidad": "accessibility a11y",
    "aterrizaje": "landing",
    "precios": "pricing",
    "planes": "pricing plans",
    "tarifas": "pricing",
    "navegación": "navbar navigation",
    "navegacion": "navbar navigation",
    "menú": "navbar menu",
    "menu": "navbar menu",
    "cabecera": "navbar header",
    "bienvenida": "onboarding",
    "desplazamiento": "scroll",
    "historia": "scroll storytelling",
    "aplicacion": "app application",
    "aplicación": "app application",
    "producto": "product saas",
    "limpio": "clean minimal",
    "moderno": "modern",
    "elegante": "elegant clean",
    "rendimiento": "performance fast",
}

# Canonical intents → trigger tokens (ES + EN) present in free text.
_INTENT_TRIGGERS: dict[str, tuple[str, ...]] = {
    "dashboard": ("dashboard", "tablero", "panel", "admin", "saas"),
    "hero": ("hero", "héroe", "heroe"),
    "pricing": ("pricing", "precios", "planes", "tarifas", "pricing-table"),
    "navbar": (
        "navbar",
        "nav",
        "navegación",
        "navegacion",
        "header",
        "menú",
        "menu",
        "cabecera",
    ),
    "landing": ("landing", "aterrizaje"),
    "saas": ("saas",),
    "scroll": ("scroll", "desplazamiento", "storytelling", "parallax"),
    "onboarding": ("onboarding", "bienvenida"),
    "animation": (
        "animation",
        "animado",
        "animación",
        "animacion",
        "motion",
        "microinteraction",
    ),
}

# Intents useful for find_components / brief component picks.
_COMPONENT_INTENTS = (
    "hero",
    "pricing",
    "navbar",
    "dashboard",
    "onboarding",
    "scroll storytelling",
    "landing",
)


def expand_query_lexicon(text: str) -> str:
    """Append English index terms for known ES/EN product words in ``text``."""
    raw = (text or "").strip()
    if not raw:
        return ""
    lower = raw.lower()
    extras: list[str] = []
    seen: set[str] = set()
    for term, expansion in _TERM_EXPANSIONS.items():
        if term in lower and expansion not in seen:
            extras.append(expansion)
            seen.add(expansion)
    if not extras:
        return raw
    return f"{raw} {' '.join(extras)}"


def detect_intents(text: str) -> list[str]:
    """Detect product intents present in requirements/description (ES+EN)."""
    lower = (text or "").lower()
    found: list[str] = []
    for intent, triggers in _INTENT_TRIGGERS.items():
        if any(tok in lower for tok in triggers):
            found.append(intent)
    return found


def select_component_intents(text: str, *, fallback: list[str] | None = None) -> list[str]:
    """Select find_components intents from bilingual text.

    Maps animation → hero when no other surface is present so animated landings
    still get a component pick. Always returns at least the fallback list.
    """
    detected = detect_intents(text)
    selected: list[str] = []

    for intent in _COMPONENT_INTENTS:
        # "scroll storytelling" is special — trigger via scroll tokens
        if intent == "scroll storytelling":
            if "scroll" in detected or "storytelling" in (text or "").lower():
                selected.append(intent)
            continue
        if intent in detected:
            selected.append(intent)

    if "animation" in detected and "hero" not in selected and (
        "landing" in detected or not selected
    ):
        # Animated landing/copy → pull hero motion surface
        selected.insert(0, "hero")

    if "landing" in detected and "hero" not in selected:
        selected.insert(0, "hero")

    if not selected:
        return list(fallback or ["hero", "navbar", "onboarding"])
    return selected
