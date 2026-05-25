from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .contracts import MemoryEvalGroup, MemoryEvalTrace, MemoryStrategyAdapter
from .datasets.locomo import load_locomo_groups
from .datasets.longmemeval_v2 import load_longmemeval_v2_groups
from .datasets.personamem import load_personamem_groups
from .harness import run_memory_use_group
from .prepare import get_dataset_preparation_status
from .scoring import aggregate_trace_scores, score_traces
from .strategies.lexical import LexicalMemoryStrategy
from .trace_io import write_trace_jsonl


def build_run_report(
    *,
    dataset: str,
    benchmark_root: str | Path,
    strategy_name: str,
    group_limit: int = 1,
    output_path: str | Path,
) -> dict[str, Any]:
    status = get_dataset_preparation_status(dataset, benchmark_root=benchmark_root)
    if not status.ready_for_smoke:
        return {
            "dataset": dataset,
            "strategy": strategy_name,
            "status": "missing_data",
            "missing_paths": list(status.missing_paths),
            "prepare_commands": list(status.prepare_commands),
            "notes": list(status.notes),
        }

    traces = run_grouped_eval(
        dataset=dataset,
        benchmark_root=benchmark_root,
        strategy_name=strategy_name,
        group_limit=group_limit,
        output_path=output_path,
    )
    group_ids = sorted({trace.group_id for trace in traces})
    return {
        "dataset": dataset,
        "strategy": strategy_name,
        "status": "ok",
        "group_count": len(group_ids),
        "trace_count": len(traces),
        "output_path": str(output_path),
        "group_ids": group_ids,
        "scores": aggregate_trace_scores(traces),
    }


def run_grouped_eval(
    *,
    dataset: str,
    benchmark_root: str | Path,
    strategy_name: str,
    group_limit: int = 1,
    output_path: str | Path,
) -> tuple[MemoryEvalTrace, ...]:
    strategy = _strategy(strategy_name)
    traces: list[MemoryEvalTrace] = []
    for group in _load_groups(dataset, benchmark_root=benchmark_root, group_limit=group_limit):
        traces.extend(run_memory_use_group(group, strategy))
    scored_traces = score_traces(tuple(traces))
    write_trace_jsonl(output_path, scored_traces)
    return scored_traces


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run grouped Amadeus memory eval traces.")
    parser.add_argument(
        "--dataset",
        choices=["locomo", "personamem", "longmemeval_v2"],
        required=True,
    )
    parser.add_argument(
        "--benchmark-root",
        default="memorybenchmarks",
        help="Path containing locomo, PersonaMem, and LongMemEval-V2 clones.",
    )
    parser.add_argument("--strategy", choices=["lexical"], required=True)
    parser.add_argument("--group-limit", type=int, default=1)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    report = build_run_report(
        dataset=args.dataset,
        benchmark_root=args.benchmark_root,
        strategy_name=args.strategy,
        group_limit=args.group_limit,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


def _load_groups(
    dataset: str,
    *,
    benchmark_root: str | Path,
    group_limit: int,
) -> Iterable[MemoryEvalGroup]:
    root = Path(benchmark_root)
    if dataset == "locomo":
        return load_locomo_groups(root / "locomo" / "data" / "locomo10.json", limit=group_limit)
    if dataset == "personamem":
        return load_personamem_groups(
            root / "PersonaMem" / "data" / "questions_32k.csv",
            root / "PersonaMem" / "data" / "shared_contexts_32k.jsonl",
            limit=group_limit,
        )
    if dataset == "longmemeval_v2":
        data_root = root / "LongMemEval-V2" / "data" / "longmemeval-v2"
        return load_longmemeval_v2_groups(
            data_root / "runtime_questions.json",
            data_root / "runtime_haystack.json",
            data_root / "trajectories.json",
            limit=group_limit,
        )
    raise ValueError(f"Unsupported dataset: {dataset}")


def _strategy(strategy_name: str) -> MemoryStrategyAdapter:
    if strategy_name == "lexical":
        return LexicalMemoryStrategy()
    raise ValueError(f"Unsupported strategy: {strategy_name}")


if __name__ == "__main__":
    raise SystemExit(main())
