from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import MemoryEvalTrace


def write_trace_jsonl(
    path: str | Path,
    traces: Iterable[MemoryEvalTrace],
    *,
    append: bool = False,
) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with destination.open(mode, encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(asdict(trace), ensure_ascii=True, sort_keys=True))
            handle.write("\n")


def load_trace_jsonl(path: str | Path) -> Iterator[MemoryEvalTrace]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        yield _trace_from_dict(json.loads(line))


def _trace_from_dict(payload: dict[str, Any]) -> MemoryEvalTrace:
    return MemoryEvalTrace(
        dataset_name=str(payload["dataset_name"]),
        group_id=str(payload["group_id"]),
        case_id=str(payload["case_id"]),
        task_type=str(payload["task_type"]),
        query=str(payload["query"]),
        gold_answer=_optional_str(payload.get("gold_answer")),
        gold_evidence_ids=tuple(str(item) for item in payload.get("gold_evidence_ids", [])),
        memory_strategy=str(payload["memory_strategy"]),
        artifact_ids_seen=tuple(str(item) for item in payload.get("artifact_ids_seen", [])),
        artifact_ids_indexed=tuple(str(item) for item in payload.get("artifact_ids_indexed", [])),
        retrieved_memory_ids=tuple(str(item) for item in payload.get("retrieved_memory_ids", [])),
        retrieval_scores={str(key): float(value) for key, value in payload.get("retrieval_scores", {}).items()},
        injected_memory_ids=tuple(str(item) for item in payload.get("injected_memory_ids", [])),
        injected_context=str(payload.get("injected_context", "")),
        final_answer=str(payload.get("final_answer", "")),
        score=_optional_float(payload.get("score")),
        latency_ms=float(payload.get("latency_ms", 0.0)),
        token_count=_optional_int(payload.get("token_count")),
        cost_estimate=_optional_float(payload.get("cost_estimate")),
        strategy_trace=dict(payload.get("strategy_trace", {})),
        native_payload=dict(payload.get("native_payload", {})),
        scoring_spec=dict(payload.get("scoring_spec", {})),
        score_details=dict(payload.get("score_details", {})),
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)
