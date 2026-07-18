from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")
_TITLE_LIMIT = 30


def title_from_first_message(content: str) -> str:
    """Build the deterministic session title used by the Web chat client."""
    normalized = _WHITESPACE.sub(" ", content).strip()
    if len(normalized) <= _TITLE_LIMIT:
        return normalized
    return f"{normalized[:_TITLE_LIMIT]}…"
