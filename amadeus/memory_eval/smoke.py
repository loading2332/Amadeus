from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .contracts import CommonEvalCase
from .datasets.locomo import load_locomo_cases
from .datasets.longmemeval_v2 import load_longmemeval_v2_cases
from .datasets.personamem import load_personamem_cases
from .prepare import get_dataset_preparation_status


def build_smoke_report(
    *,
    dataset: str,
    benchmark_root: str | Path,
    limit: int = 3,
) -> dict[str, Any]:
    root = Path(benchmark_root)
    if dataset == "locomo":
        return _load_or_missing(
            dataset=dataset,
            paths=[root / "locomo" / "data" / "locomo10.json"],
            prepare_hint="LoCoMo data/locomo10.json should be present in the official repo clone.",
            loader=lambda: load_locomo_cases(root / "locomo" / "data" / "locomo10.json", limit=limit),
        )
    if dataset == "personamem":
        questions_path = root / "PersonaMem" / "data" / "questions_32k.csv"
        contexts_path = root / "PersonaMem" / "data" / "shared_contexts_32k.jsonl"
        return _load_or_missing(
            dataset=dataset,
            paths=[questions_path, contexts_path],
            prepare_hint=(
                "Download PersonaMem 32k files from HuggingFace into "
                "memorybenchmarks/PersonaMem/data/: questions_32k.csv and "
                "shared_contexts_32k.jsonl."
            ),
            loader=lambda: load_personamem_cases(questions_path, contexts_path, limit=limit),
        )
    if dataset == "longmemeval_v2":
        data_root = root / "LongMemEval-V2" / "data" / "longmemeval-v2"
        questions_path = data_root / "runtime_questions.json"
        haystack_path = data_root / "runtime_haystack.json"
        trajectories_path = data_root / "trajectories.json"
        return _load_or_missing(
            dataset=dataset,
            paths=[questions_path, haystack_path, trajectories_path],
            prepare_hint=(
                "Run LongMemEval-V2 data/download_data.py, prepare_data.py, "
                "validate_data.py, then materialize runtime question/haystack files."
            ),
            loader=lambda: load_longmemeval_v2_cases(
                questions_path,
                haystack_path,
                trajectories_path,
                limit=limit,
            ),
        )
    raise ValueError(f"Unsupported dataset: {dataset}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke inspect Amadeus memory eval datasets.")
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
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args(argv)

    report = build_smoke_report(
        dataset=args.dataset,
        benchmark_root=args.benchmark_root,
        limit=args.limit,
    )
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0


def _load_or_missing(
    *,
    dataset: str,
    paths: list[Path],
    prepare_hint: str,
    loader: Any,
) -> dict[str, Any]:
    missing_paths = [str(path) for path in paths if not path.exists()]
    if missing_paths:
        status = get_dataset_preparation_status(dataset, benchmark_root=_benchmark_root_from_paths(paths))
        return {
            "dataset": dataset,
            "status": "missing_data",
            "missing_paths": list(status.missing_paths) or missing_paths,
            "prepare_hint": prepare_hint,
            "prepare_commands": list(status.prepare_commands),
            "notes": list(status.notes),
        }
    cases = list(loader())
    return {
        "dataset": dataset,
        "status": "ok",
        "case_count": len(cases),
        "cases": [_summarize_case(case) for case in cases],
    }


def _summarize_case(case: CommonEvalCase) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "task_type": case.task_type,
        "query": case.query,
        "gold_answer": case.gold_answer,
        "gold_evidence_ids": list(case.gold_evidence_ids),
        "artifact_count": len(case.memory_artifacts),
        "artifact_kinds": sorted({artifact.kind for artifact in case.memory_artifacts}),
        "scoring_spec": case.scoring_spec,
        "native_payload_keys": sorted(case.native_payload),
    }


def _benchmark_root_from_paths(paths: list[Path]) -> Path:
    first = paths[0]
    parts = first.parts
    if "memorybenchmarks" in parts:
        index = parts.index("memorybenchmarks")
        return Path(*parts[: index + 1])
    return first.parent


if __name__ == "__main__":
    raise SystemExit(main())
