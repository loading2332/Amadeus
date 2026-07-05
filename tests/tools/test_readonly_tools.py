from __future__ import annotations

from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager
from amadeus.tools.defaults import FetchMessagesTool, ReadFileTool, SearchMessagesTool


def test_fetch_messages_tool_reads_session_messages(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(SessionRef(user_id=1, session_id=1))
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    tool = FetchMessagesTool(store=manager.store)
    result = tool.execute(source_ref='["session:1:1:0","session:1:1:1"]')

    assert result.is_error is False
    assert [item["content"] for item in result.output["messages"]] == ["hello", "hi"]
    assert result.output["count"] == 2
    assert result.output["matched_count"] == 2


def test_fetch_messages_tool_reads_recall_evidence(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(SessionRef(user_id=1, session_id=1))
    session.add_message("user", "I am learning memory evidence")
    session.add_message("assistant", "Use fetch_messages to verify source text")
    session.add_message("user", "The source_ref should keep this traceable")
    manager.save(session)

    tool = FetchMessagesTool(store=manager.store)
    result = tool.execute(
        evidence=[
            {
                "kind": "session_messages",
                "refs": ["session:1:1:1"],
                "resolver": "amadeus.session.fetch_messages",
                "source_ref": '["session:1:1:0","session:1:1:2"]#h:abc123',
            }
        ],
        context=1,
    )

    assert result.is_error is False
    assert [item["id"] for item in result.output["messages"]] == [
        "session:1:1:0",
        "session:1:1:1",
        "session:1:1:2",
    ]
    assert [item["in_source_ref"] for item in result.output["messages"]] == [
        True,
        True,
        True,
    ]
    assert result.output["matched_count"] == 3


def test_search_messages_tool_returns_matches(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(SessionRef(user_id=1, session_id=1))
    session.add_message("user", "tool runtime")
    session.add_message("assistant", "copy that")
    manager.save(session)

    tool = SearchMessagesTool(store=manager.store)
    result = tool.execute(query="tool", user_id=1, session_id=1)

    assert result.is_error is False
    assert result.output["count"] == 1
    item = result.output["messages"][0]
    assert item["source_ref"] == "session:1:1:0"
    assert item["preview"] == "tool runtime"
    assert item["matched_terms"] == ["tool"]


def test_search_messages_tool_returns_preview_metadata(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(SessionRef(user_id=1, session_id=1))
    long_content = "\n".join(f"line-{index}" for index in range(55))
    session.add_message("user", f"benchmark recall\n{long_content}")
    session.add_message("assistant", "copy that")
    manager.save(session)

    tool = SearchMessagesTool(store=manager.store)
    result = tool.execute(query="benchmark recall", user_id=1, session_id=1, limit=1)

    assert result.is_error is False
    assert result.output["count"] == 1
    item = result.output["messages"][0]
    assert item["source_ref"] == "session:1:1:0"
    assert item["preview_line_count"] == 51
    assert item["total_line_count"] == 56
    assert item["truncated"] is True
    assert item["matched_terms"] == ["benchmark", "recall"]
    assert "call fetch_messages(source_ref)" in item["preview"]


def test_read_file_tool_reads_utf8_text(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello world", encoding="utf-8")

    tool = ReadFileTool()
    result = tool.execute(path=str(path))

    assert result.is_error is False
    assert result.output["content"] == "hello world"


