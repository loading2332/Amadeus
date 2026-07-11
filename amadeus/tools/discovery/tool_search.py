from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolRegistry

_SELECT_PREFIX = "select:"


@dataclass
class ToolSearchTool:
    """always_on 工具：让模型按需发现 deferred 工具。

    - query="select:<工具名>": 精确匹配，返回该工具的检索结果（触发解锁）
    - query=<普通查询>: 关键词打分检索，返回 top_k 候选列表
    """

    registry: ToolRegistry
    name: str = "tool_search"
    description: str = (
        "按需发现当前不可见的工具。query 可以是普通关键词（如 '搜索消息'）"
        "或 'select:<工具名>' 精确加载某个已知工具名。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询或 select:<工具名>",
                },
                "top_k": {
                    "type": "integer",
                    "description": "返回结果上限。",
                    "default": 5,
                },
            },
            "required": ["query"],
        }
    )

    def execute(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query") or "").strip()
        top_k = int(kwargs.get("top_k") or 5)
        if not query:
            return ToolResult(
                tool_name=self.name,
                output={"results": [], "hint": "query 不能为空"},
            )

        if query.startswith(_SELECT_PREFIX):
            target = query[len(_SELECT_PREFIX) :].strip()
            results = self.registry.get_schemas_as_doc_results([target])
            if not results:
                return ToolResult(
                    tool_name=self.name,
                    output={
                        "results": [],
                        "hint": f"工具 '{target}' 不存在或未注册",
                    },
                )
            return self._package(results, exact=True)

        results = self.registry.search(query, top_k=top_k)
        return self._package(results, exact=False)

    def _package(
        self, results: list[Any], *, exact: bool
    ) -> ToolResult:
        payload = [
            {
                "name": r.name,
                "summary": r.summary,
                "why_matched": r.why_matched,
                "risk": r.risk,
                "always_on": r.always_on,
            }
            for r in results
        ]
        return ToolResult(
            tool_name=self.name,
            output={
                "results": payload,
                "action": "select" if exact else "search",
            },
            metadata={"as_text": json.dumps(payload, ensure_ascii=False)},
        )