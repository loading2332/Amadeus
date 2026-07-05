from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime

import amadeus.tools as public_tools
import pytest
from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.prompts import build_behavior_rules_prompt
from amadeus.session.identity import SessionRef
from amadeus.session.store import InMemorySessionStore, SessionManager
from amadeus.tools.defaults import FetchMessagesTool, SearchMessagesTool
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.recall_memory import RecallMemoryTool

from tests.db.pgvector_helpers import pad_embedding
from tests.db.postgres_helpers import clean_postgres


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return pad_embedding([1.0, 0.0, 0.0])


class FakeExtractor:
    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        del session, messages
        return []


def _memory_fixture(tmp_path, store):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())
    session = manager.get_or_create(_session())
    session.add_message("user", "用户正在学习 memory evidence")
    session.add_message("assistant", "原始消息必须通过 fetch_messages 回源")
    manager.save(session)
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    engine = LongTermMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=StableEmbeddingProvider()),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )
    ingested = asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="用户正在学习 memory evidence",
                memory_type="event",
                source_ref='["session:1:1:0","session:1:1:1"]#h:acceptance',
            )
        )
    )
    assert ingested.item_id is not None
    return manager, engine, ingested.item_id


@pytest.fixture
def memory_store():
    db = clean_postgres()
    try:
        yield PostgresMemoryStore(user_id=1, db=db)
    finally:
        db.close()


def test_recall_evidence_can_fetch_original_messages(tmp_path, memory_store):
    manager, engine, _ = _memory_fixture(tmp_path, memory_store)

    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(query="memory evidence")
    )
    evidence = recalled.output["items"][0]["evidence"]
    fetched = FetchMessagesTool(store=manager.store).execute(evidence=evidence)

    assert [message["id"] for message in fetched.output["messages"]] == [
        "session:1:1:0",
        "session:1:1:1",
    ]
    assert [message["content"] for message in fetched.output["messages"]] == [
        "用户正在学习 memory evidence",
        "原始消息必须通过 fetch_messages 回源",
    ]


def test_search_source_ref_can_fetch_full_original_message(tmp_path, memory_store):
    manager, _, _ = _memory_fixture(tmp_path, memory_store)

    searched = SearchMessagesTool(store=manager.store).execute(
        query="memory evidence", user_id=1, session_id=1
    )
    source_ref = searched.output["messages"][0]["source_ref"]
    fetched = FetchMessagesTool(store=manager.store).execute(source_ref=source_ref)

    assert fetched.output["messages"][0]["id"] == "session:1:1:0"
    assert fetched.output["messages"][0]["content"] == "用户正在学习 memory evidence"


def test_correction_fetches_source_then_forgets_memory_id_only(tmp_path, memory_store):
    manager, engine, memory_id = _memory_fixture(tmp_path, memory_store)
    recall_tool = RecallMemoryTool(memory_engine=engine)
    recalled = asyncio.run(recall_tool.execute(query="memory evidence"))

    fetched = FetchMessagesTool(store=manager.store).execute(
        evidence=recalled.output["items"][0]["evidence"]
    )
    forgotten = ForgetMemoryTool(memory_engine=engine).execute(ids=[memory_id])
    wrong_id = ForgetMemoryTool(memory_engine=engine).execute(ids=["session:1:1:0"])

    assert fetched.output["count"] == 2
    assert forgotten.output["superseded_ids"] == [memory_id]
    assert wrong_id.output["missing_ids"] == ["session:1:1:0"]
    still_fetchable = FetchMessagesTool(store=manager.store).execute(
        source_ref='["session:1:1:0","session:1:1:1"]'
    )
    assert still_fetchable.output["count"] == 2


def test_tool_descriptions_define_candidate_and_original_evidence_boundaries(tmp_path):
    manager = SessionManager(tmp_path, store=InMemorySessionStore())

    assert "fetch_messages" in RecallMemoryTool(memory_engine=None).description
    assert "最终证据" in FetchMessagesTool(store=manager.store).description
    assert "fetch_messages" in SearchMessagesTool(store=manager.store).description


def test_behavior_rules_require_fetch_before_factual_use_and_current_memory_tools():
    prompt = build_behavior_rules_prompt()

    assert "recall_memory" in prompt
    assert "search_messages" in prompt
    assert "fetch_messages" in prompt
    assert "memorize" in prompt
    assert "forget_memory" in prompt
    assert "undo_memory_by_source" in prompt
    assert "correct_memory" not in prompt
    assert "message id" in prompt.lower()
    assert prompt.index("fetch_messages") < prompt.index("memorize")
    assert prompt.index("memorize") < prompt.index("forget_memory")


def test_public_tools_module_matches_bootstrap_memory_contract():
    assert hasattr(public_tools, "RecallMemoryTool")
    assert hasattr(public_tools, "ForgetMemoryTool")
    assert hasattr(public_tools, "MemorizeTool")
    assert hasattr(public_tools, "UndoMemoryBySourceTool")
    assert not hasattr(public_tools, "CorrectMemoryTool")
    assert "CorrectMemoryTool" not in public_tools.__all__


def test_correct_memory_module_is_not_publicly_importable():
    assert importlib.util.find_spec("amadeus.tools.correct_memory") is None


def test_recall_output_preserves_complete_evidence_and_citation_contract(tmp_path, memory_store):
    _, engine, memory_id = _memory_fixture(tmp_path, memory_store)

    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(query="memory evidence")
    )
    evidence = recalled.output["items"][0]["evidence"][0]

    assert evidence["source_ref"] == '["session:1:1:0","session:1:1:1"]#h:acceptance'
    assert evidence["metadata"] == {}
    assert recalled.output["citation_required"] is True
    assert recalled.output["citation_format"] == "§cited:[id1,id2,...]§"
    assert recalled.output["cited_item_ids"] == [memory_id]
    assert "actually used" in recalled.output["citation_rule"]


def test_recall_memory_preserves_time_filter_trace_and_signals(memory_store):
    store = memory_store
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    engine = LongTermMemoryEngine(
        store=store,
        retriever=MemoryRetriever(store=store, embedding_provider=StableEmbeddingProvider()),
        memorizer=memorizer,
        worker=PostResponseMemoryWorker(memorizer=memorizer, extractor=FakeExtractor()),
    )
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-01 09:00] 用户开始实现 Phase 2。",
                memory_type="event",
                source_ref='["session:1:1:0"]#h:early',
                happened_at="2026-06-01T09:00:00+08:00",
            )
        )
    )
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-20 09:00] 用户完成 Phase 2 smoke。",
                memory_type="event",
                source_ref='["session:1:1:1"]#h:late',
                happened_at="2026-06-20T09:00:00+08:00",
            )
        )
    )

    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(
            query="Phase 2",
            time_start="2026-06-20T00:30:00+00:00",
            time_end=datetime.fromisoformat("2026-06-20T01:30:00+00:00"),
        )
    )

    assert recalled.output["count"] == 1
    assert recalled.output["items"][0]["source_ref"] == '["session:1:1:1"]#h:late'
    assert recalled.output["trace"]["time_filters"] == {
        "start": "2026-06-20T00:30:00",
        "end": "2026-06-20T01:30:00",
    }
    assert recalled.output["trace"]["records"][0]["id"] == recalled.output["items"][0]["id"]
    assert recalled.output["trace"]["records"][0]["signals"]["lanes"] == ["vector", "lexical"]
    assert recalled.output["trace"]["records"][0]["signals"]["vector_score"] > 0
    signals = recalled.output["trace"]["records"][0]["signals"]
    assert signals["final_vector_score"] >= signals["vector_score"] * 0.8
    assert signals["hotness_alpha"] == 0.2
    assert signals["hotness_score"] > 0
    assert signals["hotness_recency"] > 0
    assert signals["emotional_weight"] == 0
    assert signals["hotness_updated_at"]


