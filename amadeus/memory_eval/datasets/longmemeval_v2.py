from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..contracts import CommonEvalCase, MemoryArtifact, MemoryEvalGroup


def load_longmemeval_v2_cases(
    questions_path: str | Path,
    haystack_path: str | Path,
    trajectories_path: str | Path,
    *,
    limit: int | None = None,
) -> Iterator[CommonEvalCase]:
    questions = _load_json_list(questions_path)
    haystack = json.loads(Path(haystack_path).read_text(encoding="utf-8"))
    trajectories = {
        str(row["id"]): row
        for row in _load_json_list(trajectories_path)
        if isinstance(row, dict) and row.get("id")
    }

    emitted = 0
    for question in questions:
        question_id = str(question.get("id", ""))
        trajectory_ids = tuple(str(item) for item in haystack.get(question_id, []))
        selected_trajectories = [trajectories[item] for item in trajectory_ids if item in trajectories]
        yield CommonEvalCase(
            dataset_name="longmemeval_v2",
            group_id=f"{question_id}:haystack",
            case_id=question_id,
            task_type=str(question.get("question_type") or question.get("category") or "qa"),
            query=_question_text(question.get("question")),
            gold_answer=_optional_text(question.get("answer")),
            gold_evidence_ids=trajectory_ids,
            memory_artifacts=tuple(_trajectory_artifact(row) for row in selected_trajectories),
            scoring_spec={
                "metric": "longmemeval_v2_accuracy_latency",
                "domain": question.get("domain"),
            },
            native_payload={
                "question": question,
                "haystack": list(trajectory_ids),
                "trajectories": selected_trajectories,
            },
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def load_longmemeval_v2_groups(
    questions_path: str | Path,
    haystack_path: str | Path,
    trajectories_path: str | Path,
    *,
    limit: int | None = None,
) -> Iterator[MemoryEvalGroup]:
    questions = _load_json_list(questions_path)
    haystack = json.loads(Path(haystack_path).read_text(encoding="utf-8"))
    trajectories = {
        str(row["id"]): row
        for row in _load_json_list(trajectories_path)
        if isinstance(row, dict) and row.get("id")
    }

    emitted = 0
    for question in questions:
        question_id = str(question.get("id", ""))
        group_id = f"{question_id}:haystack"
        trajectory_ids = tuple(str(item) for item in haystack.get(question_id, []))
        selected_trajectories = [trajectories[item] for item in trajectory_ids if item in trajectories]
        case = CommonEvalCase(
            dataset_name="longmemeval_v2",
            group_id=group_id,
            case_id=question_id,
            task_type=str(question.get("question_type") or question.get("category") or "qa"),
            query=_question_text(question.get("question")),
            gold_answer=_optional_text(question.get("answer")),
            gold_evidence_ids=trajectory_ids,
            scoring_spec={
                "metric": "longmemeval_v2_accuracy_latency",
                "domain": question.get("domain"),
            },
            native_payload={
                "question": question,
                "haystack": list(trajectory_ids),
            },
        )
        yield MemoryEvalGroup(
            dataset_name="longmemeval_v2",
            group_id=group_id,
            memory_artifacts=tuple(_trajectory_artifact(row) for row in selected_trajectories),
            cases=(case,),
            native_payload={
                "question_id": question_id,
                "haystack": list(trajectory_ids),
                "trajectories": selected_trajectories,
            },
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _load_json_list(path: str | Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list: {path}")
    return data


def _trajectory_artifact(trajectory: dict[str, Any]) -> MemoryArtifact:
    trajectory_id = str(trajectory.get("id", ""))
    return MemoryArtifact(
        artifact_id=f"trajectory:{trajectory_id}",
        text=json.dumps(trajectory, ensure_ascii=True, sort_keys=True),
        kind="trajectory",
        source_ref=trajectory_id,
        metadata={"domain": trajectory.get("domain")},
    )


def _question_text(value: object) -> str:
    if isinstance(value, dict):
        return str(value.get("text", ""))
    return str(value or "")


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
