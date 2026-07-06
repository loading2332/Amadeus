from __future__ import annotations

import copy
import inspect
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from amadeus.tools.base import Tool
from amadeus.tools.search.backend import KeywordSearchBackend, SearchResult
from amadeus.tools.search.document import ToolDocument

RiskLevel = Literal["read-only", "write", "external-side-effect"]
SourceType = Literal["builtin", "mcp", "plugin"]

# ── 意图字段（progress description 软约束）─────────────────────────────
# ID1~ID5 决策：字段名固定 `purpose`（不撞 recall_memory 已用 `intent`）；
# 5-12 个字写在 description 文本里，**不**设 minLength / maxLength 硬约束；
# 不做"工具自声明 purpose 则不注入"的兼容分支——所有工具一律注入 + execute 前 pop。
_PURPOSE_FIELD = "purpose"
_PURPOSE_SCHEMA: dict[str, Any] = {
    "type": "string",
    "description": (
        "用 5-12 个字说明这次工具调用的意图，只写给用户看的短语。"
        "不要复述工具名，不要粘贴长参数。例如：查看目录、读取配置、搜索健康数据。"
    ),
}


def _inject_purpose(schema: dict[str, Any]) -> dict[str, Any]:
    """在 OpenAI function schema 的 parameters 里注入 purpose 字段并加入 required。

    deepcopy 避免污染工具自带 parameters。
    """
    cloned = copy.deepcopy(schema)
    function = cloned.get("function")
    if not isinstance(function, dict):
        return cloned
    parameters = function.get("parameters")
    if not isinstance(parameters, dict):
        return cloned
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        properties = {}
        parameters["properties"] = properties
    properties[_PURPOSE_FIELD] = dict(_PURPOSE_SCHEMA)
    required = parameters.get("required")
    if isinstance(required, list):
        if _PURPOSE_FIELD not in required:
            required.append(_PURPOSE_FIELD)
    else:
        parameters["required"] = [_PURPOSE_FIELD]
    return cloned


@dataclass(frozen=True)
class ToolMeta:
    """工具的元数据视图：做决策用（风险等级、可见性、来源）。"""

    risk: RiskLevel = "read-only"
    always_on: bool = False
    search_hint: str | None = None
    source_type: SourceType = "builtin"
    source_name: str = ""


def _build_document(tool: Tool, meta: ToolMeta) -> ToolDocument:
    return ToolDocument(
        name=tool.name,
        description=tool.description,
        risk=meta.risk,
        always_on=meta.always_on,
        search_hint=meta.search_hint,
        source_type=meta.source_type,
        source_name=meta.source_name,
    )


class ToolRegistry:
    """三表结构：_tools / _metadata / _documents 用工具名串起。

    - _tools:     name → Tool 实现（执行用）
    - _metadata:  name → ToolMeta（决策用：risk/always_on/search_hint/source_type/source_name）
    - _documents: name → ToolDocument（检索用：纯文本轻量视图）
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._metadata: dict[str, ToolMeta] = {}
        self._documents: dict[str, ToolDocument] = {}
        self._backend: KeywordSearchBackend = KeywordSearchBackend()

    def register(
        self,
        tool: Tool,
        *,
        risk: RiskLevel = "read-only",
        always_on: bool = False,
        search_hint: str | None = None,
        source_type: SourceType = "builtin",
        source_name: str = "",
    ) -> None:
        meta = ToolMeta(
            risk=risk,
            always_on=always_on,
            search_hint=search_hint,
            source_type=source_type,
            source_name=source_name,
        )
        document = _build_document(tool, meta)
        self._tools[tool.name] = tool
        self._metadata[tool.name] = meta
        self._documents[tool.name] = document
        self._backend.add(document)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._metadata.pop(name, None)
        self._documents.pop(name, None)
        self._backend.remove(name)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_metadata(self, name: str) -> ToolMeta | None:
        return self._metadata.get(name)

    def get_document(self, name: str) -> ToolDocument | None:
        return self._documents.get(name)

    def names(self) -> Iterable[str]:
        return self._tools.keys()

    def get_registered_names(self) -> set[str]:
        return set(self._tools.keys())

    def get_always_on_names(self) -> set[str]:
        return {name for name, meta in self._metadata.items() if meta.always_on}

    def get_names_by_source(self, source_name: str) -> set[str]:
        """按 source_name 反查工具名（MCP server 卸载时用）。"""
        return {
            name
            for name, meta in self._metadata.items()
            if meta.source_name == source_name
        }

    def get_documents(self) -> list[ToolDocument]:
        return list(self._documents.values())

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        allowed_risk: set[str] | None = None,
        excluded_names: set[str] | None = None,
    ) -> list[SearchResult]:
        return self._backend.search(
            query,
            top_k=top_k,
            allowed_risk=allowed_risk,
            excluded_names=excluded_names,
        )

    def get_schemas_as_doc_results(self, names: list[str]) -> list[SearchResult]:
        """将工具名列表转为与 search() 相同格式的结果列表。

        供 select:<工具名> 精确解锁路径使用，why_matched 固定为"名称:精确匹配"。
        """
        results: list[SearchResult] = []
        for name in names:
            doc = self._documents.get(name)
            if doc:
                results.append(
                    SearchResult(
                        name=doc.name,
                        summary=doc.description[:120],
                        why_matched=["名称:精确匹配"],
                        risk=doc.risk,
                        always_on=doc.always_on,
                    )
                )
        return results

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        """注册表的执行入口，作为 ToolExecutor 默认的 invoker provider。

        工具不存在时返回错误字符串（不抛，让上层 ToolExecutor 当 error 处理）。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"工具 '{name}' 不存在"
        result = tool.execute(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    def get_schemas(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        """导出 OpenAI function schema，每条注入 purpose 字段（R4）。"""
        if names is None:
            tools = list(self._tools.values())
        else:
            tools = [
                self._tools[name] for name in self._tools if name in names
            ]
        return [_inject_purpose(self._tool_to_schema(tool)) for tool in tools]

    def export_openai_tools(self) -> list[dict[str, Any]]:
        """旧调用点兼容薄壳；等价于 get_schemas(names=None)。"""
        return self.get_schemas(names=None)

    @staticmethod
    def _tool_to_schema(tool: Tool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }