from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from amadeus.session import SessionStore, fetch_messages, search_messages
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


def _optional_string(name: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a string")


def _required_string(name: str, value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a string")


def _optional_string_list(name: str, value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} must contain only strings")
    return value


def _optional_dict_list(name: str, value: object) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list of objects")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{name} must contain only objects")
        result.append(item)
    return result


def _int_arg(name: str, value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    raise TypeError(f"{name} must be an integer")


@dataclass
class FetchMessagesTool:
    store: SessionStore
    name: str = "fetch_messages"
    description: str = (
        "Fetch persisted original session messages by ids, source_ref, or recall evidence. "
        "这是 recall_memory、search_messages 和被动记忆注入之后唯一可作为最终证据的原文工具。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "source_ref": {"type": "string"},
                "source_refs": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "object"}},
                "context": {"type": "integer"},
            },
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        messages = fetch_messages(
            self.store,
            ids=_optional_string_list("ids", kwargs.get("ids")),
            source_ref=_optional_string("source_ref", kwargs.get("source_ref")),
            source_refs=_optional_string_list("source_refs", kwargs.get("source_refs")),
            evidence=_optional_dict_list("evidence", kwargs.get("evidence")),
            context=_int_arg("context", kwargs.get("context"), 0),
        )
        return ToolResult(
            tool_name=self.name,
            output={
                "count": len(messages),
                "matched_count": sum(1 for item in messages if item.get("in_source_ref") is True)
                or len(messages),
                "messages": messages,
            },
        )


@dataclass
class SearchMessagesTool:
    store: SessionStore
    name: str = "search_messages"
    description: str = (
        "Search persisted session messages by substring and return candidate previews with source_ref. "
        "预览不是最终证据；使用结果回答前必须调用 fetch_messages(source_ref=...) 读取原文。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_key": {"type": "string"},
                "role": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["query"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        payload = search_messages(
            self.store,
            query=_required_string("query", kwargs.get("query")),
            session_key=_optional_string("session_key", kwargs.get("session_key")),
            role=_optional_string("role", kwargs.get("role")),
            limit=_int_arg("limit", kwargs.get("limit"), 10),
            offset=_int_arg("offset", kwargs.get("offset"), 0),
        )
        return ToolResult(tool_name=self.name, output=payload)


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Read a UTF-8 text file from disk."
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        path = Path(_required_string("path", kwargs.get("path")))
        return ToolResult(
            tool_name=self.name,
            output={"path": str(path), "content": path.read_text(encoding="utf-8")},
        )
