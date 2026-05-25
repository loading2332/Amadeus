from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ..contracts import CommonEvalCase, MemoryArtifact, MemoryEvalGroup


_SESSION_KEY_RE = re.compile(r"^session_(\d+)$")


def load_locomo_cases(path: str | Path, *, limit: int | None = None) -> Iterator[CommonEvalCase]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    emitted = 0
    for sample in data:
        artifacts = _conversation_artifacts(sample)
        for qa_index, qa in enumerate(sample.get("qa", [])):
            yield CommonEvalCase(
                dataset_name="locomo",
                case_id=f"{sample['sample_id']}:qa:{qa_index}",
                task_type="long_conversation_qa",
                query=str(qa.get("question", "")),
                group_id=str(sample.get("sample_id", "")),
                gold_answer=str(qa.get("answer", "")),
                gold_evidence_ids=tuple(str(item) for item in qa.get("evidence", [])),
                memory_artifacts=artifacts,
                scoring_spec={
                    "metric": "locomo_qa_f1",
                    "category": qa.get("category"),
                },
                native_payload={
                    "sample_id": sample.get("sample_id"),
                    "qa_index": qa_index,
                    "qa": qa,
                    "sample": sample,
                },
            )
            emitted += 1
            if limit is not None and emitted >= limit:
                return


def load_locomo_groups(path: str | Path, *, limit: int | None = None) -> Iterator[MemoryEvalGroup]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    emitted = 0
    for sample in data:
        sample_id = str(sample.get("sample_id", ""))
        artifacts = _conversation_artifacts(sample)
        cases: list[CommonEvalCase] = []
        for qa_index, qa in enumerate(sample.get("qa", [])):
            cases.append(
                CommonEvalCase(
                    dataset_name="locomo",
                    group_id=sample_id,
                    case_id=f"{sample_id}:qa:{qa_index}",
                    task_type="long_conversation_qa",
                    query=str(qa.get("question", "")),
                    gold_answer=str(qa.get("answer", "")),
                    gold_evidence_ids=tuple(str(item) for item in qa.get("evidence", [])),
                    scoring_spec={
                        "metric": "locomo_qa_f1",
                        "category": qa.get("category"),
                    },
                    native_payload={
                        "sample_id": sample.get("sample_id"),
                        "qa_index": qa_index,
                        "qa": qa,
                    },
                )
            )
        yield MemoryEvalGroup(
            dataset_name="locomo",
            group_id=sample_id,
            memory_artifacts=artifacts,
            cases=tuple(cases),
            native_payload={
                "sample_id": sample.get("sample_id"),
                "sample": sample,
            },
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return


def _conversation_artifacts(sample: dict[str, Any]) -> tuple[MemoryArtifact, ...]:
    conversation = sample.get("conversation", {})
    artifacts: list[MemoryArtifact] = []
    for session_key in sorted(_session_keys(conversation), key=lambda key: int(key.split("_")[1])):
        session_no = session_key.split("_")[1]
        timestamp = conversation.get(f"{session_key}_date_time")
        for turn in conversation.get(session_key, []):
            dia_id = str(turn.get("dia_id", ""))
            source_ref = dia_id or f"D{session_no}:?"
            speaker = str(turn.get("speaker", ""))
            text = str(turn.get("text", ""))
            artifacts.append(
                MemoryArtifact(
                    artifact_id=f"{sample.get('sample_id')}:{source_ref}",
                    text=f"{speaker}: {text}" if speaker else text,
                    kind="dialog_turn",
                    source_ref=source_ref,
                    timestamp=str(timestamp) if timestamp is not None else None,
                    metadata={
                        "sample_id": sample.get("sample_id"),
                        "session": session_key,
                        "speaker": speaker,
                    },
                )
            )
    return tuple(artifacts)


def _session_keys(conversation: dict[str, Any]) -> list[str]:
    return [key for key in conversation if _SESSION_KEY_RE.match(key)]
