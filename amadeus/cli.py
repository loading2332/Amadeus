from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from amadeus.bootstrap import build_passive_app, default_workspace_root


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
    chat.add_argument("--show-ids", action="store_true")
    return parser


async def _run_chat(args: argparse.Namespace) -> None:
    app = build_passive_app(
        workspace_root=args.workspace_root,
        env_path=args.env,
    )
    try:
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
    finally:
        app.close()


if __name__ == "__main__":
    main()
