from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from amadeus.memory.engine import MemoryEngine, MemoryRecallRequest
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


def _parse_iso_datetime(value: object) -> str | None:
    """Accepts ISO-8601 string or datetime object, returns ISO string or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def _string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if isinstance(item, str) and item.strip())
    if isinstance(value, str):
        result = tuple(v.strip() for v in value.split(",") if v.strip())
        return result
    return ()


def _positive_limit(value: object, default: int = 8) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float, str)):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return default
    return default


@dataclass
class RecallMemoryTool:
    memory_engine: MemoryEngine | None
    name: str = "recall_memory"
    description: str = (
        "从长期记忆中检索与当前对话相关的历史信息。"
        "当你需要回忆用户的偏好、习惯、过往事件或任何历史记录时调用此工具。"
        "返回的是候选摘要，不是原始消息最终证据。"
        "回答依赖具体历史事实时，必须把 evidence 或 source_ref 交给 fetch_messages 回源。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索查询，描述你想找的信息内容。",
                },
                "intent": {
                    "type": "string",
                    "description": "检索意图：answer（语义检索）、timeline（时间线）、context（上下文填充）、interest（兴趣偏好）。",
                    "enum": ["answer", "timeline", "context", "interest", "procedure"],
                },
                "kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "按记忆类型过滤，如 event、preference、fact。留空则不限制。",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回结果上限。",
                    "default": 8,
                },
                "time_start": {
                    "type": "string",
                    "description": "ISO-8601 起始时间过滤（含该时间点之后的记忆）。",
                },
                "time_end": {
                    "type": "string",
                    "description": "ISO-8601 结束时间过滤（含该时间点之前的记忆）。",
                },
            },
            "required": ["query"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={
                    "count": 0,
                    "items": [],
                    "error": "memory engine is not configured",
                },
                is_error=True,
            )
        query_text = kwargs.get("query")
        if not query_text or not isinstance(query_text, str) or not query_text.strip():
            return ToolResult(
                tool_name=self.name,
                output={"count": 0, "items": [], "error": "query is required"},
                is_error=True,
            )

        time_start = _parse_iso_datetime(kwargs.get("time_start"))
        time_end = _parse_iso_datetime(kwargs.get("time_end"))

        memory_query = MemoryRecallRequest(
            text=query_text.strip(),
            intent=str(kwargs.get("intent", "answer")),
            memory_types=_string_list(kwargs.get("memory_types") or kwargs.get("kinds")),
            limit=_positive_limit(kwargs.get("limit")),
            time_start=datetime.fromisoformat(time_start) if time_start else None,
            time_end=datetime.fromisoformat(time_end) if time_end else None,
        )

        result = await self.memory_engine.recall(memory_query)

        items = [
            {
                "id": r.id,
                "kind": r.kind,
                "summary": r.summary,
                "score": r.score,
                "source_ref": r.source_ref,
                "evidence": [
                    {
                        "kind": e.kind,
                        "refs": e.refs,
                        "resolver": e.resolver,
                        "source_ref": e.source_ref,
                        "metadata": e.metadata,
                    }
                    for e in (r.evidence or [])
                ],
            }
            for r in result.records
        ]

        cited_item_ids = [str(item["id"]) for item in items if str(item.get("id", "")).strip()]
        output = {
            "count": len(items),
            "items": items,
            "trace": dict(result.trace),
            "citation_required": True,
            "citation_format": "§cited:[id1,id2,...]§",
            "cited_item_ids": cited_item_ids,
            "citation_rule": "Only cite memory IDs actually used in the final answer.",
        }
        return ToolResult(tool_name=self.name, output=output)
