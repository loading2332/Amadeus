from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.app.bootstrap import build_passive_app
from amadeus.evaluation.cases import (
    MemoryQualityCase,
    MemoryQualityCaseExpect,
    SeedLongTermMemory,
    SeedSessionMessage,
)
from amadeus.evaluation.memory_quality_runner import (
    run_memory_quality_case,
    run_memory_quality_evaluation,
)
from amadeus.session.identity import SessionRef
from tests.db.pgvector_helpers import pad_embedding


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "中文" in text:
            return pad_embedding([1.0, 0.0, 0.0])
        if "英文" in text or "english" in lowered:
            return pad_embedding([0.0, 1.0, 0.0])
        return pad_embedding([0.5, 0.5, 0.5])


class FakeCompletions:
    async def create(self, **kwargs: Any):
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


class RuleBasedExtractor:
    def __init__(self, *, provider: Any, model: str) -> None:
        self.provider = provider
        self.model = model

    async def extract(
        self,
        *,
        session: SessionRef,
        messages: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        del session
        transcript = "\n".join(str(message.get("content") or "") for message in messages)
        if "短期在线" in transcript:
            return []
        if "中文" in transcript:
            source_message_id = str(messages[0].get("id") or "session:1:1:0")
            return [
                {
                    "summary": "用户默认偏好中文回复。",
                    "memory_type": "preference",
                    "source_ref": f'["{source_message_id}"]#h:new',
                }
            ]
        return []


def _env_path(tmp_path: Path) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                "OPENAI_EMBEDDING_MODEL=fake-embedding",
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def _runtime_only_env_path(tmp_path: Path) -> Path:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
            ]
        ),
        encoding="utf-8",
    )
    return env_path


def _quality_case_file(tmp_path: Path) -> Path:
    case_file = tmp_path / "memory_quality.yaml"
    case_file.write_text(
        "\n".join(
            [
                "cases:",
                "  - id: quality-runtime",
                "    mode: post_response_write",
                "    title: quality write",
                "    seed_session_messages: []",
                "    seed_long_term_memories: []",
                "    turn_messages:",
                "      - role: user",
                "        content: 以后默认用中文回复",
                "    input: {}",
                "    expect:",
                "      write_count_min: 1",
                "      judge_rubric: should write a Chinese preference memory",
            ]
        ),
        encoding="utf-8",
    )
    return case_file


def test_run_memory_quality_case_returns_post_response_write_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.LLMMemoryExtractor",
        RuleBasedExtractor,
    )
    case = MemoryQualityCase(
        id="write-case",
        mode="post_response_write",
        title="post response write",
        seed_session_messages=(),
        seed_long_term_memories=(),
        turn_messages=(
            SeedSessionMessage(role="user", content="以后默认用中文回复。"),
        ),
        input_payload={},
        expect=MemoryQualityCaseExpect(
            write_count_min=1,
            written_summaries_contains=("中文",),
            active_summaries_contains=("中文",),
            memory_types_contains=("preference",),
            judge_rubric="memory should capture the Chinese preference",
        ),
    )

    result = run_memory_quality_case(
        case,
        env_path=_env_path(tmp_path),
        app_builder=build_passive_app,
        client=FakeClient(),
    )

    assert result["assistant_response"] == ""
    assert result["write_trace"]["written_count"] == 1
    assert isinstance(result["active_memories"], list)
    assert isinstance(result["superseded_memories"], list)
    assert isinstance(result["written_memories"], list)
    assert isinstance(result["recall_items"], list)
    assert result["error"] is None


def test_run_memory_quality_case_returns_write_then_recall_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.LLMMemoryExtractor",
        RuleBasedExtractor,
    )
    case = MemoryQualityCase(
        id="write-recall-case",
        mode="write_then_recall",
        title="write then recall",
        seed_session_messages=(),
        seed_long_term_memories=(
            SeedLongTermMemory(
                summary="用户以前偏好英文回复。",
                memory_type="preference",
                source_ref='["session:1:1:10"]#h:old',
            ),
        ),
        turn_messages=(
            SeedSessionMessage(role="user", content="以后默认用中文回复。"),
        ),
        input_payload={"recall_query": "中文回复"},
        expect=MemoryQualityCaseExpect(
            write_count_min=1,
            written_summaries_contains=("中文",),
            active_summaries_contains=("中文",),
            source_ref_required=True,
            fetched_messages_contains=("中文",),
            judge_rubric="memory should capture the Chinese preference",
        ),
    )

    result = run_memory_quality_case(
        case,
        env_path=_env_path(tmp_path),
        app_builder=build_passive_app,
        client=FakeClient(),
    )

    assert result["write_trace"]["written_count"] == 1
    assert result["recall_items"]
    assert result["source_refs"]
    assert result["fetched_messages"]
    assert result["error"] is None


def test_run_memory_quality_evaluation_requires_long_term_memory_enabled(
    tmp_path: Path,
):
    with pytest.raises(
        ValueError,
        match="AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
    ):
        run_memory_quality_evaluation(
            env_path=_runtime_only_env_path(tmp_path),
            case_file=_quality_case_file(tmp_path),
            dataset_name="memory-quality",
            experiment_prefix="memory-quality",
        )
