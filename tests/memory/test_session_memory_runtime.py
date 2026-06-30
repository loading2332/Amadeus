from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from amadeus.events import EventBus, TurnCommitted
from amadeus.memory import (
    ConsolidateRequest,
    MarkdownMemoryMaintenance,
    MarkdownMemoryStore,
    MemoryOptimizer,
    RefreshRecentTurnsRequest,
)
from amadeus.session.store import SessionManager, fetch_messages, search_messages


class FakeProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: Any, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(content=self.responses.pop(0))


def test_session_store_persists_stable_message_ids_and_fetches_source_ref(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    assert session.messages[0]["id"] == "chat:1:0"
    assert session.messages[1]["id"] == "chat:1:1"

    rows = fetch_messages(manager.store, source_ref='["chat:1:0","chat:1:1"]')
    assert [row["content"] for row in rows] == ["hello", "hi"]

    result = search_messages(manager.store, "hell", session_key="chat:1")
    assert result["count"] == 1
    assert result["messages"][0]["id"] == "chat:1:0"


def test_turn_committed_refreshes_recent_turns_when_window_not_ready(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "not enough yet")
    session.add_message("assistant", "short reply")
    manager.save(session)

    store = MarkdownMemoryStore(tmp_path)
    bus = EventBus()
    MarkdownMemoryMaintenance(
        store=store,
        provider=FakeProvider(),
        model="fake",
        keep_count=6,
        session_manager=manager,
        event_bus=bus,
    )

    asyncio.run(
        bus.emit(
            TurnCommitted(
                session_key="chat:1",
                input_message="not enough yet",
                persisted_user_message="not enough yet",
                assistant_response="short reply",
            )
        )
    )

    recent = store.read_recent_context()
    assert "## Recent Turns" in recent
    assert "[user] not enough yet" in recent
    assert "[a-preview] short reply" in recent


def test_consolidation_writes_history_pending_recent_context_and_updates_cursor(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    for index in range(8):
        session.add_message("user", f"user fact {index}")
        session.add_message("assistant", f"assistant reply {index}")
    manager.save(session)

    provider = FakeProvider(
        """
        {
          "history_entries": [{"summary": "[2026-06-05 10:00] 用户确认正在迁移记忆链。"}],
          "pending_items": [{"tag": "identity", "content": "用户正在实现 Amadeus 记忆链。"}]
        }
        """,
        """
        {
          "active_topics": ["Amadeus 记忆链迁移"],
          "user_preferences": [],
          "follow_ups": ["继续验证 optimizer"],
          "avoidances": [],
          "ongoing_threads": []
        }
        """,
    )
    store = MarkdownMemoryStore(tmp_path)
    maintenance = MarkdownMemoryMaintenance(
        store=store,
        provider=provider,
        model="fake",
        keep_count=4,
        session_manager=manager,
    )

    result = asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))

    assert result.consolidated_count > 0
    assert "用户确认正在迁移记忆链" in store.read_history()
    assert "- [identity] 用户正在实现 Amadeus 记忆链。" in store.read_pending()
    assert "Amadeus 记忆链迁移" in store.read_recent_context()
    assert session.last_consolidated > 0


def test_append_once_deduplicates_same_source_ref(tmp_path):
    store = MarkdownMemoryStore(tmp_path)

    first = store.append_pending_once(
        "- [identity] first",
        source_ref='["chat:1:0"]',
        kind="pending_items",
    )
    second = store.append_pending_once(
        "- [identity] first",
        source_ref='["chat:1:0"]',
        kind="pending_items",
    )

    assert first is True
    assert second is False
    assert store.read_pending().count("- [identity] first") == 1


def test_optimizer_updates_memory_and_does_not_update_self(tmp_path):
    store = MarkdownMemoryStore(tmp_path)
    store.write_self("custom self")
    store.write_long_term("# 用户长期记忆\n\n## 用户事实\n- old")
    store.append_pending("- [preference] 用户偏好低风险迁移。")
    provider = FakeProvider("# 用户长期记忆\n\n## 用户偏好\n- 用户偏好低风险迁移。")
    optimizer = MemoryOptimizer(store=store, provider=provider, model="fake")

    asyncio.run(optimizer.optimize())

    assert "低风险迁移" in store.read_long_term()
    assert store.read_pending().strip() == ""
    assert store.read_self() == "custom self"
    assert not store.snapshot_path.exists()


def test_optimizer_rolls_back_pending_when_model_returns_empty(tmp_path):
    store = MarkdownMemoryStore(tmp_path)
    store.write_long_term("# 用户长期记忆")
    store.append_pending("- [identity] must survive")
    optimizer = MemoryOptimizer(store=store, provider=FakeProvider(""), model="fake")

    asyncio.run(optimizer.optimize())

    assert "must survive" in store.read_pending()
    assert not store.snapshot_path.exists()


def test_refresh_recent_turns_ignores_context_frame_and_tool_messages(tmp_path):
    store = MarkdownMemoryStore(tmp_path)
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "<system-reminder data-system-context-frame=\"true\">x</system-reminder>")
    session.add_message("tool", "tool result")
    session.add_message("user", "real user")
    session.add_message("assistant", "real assistant")
    manager.save(session)
    maintenance = MarkdownMemoryMaintenance(
        store=store,
        provider=FakeProvider(),
        model="fake",
        keep_count=8,
    )

    asyncio.run(maintenance.refresh_recent_turns(RefreshRecentTurnsRequest(session=session)))

    recent = store.read_recent_context()
    assert "real user" in recent
    assert "real assistant" in recent
    assert "tool result" not in recent
    assert "system-reminder" not in recent
