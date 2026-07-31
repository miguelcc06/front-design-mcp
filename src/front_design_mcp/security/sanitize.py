"""Sanitize untrusted ingested documentation content.

All ingested docs are treated as untrusted data, never instructions.
"""

from __future__ import annotations

import re
from typing import Final

# Patterns that look like prompt-injection / instruction overrides in summaries.
_CONTROL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b"),
    re.compile(r"(?i)\bdisregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\b"),
    re.compile(r"(?i)\bact\s+as\s+(if\s+you\s+are\s+)?(a\s+)?(system|developer|admin)\b"),
    re.compile(r"(?i)\bsystem\s*:\s*"),
    re.compile(r"(?i)\bassistant\s*:\s*"),
    re.compile(r"(?i)\bnew\s+instructions?\s*:"),
    re.compile(r"(?i)\bdo\s+not\s+follow\s+(your\s+)?(safety|system)\s+(rules?|guidelines?)\b"),
    re.compile(r"(?i)\bjailbreak\b"),
    re.compile(r"(?i)\bprompt\s+injection\b"),
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"),
)

DEFAULT_MAX_LENGTH: Final[int] = 8_000

UNTRUSTED_PREFIX: Final[str] = "[UNTRUSTED_SOURCE_DATA] "


def strip_control_phrases(text: str) -> str:
    """Neutralize prompt-injection-like phrases in text."""
    cleaned = text
    for pattern in _CONTROL_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    # Collapse excess whitespace after removals
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def truncate(text: str, max_length: int = DEFAULT_MAX_LENGTH) -> str:
    """Truncate text to max_length, appending an ellipsis marker if needed."""
    if max_length <= 0:
        return ""
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def mark_untrusted(text: str) -> str:
    """Prefix text so callers treat it as untrusted data, not instructions."""
    if text.startswith(UNTRUSTED_PREFIX):
        return text
    return f"{UNTRUSTED_PREFIX}{text}"


def sanitize_summary(
    text: str,
    *,
    max_length: int = DEFAULT_MAX_LENGTH,
    mark: bool = True,
) -> str:
    """Full sanitize pipeline for summaries derived from ingested docs."""
    cleaned = strip_control_phrases(text)
    cleaned = truncate(cleaned, max_length=max_length)
    if mark:
        cleaned = mark_untrusted(cleaned)
    return cleaned
