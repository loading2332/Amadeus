from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from amadeus.evaluation.embedding_cache import FileEmbeddingCacheProvider
from amadeus.evaluation.memory_retrieval_benchmark import (
    FixedRetrievalHypotheses,
    MemoryRetrievalBenchmark,
    RetrievalBenchmarkCorpus,
    RetrievalBenchmarkMemory,
    RetrievalBenchmarkQuery,
    RetrievalJudgment,
)
from amadeus.evaluation.memory_retrieval_cli import _populate_cache_and_close


class CountingEmbeddingProvider:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, 0.0, 0.0]


class LoopBoundEmbeddingProvider(CountingEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.embed_loop: asyncio.AbstractEventLoop | None = None
        self.closed = False

    async def embed(self, text: str) -> list[float]:
        self.embed_loop = asyncio.get_running_loop()
        return await super().embed(text)

    async def aclose(self) -> None:
        assert asyncio.get_running_loop() is self.embed_loop
        self.closed = True


def test_embedding_cache_writes_hashed_keys_and_replays_read_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "embeddings.json"
    provider = CountingEmbeddingProvider()
    writable = FileEmbeddingCacheProvider(
        path,
        identity="fake:model",
        dimensions=3,
        input_hash="inputs-v1",
        underlying=provider,
        allow_misses=True,
    )

    first = asyncio.run(writable.embed("用户偏好中文"))
    second = asyncio.run(writable.embed("用户偏好中文"))
    writable.flush()

    assert first == second == [1.0, 0.0, 0.0]
    assert provider.calls == ["用户偏好中文"]
    assert "用户偏好中文" not in path.read_text(encoding="utf-8")
    frozen = FileEmbeddingCacheProvider(
        path,
        identity="fake:model",
        dimensions=3,
        input_hash="inputs-v1",
    )
    assert asyncio.run(frozen.embed("用户偏好中文")) == [1.0, 0.0, 0.0]
    assert frozen.fingerprint == writable.fingerprint


def test_frozen_embedding_cache_rejects_miss(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "identity": "fake:model",
                "dimensions": 3,
                "input_hash": "inputs-v1",
                "vectors": {},
            }
        ),
        encoding="utf-8",
    )
    frozen = FileEmbeddingCacheProvider(
        path,
        identity="fake:model",
        dimensions=3,
        input_hash="inputs-v1",
    )

    with pytest.raises(ValueError, match="cache miss"):
        asyncio.run(frozen.embed("missing"))


def test_embedding_cache_rejects_identity_or_input_drift(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "identity": "fake:model-v1",
                "dimensions": 3,
                "input_hash": "inputs-v1",
                "vectors": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        FileEmbeddingCacheProvider(
            path,
            identity="fake:model-v2",
            dimensions=3,
            input_hash="inputs-v1",
        )
    with pytest.raises(ValueError, match="input_hash mismatch"):
        FileEmbeddingCacheProvider(
            path,
            identity="fake:model-v1",
            dimensions=3,
            input_hash="inputs-v2",
        )


def test_embedding_cache_rejects_non_numeric_vector_values(tmp_path: Path) -> None:
    path = tmp_path / "embeddings.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "identity": "fake:model",
                "dimensions": 3,
                "input_hash": "inputs-v1",
                "vectors": {"bad": [True, 0.0, 0.0]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="only numbers"):
        FileEmbeddingCacheProvider(
            path,
            identity="fake:model",
            dimensions=3,
            input_hash="inputs-v1",
        )


def test_cli_populates_and_closes_provider_in_the_same_event_loop(
    tmp_path: Path,
) -> None:
    memory = RetrievalBenchmarkMemory(
        key="memory",
        summary="用户偏好中文。",
        memory_type="preference",
        updated_at="2026-07-01T00:00:00+00:00",
    )
    query = RetrievalBenchmarkQuery(
        id="query",
        family_id="family",
        corpus_id="corpus",
        split="development",
        review_status="approved",
        review_batch=1,
        product_scenario="personal_assistant",
        memory_capability="cross_session",
        language="zh",
        raw_query="我偏好什么语言？",
        fixed_hypotheses=FixedRetrievalHypotheses(),
        strata=("zh",),
        judgments=(RetrievalJudgment("memory", 3, False, "直接答案"),),
        required_memory_keys=("memory",),
    )
    benchmark = MemoryRetrievalBenchmark(
        version="loop-test",
        review_status="approved",
        corpora=(RetrievalBenchmarkCorpus("corpus", (memory,)),),
        queries=(query,),
    )
    provider = LoopBoundEmbeddingProvider()
    cache = FileEmbeddingCacheProvider(
        tmp_path / "cache.json",
        identity="fake:model",
        dimensions=3,
        input_hash="inputs-v1",
        underlying=provider,
        allow_misses=True,
    )

    fingerprint = asyncio.run(
        _populate_cache_and_close(
            benchmark=benchmark,
            cache=cache,
            provider=provider,
        )
    )

    assert fingerprint == cache.fingerprint
    assert provider.closed is True
