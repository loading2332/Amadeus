from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass(frozen=True)
class SeedSessionMessage:
    role: str
    content: str
    timestamp: str | None = None

    def to_record(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
        }
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        return payload


@dataclass(frozen=True)
class SeedLongTermMemory:
    summary: str
    memory_type: str
    source_message_indexes: tuple[int, ...] = ()
    happened_at: str | None = None
    source_ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "summary": self.summary,
            "memory_type": self.memory_type,
            "source_message_indexes": list(self.source_message_indexes),
        }
        if self.happened_at is not None:
            payload["happened_at"] = self.happened_at
        if self.source_ref is not None:
            payload["source_ref"] = self.source_ref
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


@dataclass(frozen=True)
class MemoryRecallCaseExpect:
    memory_intent: str | None = None
    candidate_count_min: int = 0
    injected_count_min: int = 0
    fallbacks_contains: tuple[str, ...] = ()
    context_contains: tuple[str, ...] = ()
    source_ref_required: bool = False
    fetched_messages_contains: tuple[str, ...] = ()
    answer_keywords_any: tuple[str, ...] = ()
    judge_rubric: str = ""

    def to_record(self) -> dict[str, Any]:
        return {
            "memory_intent": self.memory_intent,
            "candidate_count_min": self.candidate_count_min,
            "injected_count_min": self.injected_count_min,
            "fallbacks_contains": list(self.fallbacks_contains),
            "context_contains": list(self.context_contains),
            "source_ref_required": self.source_ref_required,
            "fetched_messages_contains": list(self.fetched_messages_contains),
            "answer_keywords_any": list(self.answer_keywords_any),
            "judge_rubric": self.judge_rubric,
        }


@dataclass(frozen=True)
class MemoryRecallCase:
    id: str
    mode: str
    title: str
    seed_session_messages: tuple[SeedSessionMessage, ...]
    seed_long_term_memories: tuple[SeedLongTermMemory, ...]
    input_payload: dict[str, Any]
    expect: MemoryRecallCaseExpect

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mode": self.mode,
            "title": self.title,
            "seed_session_messages": [
                message.to_record() for message in self.seed_session_messages
            ],
            "seed_long_term_memories": [
                memory.to_record() for memory in self.seed_long_term_memories
            ],
            "input": dict(self.input_payload),
            "expect": self.expect.to_record(),
        }


def load_memory_recall_cases(case_file: str | Path) -> list[MemoryRecallCase]:
    path = Path(case_file)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(payload, list):
        raw_cases = payload
    elif isinstance(payload, dict):
        raw_cases = payload.get("cases")
    else:
        raw_cases = None
    if not isinstance(raw_cases, list):
        raise ValueError(f"{path} must contain a top-level 'cases' list")
    return [_parse_case(item, index=index) for index, item in enumerate(raw_cases)]


def case_from_record(payload: dict[str, Any]) -> MemoryRecallCase:
    return _parse_case(payload, index=0)


def _parse_case(payload: Any, *, index: int) -> MemoryRecallCase:
    if not isinstance(payload, dict):
        raise ValueError(f"case[{index}] must be an object")
    case_id = _required_string(payload, "id", index=index)
    mode = _required_string(payload, "mode", case_id=case_id)
    if mode not in {"runtime_turn", "recall_tool"}:
        raise ValueError(f"{case_id}: unsupported mode {mode!r}")
    title = _required_string(payload, "title", case_id=case_id)

    raw_messages = payload.get("seed_session_messages")
    if not isinstance(raw_messages, list):
        raise ValueError(f"{case_id}: seed_session_messages must be a list")
    messages = tuple(_parse_seed_message(item, case_id=case_id) for item in raw_messages)

    raw_memories = payload.get("seed_long_term_memories")
    if not isinstance(raw_memories, list):
        raise ValueError(f"{case_id}: seed_long_term_memories must be a list")
    memories = tuple(
        _parse_seed_memory(item, case_id=case_id) for item in raw_memories
    )

    input_payload = payload.get("input")
    if not isinstance(input_payload, dict):
        raise ValueError(f"{case_id}: input must be an object")
    if mode == "runtime_turn" and not _non_empty_string(input_payload.get("user_message")):
        raise ValueError(f"{case_id}: runtime_turn input.user_message is required")
    if mode == "recall_tool" and not _non_empty_string(input_payload.get("recall_query")):
        raise ValueError(f"{case_id}: recall_tool input.recall_query is required")

    raw_expect = payload.get("expect")
    if not isinstance(raw_expect, dict):
        raise ValueError(f"{case_id}: expect must be an object")
    expect = _parse_expect(raw_expect, case_id=case_id)

    return MemoryRecallCase(
        id=case_id,
        mode=mode,
        title=title,
        seed_session_messages=messages,
        seed_long_term_memories=memories,
        input_payload=dict(input_payload),
        expect=expect,
    )


def _parse_seed_message(payload: Any, *, case_id: str) -> SeedSessionMessage:
    if not isinstance(payload, dict):
        raise ValueError(f"{case_id}: seed_session_messages items must be objects")
    role = _required_string(payload, "role", case_id=case_id)
    content = _required_string(payload, "content", case_id=case_id)
    timestamp = payload.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        raise ValueError(f"{case_id}: seed_session_messages.timestamp must be a string")
    return SeedSessionMessage(role=role, content=content, timestamp=cast(str | None, timestamp))


def _parse_seed_memory(payload: Any, *, case_id: str) -> SeedLongTermMemory:
    if not isinstance(payload, dict):
        raise ValueError(f"{case_id}: seed_long_term_memories items must be objects")
    summary = _required_string(payload, "summary", case_id=case_id)
    memory_type = _required_string(payload, "memory_type", case_id=case_id)
    raw_indexes = payload.get("source_message_indexes", [])
    if not isinstance(raw_indexes, list) or any(not isinstance(item, int) for item in raw_indexes):
        raise ValueError(f"{case_id}: source_message_indexes must be a list of integers")
    happened_at = payload.get("happened_at")
    if happened_at is not None and not isinstance(happened_at, str):
        raise ValueError(f"{case_id}: happened_at must be a string")
    source_ref = payload.get("source_ref")
    if source_ref is not None and not isinstance(source_ref, str):
        raise ValueError(f"{case_id}: source_ref must be a string")
    raw_extra = payload.get("extra", {})
    if not isinstance(raw_extra, dict):
        raise ValueError(f"{case_id}: extra must be an object")
    return SeedLongTermMemory(
        summary=summary,
        memory_type=memory_type,
        source_message_indexes=tuple(raw_indexes),
        happened_at=cast(str | None, happened_at),
        source_ref=cast(str | None, source_ref),
        extra=dict(raw_extra),
    )


def _parse_expect(payload: dict[str, Any], *, case_id: str) -> MemoryRecallCaseExpect:
    rubric = _required_string(payload, "judge_rubric", case_id=case_id)
    return MemoryRecallCaseExpect(
        memory_intent=_optional_string(payload.get("memory_intent")),
        candidate_count_min=_int_value(payload.get("candidate_count_min", 0), case_id=case_id, field="candidate_count_min"),
        injected_count_min=_int_value(payload.get("injected_count_min", 0), case_id=case_id, field="injected_count_min"),
        fallbacks_contains=_string_tuple(payload.get("fallbacks_contains"), case_id=case_id, field="fallbacks_contains"),
        context_contains=_string_tuple(payload.get("context_contains"), case_id=case_id, field="context_contains"),
        source_ref_required=bool(payload.get("source_ref_required", False)),
        fetched_messages_contains=_string_tuple(payload.get("fetched_messages_contains"), case_id=case_id, field="fetched_messages_contains"),
        answer_keywords_any=_string_tuple(payload.get("answer_keywords_any"), case_id=case_id, field="answer_keywords_any"),
        judge_rubric=rubric,
    )


def _required_string(
    payload: dict[str, Any],
    field: str,
    *,
    case_id: str | None = None,
    index: int | None = None,
) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        prefix = case_id or f"case[{index}]"
        raise ValueError(f"{prefix}: {field} is required")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _string_tuple(value: Any, *, case_id: str, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{case_id}: {field} must be a list of strings")
    return tuple(item.strip() for item in value if item.strip())


def _int_value(value: Any, *, case_id: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{case_id}: {field} must be an integer")
    return max(0, value)


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
