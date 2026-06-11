from __future__ import annotations

from amadeus.session import SessionManager
from amadeus.tools.defaults import FetchMessagesTool, ReadFileTool, SearchMessagesTool


def test_fetch_messages_tool_reads_session_messages(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    tool = FetchMessagesTool(store=manager.store)
    result = tool.execute(source_ref='["chat:1:0","chat:1:1"]')

    assert result.is_error is False
    assert [item["content"] for item in result.output["messages"]] == ["hello", "hi"]


def test_search_messages_tool_returns_matches(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "tool runtime")
    session.add_message("assistant", "copy that")
    manager.save(session)

    tool = SearchMessagesTool(store=manager.store)
    result = tool.execute(query="tool", session_key="chat:1")

    assert result.is_error is False
    assert result.output["count"] == 1


def test_read_file_tool_reads_utf8_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")

    tool = ReadFileTool()
    result = tool.execute(path=str(path))

    assert result.is_error is False
    assert result.output["content"] == "hello world"
