from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.memory.engine import MemoryEngine, MemoryMutation
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]


@dataclass
class CorrectMemoryTool:
    memory_engine: MemoryEngine | None
    name: str = "correct_memory"
    description: str = (
        "更正一条长期记忆，并保留可回源的原始 source_ref 证据链。"
        "调用前必须先用 fetch_messages 核对原文，再提供 recall_memory 返回的 memory id。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "要更正的 memory id，必须来自 recall_memory 返回结果。",
                },
                "corrected_summary": {
                    "type": "string",
                    "description": "更正后的记忆摘要。",
                },
                "source_ref": {
                    "type": "string",
                    "description": "已用 fetch_messages 核对过的原始 source_ref。",
                },
                "kind": {
                    "type": "string",
                    "description": "更正后记忆类型；留空时沿用原记忆 kind。",
                },
            },
            "required": ["memory_id", "corrected_summary", "source_ref"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={"error": "vector memory is not configured"},
                is_error=True,
            )

        memory_id = str(kwargs.get("memory_id") or "").strip()
        corrected_summary = str(kwargs.get("corrected_summary") or "").strip()
        source_ref = str(kwargs.get("source_ref") or "").strip()
        kind = str(kwargs.get("kind") or "").strip()
        if not memory_id or not corrected_summary or not source_ref:
            return ToolResult(
                tool_name=self.name,
                output={
                    "error": "memory_id, corrected_summary, and source_ref are required"
                },
                is_error=True,
            )

        result = await self.memory_engine.mutate(
            MemoryMutation(
                kind="correct",
                ids=(memory_id,),
                corrected_summary=corrected_summary,
                source_ref=source_ref,
                replacement_kind=kind,
            )
        )
        if not result.accepted:
            error = _error_for_mutation_result(result.status)
            if result.status == "source_ref_mismatch":
                error = "source_ref does not match target memory"
            elif result.status == "missing":
                error = "memory id not found"
            elif result.status == "inactive":
                error = "memory id is not active"
            return ToolResult(
                tool_name=self.name,
                output={
                    "error": error,
                    "memory_id": memory_id,
                    "trace": dict(result.trace),
                },
                is_error=True,
            )

        trace = dict(result.trace)
        return ToolResult(
            tool_name=self.name,
            output={
                "memory_id": memory_id,
                "superseded_id": trace.get("superseded_id", memory_id),
                "replacement_id": trace.get("replacement_id"),
                "replacement_status": trace.get("replacement_status", "unknown"),
                "items": result.items,
                "trace": trace,
            },
        )


def _error_for_mutation_result(status: str) -> str:
    if status == "unsupported":
        return "memory correction is not supported"
    if status == "invalid":
        return "invalid correction request"
    if status == "conflict":
        return "correction conflicts with existing memory"
    if status == "skipped":
        return "replacement memory was not created"
    return "memory correction failed"
