from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from amadeus.app.bootstrap import build_passive_app
from amadeus.evaluation.memory_quality_runner import run_memory_quality_evaluation
from amadeus.evaluation.memory_recall_runner import run_memory_recall_evaluation
from amadeus.runtime.passive import PassiveTurnResult


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "chat":
        asyncio.run(_run_chat(args))
        return
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
    chat = subcommands.add_parser("chat", help="Run one passive chat turn.")
    chat.add_argument("message", help="User message for this turn.")
    chat.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Workspace root for sessions and memory files.",
    )
    chat.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the runtime .env file.",
    )
    chat.add_argument(
        "--session-key",
        default=None,
        help="Stable session key. Defaults to AMADEUS_SESSION_KEY or cli:default.",
    )
    chat.add_argument("--retrieved-memory", default=None)
    chat.add_argument("--skill", action="append", default=[])
    chat.add_argument("--show-ids", action="store_true", help="Show session key and message IDs.")
    chat.add_argument(
        "--trace",
        action="store_true",
        help="Show extended trace: tools, context retry, provider model/usage, sessions DB path.",
    )
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


async def _run_chat(args: argparse.Namespace) -> None:
    app = build_passive_app(
        workspace_root=args.workspace_root,
        env_path=args.env,
    )
    primary_error: BaseException | None = None
    try:
        await app.start()
        session_key = args.session_key or app.config.default_session_key
        result = await app.runtime.run_turn(
            session_key=session_key,
            user_message=args.message,
            retrieved_memory=args.retrieved_memory,
            active_skills=args.skill,
        )
        print(result.assistant_response)
        if args.show_ids:
            print(f"\nsession: {result.session_key}")
            print(f"user_message_id: {result.user_message_id}")
            print(f"assistant_message_id: {result.assistant_message_id}")
        if args.trace:
            _print_trace(result, app)
    except BaseException as error:
        primary_error = error
        raise
    finally:
        try:
            await app.aclose()
        except BaseException as cleanup_error:
            if primary_error is None:
                raise
            primary_error.add_note(
                f"PassiveApp cleanup failed ({type(cleanup_error).__name__})"
            )


def _format_trace(result: PassiveTurnResult, app: object) -> str:
    """Return a trace string for the completed turn.

    This is a deterministic formatting function, testable without a real
    provider or network call.
    """
    from amadeus.app.bootstrap import PassiveApp

    parts: list[str] = []

    # Session
    parts.append("─" * 48)
    parts.append(f"  Session key:        {result.session_key}")
    parts.append(f"  User message ID:    {result.user_message_id}")
    parts.append(f"  Assistant message ID: {result.assistant_message_id}")
    if isinstance(app, PassiveApp):
        sessions_db = app.config.workspace_root / "sessions.db"
        parts.append(f"  Sessions DB:        {sessions_db}")

    # Context retry / trim
    retry = result.context_retry or {}
    parts.append(f"  Retry plan:         {retry.get('selected_plan', 'N/A')}")
    attempts = retry.get("attempts", [])
    if attempts:
        parts.append(f"  Trim attempts:      {len(attempts)}")
        for a in attempts:
            disabled = sorted(a.get("disabled_sections", []))
            parts.append(f"    - {a.get('name', '?')}  window={a.get('history_window', '?')}"
                         f"{'  disabled=' + ','.join(disabled) if disabled else ''}")

    # Tool chain
    tool_chain = result.tool_chain or []
    parts.append(f"  Tool chain steps:   {len(tool_chain)}")
    for idx, step in enumerate(tool_chain):
        calls = step.get("calls", [])
        parts.append(f"    Step {idx + 1}: {len(calls)} tool(s)")
        for call in calls:
            parts.append(f"      {call.get('name', '?')}  status={call.get('status', '?')}")

    memory_trace = getattr(result, "memory_trace", {}) or {}
    if memory_trace:
        parts.append(f"  Memory intent:      {memory_trace.get('intent', 'N/A')}")
        parts.append(f"  Memory candidates:  {memory_trace.get('candidate_count', 0)}")
        parts.append(f"  Memory records:     {memory_trace.get('record_count', 0)}")
        injected = ",".join(memory_trace.get("injected_ids", [])) or "-"
        omitted = ",".join(memory_trace.get("omitted_ids", [])) or "-"
        fallbacks = ",".join(memory_trace.get("fallbacks", [])) or "-"
        parts.append(f"  Memory injected:    {injected}")
        parts.append(f"  Memory omitted:     {omitted}")
        parts.append(f"  Memory fallbacks:   {fallbacks}")

    # Provider info
    raw = getattr(result, "provider_raw", None)
    if raw is not None:
        model = getattr(raw, "model", None) or getattr(raw, "model", None)
        parts.append(f"  Provider model:     {model or 'N/A'}")
        usage = getattr(raw, "usage", None)
        if usage:
            parts.append(f"  Usage:              {usage}")

    parts.append("─" * 48)
    return "\n".join(parts)


def _print_trace(result: PassiveTurnResult, app: object) -> None:
    print()
    print(_format_trace(result, app))


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


def _print_eval_report(report: object) -> None:
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
