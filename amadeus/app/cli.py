from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from amadeus.app.bootstrap import build_passive_app
from amadeus.runtime.passive import PassiveTurnResult


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "chat":
        asyncio.run(_run_chat(args))
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


if __name__ == "__main__":
    main()
