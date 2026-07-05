from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from amadeus.app.bootstrap import PassiveApp, build_passive_app, default_workspace_root
from amadeus.session.identity import SessionRef, require_session_ref
from amadeus.turns import PostgresTurnStore, Turn

logger = logging.getLogger(__name__)


class TurnRunner(Protocol):
    async def run(self, turn: Turn) -> str: ...


class TurnQueueStore(Protocol):
    def claim_next_pending(self) -> Turn | None: ...

    def mark_done(self, turn_id: str, answer: str) -> Turn: ...

    def mark_failed(self, turn_id: str, error: str) -> Turn: ...


@dataclass
class WorkerStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0


class PassiveAppTurnRunner:
    def __init__(self, app: PassiveApp) -> None:
        self.app = app

    async def run(self, turn: Turn) -> str:
        session = (
            SessionRef(user_id=turn.user_id, session_id=turn.session_id)
            if turn.user_id is not None and turn.session_id is not None
            else require_session_ref(turn.session_key)
        )
        result = await self.app.runtime.run_turn(
            session=session,
            user_message=turn.content,
            runtime_metadata={
                "channel": str(turn.metadata.get("channel") or "web"),
                "turn_id": turn.id,
            },
            extra={"turn_id": turn.id},
        )
        return str(result.assistant_response)


class TurnWorker:
    def __init__(
        self,
        *,
        store: TurnQueueStore,
        runner: TurnRunner,
        poll_interval: float = 0.5,
    ) -> None:
        self.store = store
        self.runner = runner
        self.poll_interval = float(poll_interval)
        self.stats = WorkerStats()

    async def run_once(self) -> bool:
        turn = self.store.claim_next_pending()
        if turn is None:
            return False
        self.stats.claimed += 1
        logger.info("Processing turn id=%s session=%s", turn.id, turn.session_key)
        try:
            answer = await self.runner.run(turn)
        except Exception as exc:
            self.stats.failed += 1
            logger.exception("Turn failed id=%s", turn.id)
            self.store.mark_failed(turn.id, str(exc))
            return True
        self.store.mark_done(turn.id, answer)
        self.stats.completed += 1
        return True

    async def run_forever(self) -> None:
        while True:
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.poll_interval)


async def amain(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    workspace_root = (
        Path(args.workspace_root).resolve()
        if args.workspace_root is not None
        else default_workspace_root()
    )
    app = build_passive_app(workspace_root=workspace_root, env_path=args.env)
    try:
        await app.start()
        store = PostgresTurnStore(app.config.postgres_dsn)
        worker = TurnWorker(
            store=store,
            runner=PassiveAppTurnRunner(app),
            poll_interval=args.poll_interval,
        )
        await worker.run_forever()
    finally:
        await app.aclose()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(amain(argv))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Amadeus Web turn worker.")
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Workspace root containing memory files and plugins.",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the runtime .env file.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="Seconds to wait when no pending turn is available.",
    )
    return parser


if __name__ == "__main__":
    main()
