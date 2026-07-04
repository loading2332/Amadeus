from __future__ import annotations

import json
from typing import Any

from amadeus.provider import LLMToolCall
from amadeus.tools.base import ToolResult


def tool_call_batch_snapshot(
    tool_calls: list[LLMToolCall],
) -> dict[str, object]:
    """Batch snapshot: 记录本轮所有 tool call 的基础信息。"""
    return {
        "call_ids": [tc.id for tc in tool_calls],
        "names": [tc.name for tc in tool_calls],
        "count": len(tool_calls),
    }


def append_assistant_tool_calls(
    messages: list[dict[str, Any]],
    *,
    content: str | None,
    tool_calls: list[LLMToolCall],
) -> None:
    messages.append(
        {
            "role": "assistant",
            "content": content,
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": json.dumps(tool_call.arguments, ensure_ascii=False),
                    },
                }
                for tool_call in tool_calls
            ],
        }
    )


def append_tool_result(
    messages: list[dict[str, Any]],
    *,
    tool_call_id: str,
    result: ToolResult,
) -> None:
    messages.append(
        {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": _render_tool_result_content(result),
        }
    )


def _render_tool_result_content(result: ToolResult) -> str:
    output = result.output
    if isinstance(output, str):
        return output
    try:
        return json.dumps(output, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(output)
