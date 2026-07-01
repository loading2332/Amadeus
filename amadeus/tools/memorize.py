from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.memory.engine import MemoryEngine, MemoryWriteRequest
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


@dataclass
class MemorizeTool:
    memory_engine: MemoryEngine | None
    name: str = "memorize"
    description: str = "把明确的用户长期事实写入长期记忆。"
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "memory_type": {"type": "string"},
                "source_ref": {"type": "string"},
                "happened_at": {"type": "string"},
            },
            "required": ["summary", "memory_type", "source_ref"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={"error": "memory engine is not configured"},
                is_error=True,
            )
        request = MemoryWriteRequest(
            summary=str(kwargs.get("summary") or "").strip(),
            memory_type=str(kwargs.get("memory_type") or "").strip(),
            source_ref=str(kwargs.get("source_ref") or "").strip(),
            happened_at=str(kwargs.get("happened_at") or "").strip() or None,
        )
        if not request.summary or not request.memory_type or not request.source_ref:
            return ToolResult(
                tool_name=self.name,
                output={"error": "summary, memory_type, and source_ref are required"},
                is_error=True,
            )
        result = await self.memory_engine.memorize(request)
        return ToolResult(
            tool_name=self.name,
            output={
                "status": result.status,
                "memory_id": result.item_id,
                "trace": dict(result.trace),
            },
            is_error=result.status not in {"new", "reinforced", "skipped"},
        )
