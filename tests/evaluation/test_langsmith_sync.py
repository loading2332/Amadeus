from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from amadeus.evaluation.cases import (
    MemoryQualityCase,
    MemoryQualityCaseExpect,
    MemoryRecallCase,
    MemoryRecallCaseExpect,
    SeedLongTermMemory,
    SeedSessionMessage,
)
from amadeus.evaluation.langsmith_sync import (
    build_langsmith_client,
    sync_memory_quality_dataset,
    sync_memory_recall_dataset,
)


class FakeLangSmithClient:
    def __init__(self) -> None:
        self.datasets: dict[str, SimpleNamespace] = {}
        self.examples: dict[str, SimpleNamespace] = {}
        self.created_datasets = 0
        self.created_examples = 0
        self.updated_examples = 0
        self.deleted_examples = 0

    def list_datasets(self, *, dataset_name=None, **kwargs):
        if dataset_name and dataset_name in self.datasets:
            yield self.datasets[dataset_name]
            return
        yield from ()

    def create_dataset(self, dataset_name: str, **kwargs):
        self.created_datasets += 1
        dataset = SimpleNamespace(id=f"ds-{self.created_datasets}", name=dataset_name)
        self.datasets[dataset_name] = dataset
        return dataset

    def list_examples(self, *, dataset_id=None, **kwargs):
        for example in self.examples.values():
            if example.dataset_id == dataset_id:
                yield example

    def create_example(self, *, dataset_id=None, inputs=None, outputs=None, metadata=None, **kwargs):
        self.created_examples += 1
        case_id = metadata["case_id"]
        example = SimpleNamespace(
            id=f"ex-{self.created_examples}",
            dataset_id=dataset_id,
            inputs=inputs,
            outputs=outputs,
            metadata=dict(metadata or {}),
        )
        self.examples[case_id] = example
        return example

    def update_example(self, example_id, *, inputs=None, outputs=None, metadata=None, **kwargs):
        self.updated_examples += 1
        for case_id, example in self.examples.items():
            if example.id == example_id:
                self.examples[case_id] = SimpleNamespace(
                    id=example.id,
                    dataset_id=example.dataset_id,
                    inputs=inputs,
                    outputs=outputs,
                    metadata=dict(metadata or {}),
                )
                return {"id": example_id}
        raise KeyError(example_id)

    def delete_example(self, example_id, **kwargs):
        self.deleted_examples += 1
        for case_id, example in list(self.examples.items()):
            if example.id == example_id:
                del self.examples[case_id]
                return {"id": example_id}
        raise KeyError(example_id)


def _sample_case() -> MemoryRecallCase:
    return MemoryRecallCase(
        id="case-1",
        mode="recall_tool",
        title="sample",
        seed_session_messages=(SeedSessionMessage(role="user", content="hello"),),
        seed_long_term_memories=(
            SeedLongTermMemory(
                summary="remember hello",
                memory_type="fact",
                source_message_indexes=(0,),
            ),
        ),
        input_payload={"recall_query": "hello"},
        expect=MemoryRecallCaseExpect(
            source_ref_required=True,
            fetched_messages_contains=("hello",),
            answer_keywords_any=("hello",),
            judge_rubric="mention hello",
        ),
    )


def _sample_quality_case() -> MemoryQualityCase:
    return MemoryQualityCase(
        id="quality-1",
        mode="post_response_write",
        title="sample quality",
        seed_session_messages=(),
        seed_long_term_memories=(),
        turn_messages=(SeedSessionMessage(role="user", content="以后默认用中文回复"),),
        input_payload={},
        expect=MemoryQualityCaseExpect(
            write_count_min=1,
            written_summaries_contains=("中文",),
            judge_rubric="write a Chinese preference memory",
        ),
    )


def test_sync_memory_recall_dataset_is_idempotent_by_case_id():
    client = FakeLangSmithClient()
    cases = [_sample_case()]

    first = sync_memory_recall_dataset(cases, dataset_name="memory-recall", client=client)
    second = sync_memory_recall_dataset(cases, dataset_name="memory-recall", client=client)

    assert first.dataset_name == "memory-recall"
    assert second.dataset_name == "memory-recall"
    assert client.created_datasets == 1
    assert len(client.examples) == 1
    assert client.created_examples == 1
    assert client.updated_examples == 1


class CapturingLangSmithClient:
    def __init__(self, **kwargs) -> None:
        self.kwargs = dict(kwargs)


def test_build_langsmith_client_reads_api_key_from_env_file(
    tmp_path: Path,
    monkeypatch,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "LANGSMITH_API_KEY=lsv2_pt_test_key",
                "LANGSMITH_TRACING=true",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGSMITH_ENDPOINT", raising=False)

    client = build_langsmith_client(
        env_path=env_path,
        client_class=CapturingLangSmithClient,
    )

    assert isinstance(client, CapturingLangSmithClient)
    assert client.kwargs["api_key"] == "lsv2_pt_test_key"


def test_sync_memory_quality_dataset_prunes_stale_examples():
    client = FakeLangSmithClient()
    stale_case = _sample_quality_case()
    sync_memory_quality_dataset(
        [stale_case],
        dataset_name="memory-quality",
        client=client,
    )

    fresh_case = MemoryQualityCase(
        id="quality-2",
        mode="post_response_write",
        title="fresh quality",
        seed_session_messages=(),
        seed_long_term_memories=(),
        turn_messages=(SeedSessionMessage(role="user", content="记住我偏好中文"),),
        input_payload={},
        expect=MemoryQualityCaseExpect(
            write_count_min=1,
            written_summaries_contains=("中文",),
            judge_rubric="write a Chinese preference memory",
        ),
    )

    result = sync_memory_quality_dataset(
        [fresh_case],
        dataset_name="memory-quality",
        client=client,
    )

    assert result.dataset_name == "memory-quality"
    assert client.deleted_examples == 1
    assert set(client.examples) == {"quality-2"}
