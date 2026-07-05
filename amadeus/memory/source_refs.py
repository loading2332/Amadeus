from __future__ import annotations

import hashlib
import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from amadeus.memory.engine import EvidenceRef

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


def source_ref_message_ids(source_ref: str) -> list[str]:
    base = source_ref.split("#", 1)[0].strip()
    if not base:
        return []
    try:
        payload = json.loads(base)
    except json.JSONDecodeError:
        return [base]
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item).strip()]
    text = str(payload).strip()
    return [text] if text else []


def build_message_source_ref(source_message_ids: list[str], summary: str) -> str:
    digest = hashlib.sha256(summary.encode("utf-8")).hexdigest()[:8]
    return f"{json.dumps(source_message_ids, ensure_ascii=False)}#h:{digest}"


def evidence_from_source_ref(source_ref: str) -> list[EvidenceRef]:
    refs = source_ref_message_ids(source_ref)
    if not refs:
        return []
    from amadeus.memory.engine import EvidenceRef

    return [
        EvidenceRef(
            kind="session_messages",
            refs=refs,
            resolver="amadeus.session.fetch_messages",
            source_ref=source_ref,
            metadata={},
        )
    ]


def collect_source_ref_ids(values: list[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        for candidate in source_ref_message_ids(str(raw_value or "").strip()):
            if candidate and candidate not in seen:
                seen.add(candidate)
                resolved.append(candidate)
    return resolved


def source_refs_from_evidence(evidence: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for item in evidence:
        source_ref = str(item.get("source_ref") or "").strip()
        if source_ref:
            values.append(source_ref)
        refs = item.get("refs")
        if isinstance(refs, list):
            values.extend(str(ref).strip() for ref in refs if str(ref).strip())
    return values
