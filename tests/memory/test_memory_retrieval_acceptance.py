from __future__ import annotations

import asyncio
import importlib.util
from datetime import datetime

import amadeus.tools as public_tools
from amadeus.memory import (
    LongTermMemoryEngine,
    MemoryMemorizer,
    MemoryRetriever,
    MemoryStore,
    MemoryWriteRequest,
    PostResponseMemoryWorker,
)
from amadeus.prompts import build_behavior_rules_prompt
from amadeus.session.store import SessionManager
from amadeus.tools.defaults import FetchMessagesTool, SearchMessagesTool
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.recall_memory import RecallMemoryTool


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class FakeExtractor:
    async def extract(
        self,
        *,
        session_key: str,
        messages: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        return []


def _memory_fixture(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "用户正在学习 memory evidence")
    session.add_message("assistant", "原始消息必须通过 fetch_messages 回源")
    manager.save(session)
    store = MemoryStore(tmp_path / "long_term_memory.db")
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
                source_ref='["chat:1:0","chat:1:1"]#h:acceptance',
            )
        )
    )
    assert ingested.item_id is not None
    return manager, engine, ingested.item_id


def test_recall_evidence_can_fetch_original_messages(tmp_path):
    manager, engine, _ = _memory_fixture(tmp_path)

    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(query="memory evidence")
    )
    evidence = recalled.output["items"][0]["evidence"]
    fetched = FetchMessagesTool(store=manager.store).execute(evidence=evidence)

    assert [message["id"] for message in fetched.output["messages"]] == [
        "chat:1:0",
        "chat:1:1",
    ]
    assert [message["content"] for message in fetched.output["messages"]] == [
        "用户正在学习 memory evidence",
        "原始消息必须通过 fetch_messages 回源",
    ]


def test_search_source_ref_can_fetch_full_original_message(tmp_path):
    manager, _, _ = _memory_fixture(tmp_path)

    searched = SearchMessagesTool(store=manager.store).execute(
        query="memory evidence", session_key="chat:1"
    )
    source_ref = searched.output["messages"][0]["source_ref"]
    fetched = FetchMessagesTool(store=manager.store).execute(source_ref=source_ref)

    assert fetched.output["messages"][0]["id"] == "chat:1:0"
    assert fetched.output["messages"][0]["content"] == "用户正在学习 memory evidence"


def test_correction_fetches_source_then_forgets_memory_id_only(tmp_path):
    manager, engine, memory_id = _memory_fixture(tmp_path)
    recall_tool = RecallMemoryTool(memory_engine=engine)
    recalled = asyncio.run(recall_tool.execute(query="memory evidence"))

    fetched = FetchMessagesTool(store=manager.store).execute(
        evidence=recalled.output["items"][0]["evidence"]
    )
    forgotten = ForgetMemoryTool(memory_engine=engine).execute(ids=[memory_id])
    wrong_id = ForgetMemoryTool(memory_engine=engine).execute(ids=["chat:1:0"])

    assert fetched.output["count"] == 2
    assert forgotten.output["superseded_ids"] == [memory_id]
    assert wrong_id.output["missing_ids"] == ["chat:1:0"]
    still_fetchable = FetchMessagesTool(store=manager.store).execute(
        source_ref='["chat:1:0","chat:1:1"]'
    )
    assert still_fetchable.output["count"] == 2


def test_tool_descriptions_define_candidate_and_original_evidence_boundaries(tmp_path):
    manager = SessionManager(tmp_path)

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


def test_recall_output_preserves_complete_evidence_and_citation_contract(tmp_path):
    _, engine, memory_id = _memory_fixture(tmp_path)

    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(query="memory evidence")
    )
    evidence = recalled.output["items"][0]["evidence"][0]

    assert evidence["source_ref"] == '["chat:1:0","chat:1:1"]#h:acceptance'
    assert evidence["metadata"] == {}
    assert recalled.output["citation_required"] is True
    assert recalled.output["citation_format"] == "§cited:[id1,id2,...]§"
    assert recalled.output["cited_item_ids"] == [memory_id]
    assert "actually used" in recalled.output["citation_rule"]


def test_recall_memory_preserves_time_filter_trace_and_signals(tmp_path):
    store = MemoryStore(tmp_path / "long_term_memory.db")
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
                source_ref='["chat:1:0"]#h:early',
                happened_at="2026-06-01T09:00:00+08:00",
            )
        )
    )
    asyncio.run(
        engine.memorize(
            MemoryWriteRequest(
                summary="[2026-06-20 09:00] 用户完成 Phase 2 smoke。",
                memory_type="event",
                source_ref='["chat:1:1"]#h:late',
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
    assert recalled.output["items"][0]["source_ref"] == '["chat:1:1"]#h:late'
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
