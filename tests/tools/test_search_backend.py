from __future__ import annotations

from amadeus.tools.search.backend import KeywordSearchBackend
from amadeus.tools.search.document import ToolDocument


def _doc(name, desc, hint=None, source_type="builtin", source_name=""):
    return ToolDocument(
        name=name,
        description=desc,
        risk="read-only",
        always_on=False,
        search_hint=hint,
        source_type=source_type,
        source_name=source_name,
    )


def test_exact_name_match_fast_path():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "读文件"))
    results = backend.search("read_file")

    assert len(results) == 1
    assert results[0].name == "read_file"
    assert "名称:精确匹配" in results[0].why_matched


def test_cjk_query_matches_search_hint():
    backend = KeywordSearchBackend()
    backend.add(_doc("search_messages", "检索消息", hint="找消息 搜索历史"))
    backend.add(_doc("read_file", "读文件", hint="读取"))

    results = backend.search("搜索消息", top_k=5)

    assert results[0].name == "search_messages"
    assert any("搜索提示" in w for w in results[0].why_matched)


def test_english_query_matches_name_part():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "Read file"))
    backend.add(_doc("search_messages", "Search messages"))

    results = backend.search("read", top_k=5)

    names = [r.name for r in results]
    assert "read_file" in names
    assert any("名称" in w for w in results[0].why_matched)


def test_excluded_names_filter_out():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "读文件"))
    backend.add(_doc("read_config", "读配置"))

    results = backend.search("read", top_k=5, excluded_names={"read_file"})

    assert "read_file" not in [r.name for r in results]


def test_no_match_returns_empty():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "读文件"))

    results = backend.search("zzzz")

    assert results == []


def test_mcp_bonus_only_applies_when_already_scored():
    """MCP 工具本身无关 query 不应靠 +2 进结果（修复 bug）。"""
    backend = KeywordSearchBackend()
    backend.add(_doc("mcp_github__read_pr", "whatever", source_type="mcp", source_name="github"))
    backend.add(_doc("search_messages", "搜索消息"))

    results = backend.search("搜索消息", top_k=5)

    # MCP 工具与 query 无关，不应出现
    names = [r.name for r in results]
    assert "mcp_github__read_pr" not in names
    assert "search_messages" in names


def test_mcp_bonus_ranks_tied_match_above_builtin():
    """同 name part 精确命中时，MCP 工具靠 +2 排前。"""
    backend = KeywordSearchBackend()
    backend.add(_doc("builtin_read", "Read", source_type="builtin"))
    backend.add(_doc("mcp_x__read", "Read", source_type="mcp", source_name="x"))

    results = backend.search("read", top_k=2)

    # 两者 name parts 都含 'read' 精确匹配得 10；MCP 加 +2 排前
    assert results[0].name == "mcp_x__read"


def test_remove_drops_from_index():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "读文件"))

    backend.remove("read_file")
    assert backend.search("read_file") == []


def test_empty_query_returns_empty():
    backend = KeywordSearchBackend()
    backend.add(_doc("read_file", "读文件"))

    assert backend.search("") == []