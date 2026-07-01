from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.memory.engine import MemoryEngine
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


@dataclass
class UndoMemoryBySourceTool:
    memory_engine: MemoryEngine | None
    name: str = "undo_memory_by_source"
    description: str = "按 source_ref 撤销对应长期记忆。"
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"source_ref": {"type": "string"}},
            "required": ["source_ref"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={"error": "memory engine is not configured"},
                is_error=True,
            )
        source_ref = str(kwargs.get("source_ref") or "").strip()
        if not source_ref:
            return ToolResult(
                tool_name=self.name,
                output={"error": "source_ref is required"},
                is_error=True,
            )
        result = self.memory_engine.undo_by_source(source_ref)
        return ToolResult(
            tool_name=self.name,
            output={
                "accepted": result.accepted,
                "status": result.status,
                "restored_ids": result.affected_ids,
                "missing_ids": result.missing_ids,
                "items": result.items,
                "trace": dict(result.trace),
            },
            is_error=not result.accepted,
        )
