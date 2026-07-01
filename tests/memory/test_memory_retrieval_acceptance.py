from __future__ import annotations

import asyncio
from datetime import datetime

from amadeus.memory.engine import MemoryIngestRequest
from amadeus.memory.vector import VectorMemoryEngine, VectorMemoryStore
from amadeus.prompts import build_behavior_rules_prompt
from amadeus.tools.correct_memory import CorrectMemoryTool
from amadeus.session.store import SessionManager
from amadeus.tools.defaults import FetchMessagesTool, SearchMessagesTool
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.recall_memory import RecallMemoryTool


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def _memory_fixture(tmp_path):
    manager = SessionManager(tmp_path)
    session = manager.get_or_create("chat:1")
    session.add_message("user", "用户正在学习 memory evidence")
    session.add_message("assistant", "原始消息必须通过 fetch_messages 回源")
    manager.save(session)
    engine = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=StableEmbeddingProvider(),
    )
    ingested = asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="用户正在学习 memory evidence",
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


def test_correct_memory_tool_supersedes_old_item_and_creates_replacement(tmp_path):
    manager, engine, memory_id = _memory_fixture(tmp_path)
    tool = CorrectMemoryTool(memory_engine=engine)

    fetched = FetchMessagesTool(store=manager.store).execute(
        source_ref='["chat:1:0","chat:1:1"]#h:acceptance'
    )
    assert fetched.output["count"] == 2

    corrected = asyncio.run(
        tool.execute(
            memory_id=memory_id,
            corrected_summary="用户正在实现完整的 Phase 2 memory closure",
            source_ref='["chat:1:0","chat:1:1"]#h:acceptance',
            kind="event",
        )
    )
    recalled = asyncio.run(
        RecallMemoryTool(memory_engine=engine).execute(query="Phase 2 memory closure")
    )

    assert corrected.is_error is False
    assert corrected.output["superseded_id"] == memory_id
    assert corrected.output["replacement_id"] is not None
    assert corrected.output["replacement_id"] != memory_id
    assert recalled.output["items"][0]["id"] == corrected.output["replacement_id"]


def test_correct_memory_tool_rejects_source_ref_mismatch(tmp_path):
    _, engine, memory_id = _memory_fixture(tmp_path)
    tool = CorrectMemoryTool(memory_engine=engine)

    result = asyncio.run(
        tool.execute(
            memory_id=memory_id,
            corrected_summary="错误修正",
            source_ref='["chat:999:0"]#h:wrong',
            kind="event",
        )
    )

    assert result.is_error is True
    assert result.output["error"] == "source_ref does not match target memory"


def test_tool_descriptions_define_candidate_and_original_evidence_boundaries(tmp_path):
    manager = SessionManager(tmp_path)

    assert "fetch_messages" in RecallMemoryTool(memory_engine=None).description
    assert "fetch_messages" in CorrectMemoryTool(memory_engine=None).description
    assert "最终证据" in FetchMessagesTool(store=manager.store).description
    assert "fetch_messages" in SearchMessagesTool(store=manager.store).description


def test_behavior_rules_require_fetch_before_factual_use_and_correction_or_forget():
    prompt = build_behavior_rules_prompt()

    assert "recall_memory" in prompt
    assert "search_messages" in prompt
    assert "fetch_messages" in prompt
    assert "correct_memory" in prompt
    assert "forget_memory" in prompt
    assert "message id" in prompt.lower()
    assert prompt.index("fetch_messages") < prompt.index("correct_memory")
    assert prompt.index("correct_memory") < prompt.index("forget_memory")


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
    engine = VectorMemoryEngine(
        store=VectorMemoryStore(tmp_path / "vector_memory.db"),
        embedding_provider=StableEmbeddingProvider(),
    )
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-01 09:00] 用户开始实现 Phase 2。",
                kind="event",
                source_ref='["chat:1:0"]#h:early',
                happened_at="2026-06-01T09:00:00+08:00",
            )
        )
    )
    asyncio.run(
        engine.ingest(
            MemoryIngestRequest(
                summary="[2026-06-20 09:00] 用户完成 Phase 2 smoke。",
                kind="event",
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
