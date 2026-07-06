from __future__ import annotations

from amadeus.tools.discovery.tool_search import ToolSearchTool
from amadeus.tools.registry import ToolRegistry


def _register(reg: ToolRegistry, name: str, desc: str, **meta):
    class FakeTool:
        pass

    tool = FakeTool()
    tool.name = name
    tool.description = desc
    tool.parameters = {"type": "object", "properties": {}}
    tool.execute = lambda **k: None
    reg.register(tool, **meta)
    return tool


def test_select_prefix_returns_exact_match():
    reg = ToolRegistry()
    _register(reg, "read_file", "读文件")
    ts = ToolSearchTool(registry=reg)

    result = ts.execute(query="select:read_file")

    assert result.output["action"] == "select"
    assert len(result.output["results"]) == 1
    assert result.output["results"][0]["name"] == "read_file"
    assert "名称:精确匹配" in result.output["results"][0]["why_matched"]


def test_select_unknown_returns_empty_with_hint():
    reg = ToolRegistry()
    ts = ToolSearchTool(registry=reg)

    result = ts.execute(query="select:nonexistent")

    assert result.output["results"] == []
    assert "nonexistent" in result.output["hint"]


def test_normal_query_returns_ranked_results():
    reg = ToolRegistry()
    _register(reg, "search_messages", "检索消息", search_hint="搜索")
    _register(reg, "read_file", "读文件")

    ts = ToolSearchTool(registry=reg)
    result = ts.execute(query="搜索")

    assert result.output["action"] == "search"
    assert any(r["name"] == "search_messages" for r in result.output["results"])


def test_empty_query_returns_hint():
    reg = ToolRegistry()
    ts = ToolSearchTool(registry=reg)

    result = ts.execute(query="")

    assert result.output["results"] == []