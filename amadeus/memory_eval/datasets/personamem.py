from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from collections import OrderedDict
from pathlib import Path
from typing import Any

from ..contracts import CommonEvalCase, MemoryArtifact, MemoryEvalGroup


def load_personamem_cases(
    questions_path: str | Path,
    contexts_path: str | Path,
    *,
    limit: int | None = None,
) -> Iterator[CommonEvalCase]:
    contexts = _load_contexts(contexts_path)
    with Path(questions_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            shared_context_id = str(row.get("shared_context_id", ""))
            full_context = list(contexts.get(shared_context_id, []))
            end_index = _parse_int(row.get("end_index_in_shared_context"), len(full_context))
            sliced_context = full_context[:end_index]
            yield CommonEvalCase(
                dataset_name="personamem",
                case_id=str(row.get("question_id") or f"row-{index}"),
                task_type="personalized_response_mcq",
                query=str(row.get("user_question_or_message", "")),
                group_id=_group_id(shared_context_id, end_index),
                gold_answer=str(row.get("correct_answer", "")),
                gold_evidence_ids=(),
                memory_artifacts=_context_artifacts(row, sliced_context),
                scoring_spec={
                    "metric": "multiple_choice_accuracy",
                    "all_options": row.get("all_options", ""),
                    "question_type": row.get("question_type", ""),
                },
                native_payload={
                    "question": dict(row),
                    "shared_context": full_context,
                },
            )
            if limit is not None and index + 1 >= limit:
                return


def load_personamem_groups(
    questions_path: str | Path,
    contexts_path: str | Path,
    *,
    limit: int | None = None,
) -> Iterator[MemoryEvalGroup]:
    contexts = _load_contexts(contexts_path)
    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    with Path(questions_path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader):
            shared_context_id = str(row.get("shared_context_id", ""))
            full_context = list(contexts.get(shared_context_id, []))
            end_index = _parse_int(row.get("end_index_in_shared_context"), len(full_context))
            group_id = _group_id(shared_context_id, end_index)
            if group_id not in groups:
                sliced_context = full_context[:end_index]
                groups[group_id] = {
                    "artifacts": _context_artifacts(row, sliced_context),
                    "cases": [],
                    "native_payload": {
                        "shared_context_id": shared_context_id,
                        "end_index_in_shared_context": end_index,
                        "shared_context": full_context,
                    },
                }
            groups[group_id]["cases"].append(
                CommonEvalCase(
                    dataset_name="personamem",
                    group_id=group_id,
                    case_id=str(row.get("question_id") or f"row-{index}"),
                    task_type="personalized_response_mcq",
                    query=str(row.get("user_question_or_message", "")),
                    gold_answer=str(row.get("correct_answer", "")),
                    gold_evidence_ids=(),
                    scoring_spec={
                        "metric": "multiple_choice_accuracy",
                        "all_options": row.get("all_options", ""),
                        "question_type": row.get("question_type", ""),
                    },
                    native_payload={"question": dict(row)},
                )
            )

    emitted = 0
    for group_id, group_data in groups.items():
        yield MemoryEvalGroup(
            dataset_name="personamem",
            group_id=group_id,
            memory_artifacts=group_data["artifacts"],
            cases=tuple(group_data["cases"]),
            native_payload=group_data["native_payload"],
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _load_contexts(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    contexts: dict[str, list[dict[str, Any]]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            for key, value in payload.items():
                contexts[str(key)] = list(value) if isinstance(value, list) else []
    return contexts


def _context_artifacts(
    row: dict[str, str],
    context: list[dict[str, Any]],
) -> tuple[MemoryArtifact, ...]:
    persona_id = str(row.get("persona_id", ""))
    question_id = str(row.get("question_id", ""))
    artifacts: list[MemoryArtifact] = []
    for index, message in enumerate(context):
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        artifacts.append(
            MemoryArtifact(
                artifact_id=f"{question_id}:context:{index}",
                text=f"{role}: {content}" if role else content,
                kind="persona_context_message",
                source_ref=f"{question_id}:context:{index}",
                scope={"persona_id": persona_id} if persona_id else {},
                metadata={"role": role, "topic": row.get("topic", "")},
            )
        )
    return tuple(artifacts)


def _parse_int(value: object, default: int) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


def _group_id(shared_context_id: str, end_index: int) -> str:
    return f"{shared_context_id}:until:{end_index}"
