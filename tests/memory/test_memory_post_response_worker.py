from __future__ import annotations

import asyncio

from amadeus.memory.engine import MemoryWriteRequest
from amadeus.memory.memorizer import MemoryMemorizer
from amadeus.memory.post_response_worker import (
    LLMMemoryDecisionProvider,
    MemoryDecision,
    PostResponseMemoryWorker,
)
from amadeus.memory.store import MemoryStore


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        if "中文" in text:
            return [1.0, 0.0, 0.0]
        return [0.8, 0.2, 0.0]


class FakeExtractor:
    async def extract(self, *, session_key: str, messages: list[dict[str, str]]):
        return [
            {
                "summary": "用户明确要求长期记住：默认用中文",
                "memory_type": "preference",
                "source_ref": '["chat:1:0"]#h:extract',
            }
        ]


class CandidateExtractor:
    def __init__(self, candidates):
        self.candidates = candidates

    async def extract(self, *, session_key: str, messages: list[dict[str, str]]):
        return list(self.candidates)


class StaticDecisionProvider:
    def __init__(self, decision: MemoryDecision):
        self.decision = decision

    async def decide(self, candidate):
        del candidate
        return self.decision


class FakeDecisionResponse:
    def __init__(self, content: str):
        self.content = content


class FakeDecisionLLM:
    def __init__(self, *, target_id: str):
        self.target_id = target_id
        self.prompts: list[str] = []

    async def chat(self, messages, **kwargs):
        del kwargs
        self.prompts.append(str(messages[0]["content"]))
        return FakeDecisionResponse(
            f'{{"decision":"replace","reason":"user correction","target_ids":["{self.target_id}"]}}'
        )


def test_post_response_worker_writes_implicit_memory_once(tmp_path) -> None:
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(
            store=MemoryStore(tmp_path / "long_term_memory.db"),
            embedding_provider=StableEmbeddingProvider(),
        ),
        extractor=FakeExtractor(),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[{"role": "user", "content": "以后默认中文回复"}],
            explicit_memory_ids=[],
        )
    )

    assert result["written_count"] == 1
    assert result["skipped_duplicates"] == 0
    assert result["written_ids"]


def test_post_response_worker_builds_source_ref_from_user_message_id(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(
            store=store,
            embedding_provider=StableEmbeddingProvider(),
        ),
        extractor=CandidateExtractor(
            [
                {
                    "summary": "用户默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_message_ids": ["chat:1:0"],
                    "extra": {"category": "response_language"},
                }
            ]
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[
                {"id": "chat:1:0", "role": "user", "content": "以后默认中文回复"},
                {"id": "chat:1:1", "role": "assistant", "content": "好的"},
            ],
            explicit_memory_ids=[],
        )
    )

    item = store.get_items_by_ids(result["written_ids"])[0]
    assert result["written_count"] == 1
    assert item["source_ref"].startswith('["chat:1:0"]')
    assert item["extra"]["category"] == "response_language"


def test_post_response_worker_rejects_assistant_only_evidence(tmp_path) -> None:
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(
            store=MemoryStore(tmp_path / "long_term_memory.db"),
            embedding_provider=StableEmbeddingProvider(),
        ),
        extractor=CandidateExtractor(
            [
                {
                    "summary": "用户默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_message_ids": ["chat:1:1"],
                }
            ]
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[
                {"id": "chat:1:0", "role": "user", "content": "你好"},
                {"id": "chat:1:1", "role": "assistant", "content": "用户偏好中文"},
            ],
            explicit_memory_ids=[],
        )
    )

    assert result["written_count"] == 0
    assert result["candidate_decisions"][0]["action"] == "skip"
    assert result["candidate_decisions"][0]["reason"] == "source_ref_must_resolve_to_user_message"


def test_post_response_worker_replaces_conflicting_preference(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    old = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户以前默认偏好英文回复。",
                memory_type="preference",
                source_ref='["seed:0"]#h:old',
                extra={"category": "response_language"},
            )
        )
    )
    worker = PostResponseMemoryWorker(
        memorizer=memorizer,
        extractor=CandidateExtractor(
            [
                {
                    "summary": "用户现在默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_message_ids": ["chat:1:0"],
                    "extra": {"category": "response_language"},
                }
            ]
        ),
        decision_provider=StaticDecisionProvider(
            MemoryDecision(
                action="replace",
                reason="same_preference_updated",
                target_ids=[str(old.item_id)],
            )
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[
                {"id": "chat:1:0", "role": "user", "content": "我现在改了，以后默认中文回复。"}
            ],
            explicit_memory_ids=[],
        )
    )

    old_item = store.get_item_by_id(str(old.item_id))
    active = store.list_active_items(memory_types=("preference",))
    assert result["written_count"] == 1
    assert result["candidate_decisions"][0]["action"] == "replace"
    assert old_item is not None
    assert old_item["status"] == "superseded"
    assert any("中文" in item["summary"] for item in active)


def test_llm_decision_provider_replaces_similar_memory_from_llm_json(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    old = asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户以前默认偏好英文回复。",
                memory_type="preference",
                source_ref='["seed:0"]#h:old',
                extra={},
            )
        )
    )
    provider = FakeDecisionLLM(target_id=str(old.item_id))
    worker = PostResponseMemoryWorker(
        memorizer=memorizer,
        extractor=CandidateExtractor(
            [
                {
                    "summary": "用户现在默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_message_ids": ["chat:1:0"],
                }
            ]
        ),
        decision_provider=LLMMemoryDecisionProvider(
            memorizer=memorizer,
            provider=provider,
            model="fake-model",
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[
                {"id": "chat:1:0", "role": "user", "content": "我现在改了，以后默认中文回复。"}
            ],
            explicit_memory_ids=[],
        )
    )

    old_item = store.get_item_by_id(str(old.item_id))
    assert provider.prompts
    assert "已有相似记忆" in provider.prompts[0]
    assert str(old.item_id) in provider.prompts[0]
    assert result["candidate_decisions"][0]["reason"] == "user correction"
    assert old_item is not None
    assert old_item["status"] == "superseded"


def test_post_response_worker_skips_duplicate_candidate(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    memorizer = MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider())
    asyncio.run(
        memorizer.memorize(
            MemoryWriteRequest(
                summary="用户默认偏好中文回复。",
                memory_type="preference",
                source_ref='["seed:0"]#h:old',
                extra={"category": "response_language"},
            )
        )
    )
    worker = PostResponseMemoryWorker(
        memorizer=memorizer,
        extractor=CandidateExtractor(
            [
                {
                    "summary": "用户默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_message_ids": ["chat:1:0"],
                    "extra": {"category": "response_language"},
                }
            ]
        ),
        decision_provider=StaticDecisionProvider(
            MemoryDecision(
                action="skip",
                reason="duplicate_active_memory",
                target_ids=[],
            )
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[{"id": "chat:1:0", "role": "user", "content": "还是默认中文回复。"}],
            explicit_memory_ids=[],
        )
    )

    assert result["written_count"] == 0
    assert result["skipped_duplicates"] == 1
    assert result["candidate_decisions"][0]["action"] == "skip"


def test_post_response_worker_writes_explicit_procedure(tmp_path) -> None:
    store = MemoryStore(tmp_path / "long_term_memory.db")
    worker = PostResponseMemoryWorker(
        memorizer=MemoryMemorizer(store=store, embedding_provider=StableEmbeddingProvider()),
        extractor=CandidateExtractor(
            [
                {
                    "summary": "以后修改代码前先写测试。",
                    "memory_type": "procedure",
                    "source_message_ids": ["chat:1:0"],
                    "extra": {"category": "development_rule"},
                }
            ]
        ),
    )

    result = asyncio.run(
        worker.run(
            session_key="chat:1",
            messages=[{"id": "chat:1:0", "role": "user", "content": "以后修改代码前先写测试。"}],
            explicit_memory_ids=[],
        )
    )

    item = store.get_items_by_ids(result["written_ids"])[0]
    assert result["written_count"] == 1
    assert item["memory_type"] == "procedure"
