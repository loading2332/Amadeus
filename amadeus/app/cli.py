from __future__ import annotations

import argparse
from pathlib import Path

from amadeus.evaluation.memory_quality_runner import (
    MemoryQualityEvaluationReport,
    run_memory_quality_evaluation,
)
from amadeus.evaluation.memory_recall_runner import (
    MemoryRecallEvaluationReport,
    run_memory_recall_evaluation,
)

EvaluationReport = MemoryRecallEvaluationReport | MemoryQualityEvaluationReport


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "eval" and args.eval_command == "memory-recall":
        _run_eval_memory_recall(args)
        return
    if args.command == "eval" and args.eval_command == "memory-quality":
        _run_eval_memory_quality(args)
        return
    parser.print_help()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Amadeus from the formal runtime.")
    subcommands = parser.add_subparsers(dest="command")
    eval_parser = subcommands.add_parser("eval", help="Run evaluation suites.")
    eval_commands = eval_parser.add_subparsers(dest="eval_command")
    memory_recall = eval_commands.add_parser(
        "memory-recall",
        help="Run the Memory Recall evaluation suite with LangSmith.",
    )
    memory_recall.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the runtime .env file.",
    )
    memory_recall.add_argument(
        "--case-file",
        type=Path,
        default=Path("tests/evaluation/cases/memory_recall_v1.yaml"),
        help="Repo-canonical memory recall case file.",
    )
    memory_recall.add_argument(
        "--dataset-name",
        default="amadeus-memory-recall-v1",
        help="LangSmith dataset name.",
    )
    memory_recall.add_argument(
        "--experiment-prefix",
        default="amadeus-memory-recall",
        help="LangSmith experiment prefix.",
    )
    memory_recall.add_argument(
        "--judge-model",
        default=None,
        help="Optional judge model override. Defaults to AMADEUS_EVAL_JUDGE_MODEL or OPENAI_MODEL.",
    )
    memory_recall.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("runtime-artifacts") / "evaluation",
        help="Directory for local evaluation artifacts.",
    )
    memory_quality = eval_commands.add_parser(
        "memory-quality",
        help="Run the Memory Quality evaluation suite with LangSmith.",
    )
    memory_quality.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the runtime .env file.",
    )
    memory_quality.add_argument(
        "--case-file",
        type=Path,
        default=Path("tests/evaluation/cases/memory_quality_v1.yaml"),
        help="Repo-canonical memory quality case file.",
    )
    memory_quality.add_argument(
        "--dataset-name",
        default="amadeus-memory-quality-v1",
        help="LangSmith dataset name.",
    )
    memory_quality.add_argument(
        "--experiment-prefix",
        default="amadeus-memory-quality",
        help="LangSmith experiment prefix.",
    )
    memory_quality.add_argument(
        "--judge-model",
        default=None,
        help="Optional judge model override. Defaults to AMADEUS_EVAL_JUDGE_MODEL or OPENAI_MODEL.",
    )
    memory_quality.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("runtime-artifacts") / "evaluation",
        help="Directory for local evaluation artifacts.",
    )
    return parser


def _run_eval_memory_recall(args: argparse.Namespace) -> None:
    report = run_memory_recall_evaluation(
        env_path=args.env,
        case_file=args.case_file,
        dataset_name=args.dataset_name,
        experiment_prefix=args.experiment_prefix,
        judge_model=args.judge_model,
        artifacts_dir=args.artifacts_dir,
    )
    _print_eval_report(report)


def _run_eval_memory_quality(args: argparse.Namespace) -> None:
    report = run_memory_quality_evaluation(
        env_path=args.env,
        case_file=args.case_file,
        dataset_name=args.dataset_name,
        experiment_prefix=args.experiment_prefix,
        judge_model=args.judge_model,
        artifacts_dir=args.artifacts_dir,
    )
    _print_eval_report(report)


def _print_eval_report(report: EvaluationReport) -> None:
    failed = ", ".join(report.failed_case_ids) if report.failed_case_ids else "-"
    print(f"Total cases: {report.total_cases}")
    print(f"Passed cases: {report.passed_cases}")
    print(f"Failed cases: {failed}")
    print(f"LangSmith experiment: {report.experiment_name}")
    if report.experiment_url:
        print(f"LangSmith URL: {report.experiment_url}")
    print(f"Summary artifact: {report.summary_path}")
    print(f"Results artifact: {report.results_path}")


if __name__ == "__main__":
    main()
