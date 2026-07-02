from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.memory.engine import MemoryEngine
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


def _clean_ids(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("ids must be a list of strings")
    result: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item_id = str(raw).strip()
        if item_id and item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result


@dataclass
class ForgetMemoryTool:
    memory_engine: MemoryEngine | None
    name: str = "forget_memory"
    description: str = (
        "将已确认错误或不再应使用的长期记忆标记为失效。"
        "输入必须是 recall_memory 返回的 memory id，不是 message id。"
        "本工具只 soft-delete memory item，不删除原始 session messages。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要失效的 memory id 列表，来自 recall_memory 返回的 id 字段。",
                }
            },
            "required": ["ids"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={
                    "requested_ids": [],
                    "superseded_ids": [],
                    "missing_ids": [],
                    "count": 0,
                    "items": [],
                    "error": "memory engine is not configured",
                },
                is_error=True,
            )

        clean_ids = _clean_ids(kwargs.get("ids"))
        if not clean_ids:
            return ToolResult(
                tool_name=self.name,
                output={
                    "requested_ids": [],
                    "superseded_ids": [],
                    "missing_ids": [],
                    "count": 0,
                    "items": [],
                },
            )

        result = self.memory_engine.forget(clean_ids)

        return ToolResult(
            tool_name=self.name,
            output={
                "requested_ids": clean_ids,
                "superseded_ids": result.affected_ids,
                "missing_ids": result.missing_ids,
                "count": len(result.affected_ids),
                "items": result.items,
            },
        )
