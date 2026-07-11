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


class ToolNotFoundError(LookupError):
    """Registry 无法解析工具名时抛出的领域错误。"""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"工具 {tool_name!r} 不存在")


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

        工具名解析失败属于执行失败，必须抛 typed error，让 ToolExecutor
        统一归一为 ``status="error"``，不能伪装成普通成功输出。
        """
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(name)
        result = tool.execute(**arguments)
        if inspect.isawaitable(result):
            result = await result
        return result

    def get_schemas(self, names: set[str] | None = None) -> list[dict[str, Any]]:
        """导出远端工具的纯业务 schema；宿主字段由 Provider adapter 包装。"""
        if names is None:
            tools = list(self._tools.values())
        else:
            tools = [
                self._tools[name] for name in self._tools if name in names
            ]
        return [self._tool_to_schema(tool) for tool in tools]

    @staticmethod
    def _tool_to_schema(tool: Tool) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": copy.deepcopy(tool.parameters),
            },
        }
