from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.events import EventBus, TurnCommitted
from amadeus.memory import (
    ConsolidateRequest,
    LongTermMemoryEngine,
    MarkdownMemoryMaintenance,
    MarkdownMemoryStore,
    MemoryMemorizer,
    MemoryOptimizer,
    MemoryRetriever,
    PostResponseMemoryWorker,
    RefreshRecentTurnsRequest,
)
from amadeus.memory.engine import MemoryRecallRequest
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.session.identity import SessionRef
from amadeus.session.store import (
    InMemorySessionStore,
    SessionManager,
    fetch_messages,
    search_messages,
)

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


class FakeProvider:
    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages: Any, **kwargs: Any) -> SimpleNamespace:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return SimpleNamespace(content=self.responses.pop(0))


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "面试项目" in text:
            return pad_embedding([1.0, 0.0, 0.0])
        if "中文解释" in text:
            return pad_embedding([0.0, 1.0, 0.0])
        if "phase 2" in lowered or "phase 2" in text:
            return pad_embedding([0.0, 0.0, 1.0])
        return pad_embedding([0.5, 0.5, 0.5])


class FakeExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        del session, messages
        return []


@pytest.fixture
def memory_store_db():
    db = clean_postgres()
    try:
        yield PostgresMemoryStore(user_id=1, db=db)
    finally:
        db.close()


@pytest.fixture
def markdown_store(tmp_path):
    db = clean_postgres()
    try:
        yield MarkdownMemoryStore(tmp_path, db=db)
    finally:
        db.close()


def test_session_store_persists_stable_message_ids_and_fetches_source_ref(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    assert session.messages[0]["id"] == "session:1:1:0"
    assert session.messages[1]["id"] == "session:1:1:1"

    rows = fetch_messages(manager.store, source_ref='["session:1:1:0","session:1:1:1"]')
    assert [row["content"] for row in rows] == ["hello", "hi"]

    result = search_messages(manager.store, "hell", user_id=1, session_id=1)
    assert result["count"] == 1
    assert result["messages"][0]["id"] == "session:1:1:0"


def test_in_memory_session_store_uses_canonical_message_ids_for_session_ref(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(SessionRef(user_id=2, session_id=4))
    session.add_message("user", "hello")
    session.add_message("assistant", "hi")
    manager.save(session)

    assert session.ref == SessionRef(user_id=2, session_id=4)
    assert [message["id"] for message in session.messages] == [
        "session:2:4:0",
        "session:2:4:1",
    ]

    rows = fetch_messages(manager.store, source_ref='["session:2:4:0","session:2:4:1"]')
    assert [row["content"] for row in rows] == ["hello", "hi"]


def test_turn_committed_refreshes_recent_turns_when_window_not_ready(
    tmp_path,
    markdown_store,
):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    session.add_message("user", "not enough yet")
    session.add_message("assistant", "short reply")
    manager.save(session)

    store = markdown_store
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
                session=_session(),
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


def test_consolidation_writes_history_pending_recent_context_and_updates_cursor(
    tmp_path,
    markdown_store,
):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
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
    store = markdown_store
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


def test_consolidation_ingests_pending_profile_preference_and_correction_into_memory_engine(
    tmp_path,
    markdown_store,
    memory_store_db,
):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    for index in range(8):
        session.add_message("user", f"user fact {index}")
        session.add_message("assistant", f"assistant reply {index}")
    manager.save(session)

    provider = FakeProvider(
        """
        {
          "history_entries": [{"summary": "[2026-06-05 10:00] 用户推进 Phase 2 记忆闭环。"}],
          "pending_items": [
            {"tag": "identity", "content": "用户正在把 Amadeus 打造成面试项目"},
            {"tag": "preference", "content": "用户偏好中文解释"},
            {"tag": "correction", "content": "更正：当前优先做 Memory Phase 2，而不是 Telegram"}
          ]
        }
        """,
        """
        {
          "active_topics": ["Phase 2 记忆闭环"],
          "user_preferences": ["中文解释"],
          "follow_ups": [],
          "avoidances": [],
          "ongoing_threads": []
        }
        """,
    )
    store_db = memory_store_db
    memorizer = MemoryMemorizer(store=store_db, embedding_provider=StableEmbeddingProvider())
    memory_engine = LongTermMemoryEngine(
        store=store_db,
        retriever=MemoryRetriever(store=store_db, embedding_provider=StableEmbeddingProvider()),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )
    store = markdown_store
    maintenance = MarkdownMemoryMaintenance(
        store=store,
        provider=provider,
        model="fake",
        keep_count=4,
        session_manager=manager,
        long_term_memory=memory_engine,
    )

    result = asyncio.run(maintenance.consolidate(ConsolidateRequest(session=session)))
    profile = asyncio.run(
        memory_engine.recall(MemoryRecallRequest(text="面试项目", memory_types=("profile",)))
    )
    preference = asyncio.run(
        memory_engine.recall(
            MemoryRecallRequest(text="中文解释", memory_types=("preference",))
        )
    )
    correction = asyncio.run(
        memory_engine.recall(MemoryRecallRequest(text="Memory Phase 2", memory_types=("fact",)))
    )

    assert result.trace["long_term_memory_ingest"]["attempted"] == 4
    assert profile.records[0].kind == "profile"
    assert profile.records[0].signals["extra"]["memory_tag"] == "identity"
    assert preference.records[0].kind == "preference"
    assert preference.records[0].signals["extra"]["memory_tag"] == "preference"
    assert correction.records[0].kind == "fact"
    assert correction.records[0].signals["extra"]["memory_tag"] == "correction"
    assert correction.records[0].signals["extra"]["lifecycle"] == "correction"


def test_append_once_deduplicates_same_source_ref(tmp_path, markdown_store):
    store = markdown_store

    first = store.append_pending_once(
        "- [identity] first",
        source_ref='["session:1:1:0"]',
        kind="pending_items",
    )
    second = store.append_pending_once(
        "- [identity] first",
        source_ref='["session:1:1:0"]',
        kind="pending_items",
    )

    assert first is True
    assert second is False
    assert store.read_pending().count("- [identity] first") == 1
    assert not (tmp_path / "memory" / "consolidation_writes.db").exists()


def test_optimizer_updates_memory_and_does_not_update_self(tmp_path, markdown_store):
    store = markdown_store
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


def test_optimizer_rolls_back_pending_when_model_returns_empty(tmp_path, markdown_store):
    store = markdown_store
    store.write_long_term("# 用户长期记忆")
    store.append_pending("- [identity] must survive")
    optimizer = MemoryOptimizer(store=store, provider=FakeProvider(""), model="fake")

    asyncio.run(optimizer.optimize())

    assert "must survive" in store.read_pending()
    assert not store.snapshot_path.exists()


def test_refresh_recent_turns_ignores_context_frame_and_tool_messages(
    tmp_path,
    markdown_store,
):
    store = markdown_store
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
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


