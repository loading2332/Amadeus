from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from amadeus.app.bootstrap import build_passive_app
from amadeus.evaluation.cases import (
    MemoryRecallCase,
    MemoryRecallCaseExpect,
    SeedLongTermMemory,
    SeedSessionMessage,
)
from amadeus.evaluation.memory_recall_runner import (
    run_memory_recall_case,
    run_memory_recall_evaluation,
)


class StableEmbeddingProvider:
    async def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        if "中文" in text:
            return [1.0, 0.0, 0.0]
        if "面试项目" in text or "interview" in lowered:
            return [0.0, 1.0, 0.0]
        if "evaluation" in lowered:
            return [0.0, 0.0, 1.0]
        return [0.5, 0.5, 0.5]


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any):
        self.calls.append(kwargs)
        prompt_text = "\n".join(str(message.get("content", "")) for message in kwargs["messages"])
        if "中文" in prompt_text:
            content = "之后默认用中文回复。"
        elif "Evaluation" in prompt_text:
            content = "Memory Phase 3 先做 Evaluation。"
        else:
            content = "assistant reply"
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage={},
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


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


def _case_file(tmp_path: Path) -> Path:
    case_file = tmp_path / "memory_recall.yaml"
    case_file.write_text(
        "\n".join(
            [
                "- id: runtime-case",
                "  mode: runtime_turn",
                "  title: runtime turn",
                "  seed_session_messages:",
                "    - role: user",
                "      content: 以后默认用中文回答。",
                "  seed_long_term_memories:",
                "    - summary: 用户偏好中文回答。",
                "      memory_type: preference",
                "      source_message_indexes: [0]",
                "  input:",
                "    user_message: 之后默认用什么语言回复我？",
                "  expect:",
                "    memory_intent: context",
            ]
        ),
        encoding="utf-8",
    )
    return case_file


def test_run_memory_recall_case_returns_runtime_turn_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    case = MemoryRecallCase(
        id="runtime-case",
        mode="runtime_turn",
        title="runtime turn",
        seed_session_messages=(
            SeedSessionMessage(role="user", content="以后默认用中文回答。"),
        ),
        seed_long_term_memories=(
            SeedLongTermMemory(
                summary="用户偏好中文回答。",
                memory_type="preference",
                source_message_indexes=(0,),
            ),
        ),
        input_payload={"user_message": "之后默认用什么语言回复我？"},
        expect=MemoryRecallCaseExpect(
            memory_intent="context",
            candidate_count_min=1,
            injected_count_min=1,
            answer_keywords_any=("中文",),
            judge_rubric="say chinese",
        ),
    )

    result = run_memory_recall_case(
        case,
        env_path=_env_path(tmp_path),
        app_builder=build_passive_app,
        client=FakeClient(),
    )

    assert result["assistant_response"]
    assert result["memory_trace"]["intent"] == "context"
    assert isinstance(result["tool_chain"], list)
    assert isinstance(result["recall_items"], list)
    assert isinstance(result["fetched_messages"], list)
    assert isinstance(result["source_refs"], list)
    assert result["error"] is None


def test_run_memory_recall_case_returns_recall_tool_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    case = MemoryRecallCase(
        id="recall-case",
        mode="recall_tool",
        title="recall tool",
        seed_session_messages=(
            SeedSessionMessage(role="user", content="我正在把 Amadeus 做成面试项目。"),
        ),
        seed_long_term_memories=(
            SeedLongTermMemory(
                summary="用户正在把 Amadeus 做成面试项目。",
                memory_type="profile",
                source_message_indexes=(0,),
            ),
        ),
        input_payload={"recall_query": "面试项目"},
        expect=MemoryRecallCaseExpect(
            source_ref_required=True,
            fetched_messages_contains=("面试项目",),
            answer_keywords_any=("面试项目",),
            judge_rubric="mention interview project",
        ),
    )

    result = run_memory_recall_case(
        case,
        env_path=_env_path(tmp_path),
        app_builder=build_passive_app,
        client=FakeClient(),
    )

    assert result["assistant_response"] == ""
    assert result["recall_items"]
    assert result["source_refs"]
    assert result["fetched_messages"]
    assert result["error"] is None


def test_run_memory_recall_evaluation_requires_long_term_memory_enabled(tmp_path: Path):
    with pytest.raises(
        ValueError,
        match="AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
    ):
        run_memory_recall_evaluation(
            env_path=_runtime_only_env_path(tmp_path),
            case_file=_case_file(tmp_path),
            dataset_name="memory-recall",
            experiment_prefix="memory-recall",
        )
