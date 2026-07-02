from __future__ import annotations

import hashlib
import re

_TIME_PREFIX_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<hour>\d{2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?)?\]"
)


def parse_history_entry_happened_at(summary: str) -> str | None:
    match = _TIME_PREFIX_RE.match((summary or "").strip())
    if not match:
        return None
    date = match.group("date")
    hour = match.group("hour") or "00"
    minute = match.group("minute") or "00"
    second = match.group("second") or "00"
    return f"{date}T{hour}:{minute}:{second}"


def build_entry_source_ref(base_source_ref: str, entry: str) -> str:
    base = base_source_ref.strip()
    text = entry.strip()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12] if text else "empty"
    return f"{base}#h:{digest}" if base else f"#h:{digest}"
