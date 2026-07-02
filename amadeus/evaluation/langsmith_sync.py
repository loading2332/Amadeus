from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langsmith import Client

from amadeus.app.bootstrap import _read_dotenv
from amadeus.evaluation.cases import MemoryRecallCase


@dataclass(frozen=True)
class DatasetSyncResult:
    dataset_id: str
    dataset_name: str
    created_examples: int
    updated_examples: int


def build_langsmith_client(
    *,
    env_path: str | Path = ".env",
    client_class: type[Client] | Any = Client,
) -> Client | Any:
    file_values = _read_dotenv(Path(env_path))
    api_key = (
        file_values.get("LANGSMITH_API_KEY")
        or file_values.get("LANGCHAIN_API_KEY")
    )
    api_url = (
        file_values.get("LANGSMITH_ENDPOINT")
        or file_values.get("LANGCHAIN_ENDPOINT")
    )
    web_url = file_values.get("LANGSMITH_WEB_URL")
    workspace_id = file_values.get("LANGSMITH_WORKSPACE_ID")
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if api_url:
        kwargs["api_url"] = api_url
    if web_url:
        kwargs["web_url"] = web_url
    if workspace_id:
        kwargs["workspace_id"] = workspace_id
    return client_class(**kwargs)


def sync_memory_recall_dataset(
    cases: list[MemoryRecallCase],
    *,
    dataset_name: str,
    env_path: str | Path = ".env",
    client: Client | Any | None = None,
) -> DatasetSyncResult:
    langsmith_client = client or build_langsmith_client(env_path=env_path)
    dataset = next(
        langsmith_client.list_datasets(dataset_name=dataset_name),
        None,
    )
    if dataset is None:
        dataset = langsmith_client.create_dataset(
            dataset_name,
            description="Repo-canonical Memory Recall evaluation cases for Amadeus.",
            metadata={"suite": "memory_recall_v1"},
        )
    dataset_id = str(dataset.id)

    existing_by_case_id: dict[str, Any] = {}
    for example in langsmith_client.list_examples(dataset_id=dataset_id):
        metadata = getattr(example, "metadata", {}) or {}
        case_id = str(metadata.get("case_id") or "").strip()
        if case_id:
            existing_by_case_id[case_id] = example

    created = 0
    updated = 0
    for case in cases:
        inputs = {"case": case.to_record()}
        outputs = {"expect": case.expect.to_record()}
        metadata = {
            "case_id": case.id,
            "title": case.title,
            "mode": case.mode,
        }
        existing = existing_by_case_id.get(case.id)
        if existing is None:
            langsmith_client.create_example(
                dataset_id=dataset_id,
                inputs=inputs,
                outputs=outputs,
                metadata=metadata,
            )
            created += 1
            continue
        langsmith_client.update_example(
            str(existing.id),
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
            dataset_id=dataset_id,
        )
        updated += 1

    return DatasetSyncResult(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        created_examples=created,
        updated_examples=updated,
    )
