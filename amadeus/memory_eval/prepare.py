from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DatasetPreparationStatus:
    dataset: str
    status: str
    ready_for_smoke: bool
    ready_for_official_run: bool
    required_paths: tuple[str, ...]
    missing_paths: tuple[str, ...]
    prepare_commands: tuple[str, ...]
    notes: tuple[str, ...]

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


def get_dataset_preparation_status(
    dataset: str,
    *,
    benchmark_root: str | Path,
) -> DatasetPreparationStatus:
    root = Path(benchmark_root)
    if dataset == "locomo":
        return _status_from_paths(
            dataset="locomo",
            required_paths=(root / "locomo" / "data" / "locomo10.json",),
            prepare_commands=(
                "git clone https://github.com/snap-research/locomo.git memorybenchmarks/locomo",
            ),
            notes=(
                "LoCoMo includes data/locomo10.json in the official repository clone.",
                "Official QA scripts live under task_eval/ and scripts/.",
            ),
        )
    if dataset == "personamem":
        return _status_from_paths(
            dataset="personamem",
            required_paths=(
                root / "PersonaMem" / "data" / "questions_32k.csv",
                root / "PersonaMem" / "data" / "shared_contexts_32k.jsonl",
            ),
            prepare_commands=(
                "Open https://huggingface.co/datasets/bowen-upenn/PersonaMem",
                "Download questions_32k.csv into memorybenchmarks/PersonaMem/data/",
                "Download shared_contexts_32k.jsonl into memorybenchmarks/PersonaMem/data/",
            ),
            notes=(
                "The GitHub repository documents the benchmark but does not include the large HuggingFace data files.",
                "Start with 32k files for smoke runs before 128k or 1M.",
            ),
        )
    if dataset == "longmemeval_v2":
        data_root = root / "LongMemEval-V2" / "data" / "longmemeval-v2"
        return _status_from_paths(
            dataset="longmemeval_v2",
            required_paths=(
                data_root / "runtime_questions.json",
                data_root / "runtime_haystack.json",
                data_root / "trajectories.json",
            ),
            prepare_commands=(
                "cd memorybenchmarks/LongMemEval-V2",
                "python data/download_data.py --data-root data/longmemeval-v2",
                "python data/prepare_data.py --data-root data/longmemeval-v2 --mode symlink",
                "python data/validate_data.py --data-root data/longmemeval-v2 --tier small",
            ),
            notes=(
                "The official repo prepares public data from HuggingFace before evaluation.",
                "Amadeus still needs a materialize step that writes runtime_questions.json and runtime_haystack.json for small smoke cases.",
            ),
        )
    raise ValueError(f"Unsupported dataset: {dataset}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report memory benchmark data preparation status.")
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
    args = parser.parse_args(argv)
    status = get_dataset_preparation_status(args.dataset, benchmark_root=args.benchmark_root)
    print(json.dumps(status.to_json_dict(), indent=2, ensure_ascii=True))
    return 0


def _status_from_paths(
    *,
    dataset: str,
    required_paths: tuple[Path, ...],
    prepare_commands: tuple[str, ...],
    notes: tuple[str, ...],
) -> DatasetPreparationStatus:
    missing_paths = tuple(str(path) for path in required_paths if not path.exists())
    ready = not missing_paths
    return DatasetPreparationStatus(
        dataset=dataset,
        status="ready" if ready else "missing_data",
        ready_for_smoke=ready,
        ready_for_official_run=ready,
        required_paths=tuple(str(path) for path in required_paths),
        missing_paths=missing_paths,
        prepare_commands=prepare_commands,
        notes=notes,
    )


if __name__ == "__main__":
    raise SystemExit(main())

