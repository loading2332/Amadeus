from __future__ import annotations

import hashlib
from datetime import UTC, datetime


def _normalize_datetime(value: datetime) -> str:
    normalized = (
        value.astimezone(UTC).replace(tzinfo=None)
        if value.tzinfo
        else value.replace(tzinfo=None)
    )
    return normalized.replace(microsecond=0).isoformat()


def _content_hash(summary: str, memory_type: str) -> str:
    normalized = " ".join(summary.lower().split())
    return hashlib.sha256(f"{memory_type}:{normalized}".encode()).hexdigest()[:16]
