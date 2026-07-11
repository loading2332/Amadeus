from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolDocument:
    """工具的检索索引态视图，由 Tool + ToolMeta 派生，供搜索后端使用。

    与完整 Tool 对象解耦：搜索在纯文本视图上做，成本不依赖工具实现有多重。
    """

    name: str
    description: str
    risk: str
    always_on: bool
    search_hint: str | None
    source_type: str  # "builtin" | "mcp" | "plugin"
    source_name: str  # mcp server 名 / plugin 名，builtin 为空字符串