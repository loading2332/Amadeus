from __future__ import annotations

from amadeus.mcp.tool import _make_wrapper_name, parse_wrapper_name


def test_make_wrapper_name_double_underscore():
    assert _make_wrapper_name("github", "read_pr") == "mcp_github__read_pr"


def test_parse_wrapper_name_round_trip():
    name = _make_wrapper_name("filesystem", "read_file")
    parsed = parse_wrapper_name(name)
    assert parsed == ("filesystem", "read_file")


def test_parse_wrapper_name_rejects_non_mcp_prefix():
    assert parse_wrapper_name("read_file") is None
    assert parse_wrapper_name("echo_tool") is None


def test_parse_wrapper_name_rejects_no_separator():
    assert parse_wrapper_name("mcp_github") is None


def test_parse_wrapper_name_handles_server_with_underscore():
    """server 名含下划线时仍能按 __ 分隔解析。"""
    name = _make_wrapper_name("my_server", "tool")
    assert name == "mcp_my_server__tool"
    assert parse_wrapper_name(name) == ("my_server", "tool")