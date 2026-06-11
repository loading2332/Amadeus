from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from amadeus.session import SessionStore, fetch_messages, search_messages
from amadeus.tools.base import ToolResult


@dataclass
class FetchMessagesTool:
    store: SessionStore
    name: str = "fetch_messages"
    description: str = "Fetch persisted session messages by ids or source_ref."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "source_ref": {"type": "string"},
                "context": {"type": "integer"},
            },
        }
    )

    def execute(self, **kwargs):
        messages = fetch_messages(
            self.store,
            ids=kwargs.get("ids"),
            source_ref=kwargs.get("source_ref"),
            context=int(kwargs.get("context", 0)),
        )
        return ToolResult(tool_name=self.name, output={"messages": messages})


@dataclass
class SearchMessagesTool:
    store: SessionStore
    name: str = "search_messages"
    description: str = "Search persisted session messages by substring."
    parameters: dict = field(
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

    def execute(self, **kwargs):
        payload = search_messages(
            self.store,
            query=str(kwargs["query"]),
            session_key=kwargs.get("session_key"),
            role=kwargs.get("role"),
            limit=int(kwargs.get("limit", 10)),
            offset=int(kwargs.get("offset", 0)),
        )
        return ToolResult(tool_name=self.name, output=payload)


@dataclass
class ReadFileTool:
    name: str = "read_file"
    description: str = "Read a UTF-8 text file from disk."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        }
    )

    def execute(self, **kwargs):
        path = Path(str(kwargs["path"]))
        return ToolResult(
            tool_name=self.name,
            output={"path": str(path), "content": path.read_text(encoding="utf-8")},
        )
