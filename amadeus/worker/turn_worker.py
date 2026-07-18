from __future__ import annotations

import argparse
import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from amadeus.app.bootstrap import PassiveApp, build_passive_app, default_workspace_root
from amadeus.runtime.streaming import TurnCancelled, TurnStreamSink
from amadeus.session import PostgresSessionStore
from amadeus.session.identity import SessionRef
from amadeus.turns import PostgresTurnStore, Turn, TurnError

logger = logging.getLogger(__name__)


class TurnRunner(Protocol):
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str: ...


class TurnQueueStore(Protocol):
    def claim_next_pending(self) -> Turn | None: ...

    def heartbeat(self, turn_id: str, lease_id: str) -> bool: ...

    def cancel_requested(self, turn_id: str, lease_id: str) -> bool: ...

    def begin_finalization(self, turn_id: str, lease_id: str) -> Turn | None: ...

    def append_content_snapshot(
        self, turn_id: str, lease_id: str, content: str
    ) -> object: ...

    def append_tool_activity(
        self,
        turn_id: str,
        lease_id: str,
        *,
        activity_id: str,
        tool_name: str,
        state: str,
    ) -> object: ...

    def mark_done(self, turn_id: str, lease_id: str, answer: str) -> Turn: ...

    def mark_cancelled(self, turn_id: str, lease_id: str) -> Turn: ...

    def mark_failed(self, turn_id: str, lease_id: str, error: TurnError) -> Turn: ...

    def list_stale_processing(self, *, stale_after_seconds: float) -> list[Turn]: ...

    def reconcile_interrupted(
        self,
        turn_id: str,
        *,
        lease_id: str,
        stale_after_seconds: float,
        assistant_answer: str | None,
    ) -> Turn: ...


class TurnMessageStore(Protocol):
    def find_message_by_turn(
        self,
        turn_id: str,
        *,
        role: str,
    ) -> dict[str, object] | None: ...


@dataclass
class WorkerStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0


class PassiveAppTurnRunner:
    def __init__(self, app: PassiveApp) -> None:
        self.app = app

    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        session = SessionRef(user_id=turn.user_id, session_id=turn.session_id)
        result = await self.app.runtime.run_turn(
            session=session,
            user_message=turn.content,
            runtime_metadata={
                "channel": str(turn.metadata.get("channel") or "web"),
                "turn_id": turn.id,
            },
            extra={"turn_id": turn.id},
            stream_sink=stream_sink,
        )
        return str(result.assistant_response)


class PersistedTurnStream:
    def __init__(
        self,
        *,
        store: TurnQueueStore,
        turn: Turn,
        flush_characters: int = 128,
        flush_interval: float = 0.1,
    ) -> None:
        if turn.lease_id is None:
            raise ValueError("claimed turn must include lease_id")
        self.store = store
        self.turn_id = turn.id
        self.lease_id = turn.lease_id
        self.content = turn.partial_answer
        self._flushed_content = turn.partial_answer
        self.flush_characters = max(1, int(flush_characters))
        self.flush_interval = max(0.01, float(flush_interval))
        self._last_flush = time.monotonic()
        self._last_cancel_check = 0.0

    async def publish_content(self, delta: str) -> None:
        if not delta:
            return
        self.content += delta
        await self._check_cancelled(force=False)
        if (
            len(self.content) - len(self._flushed_content) >= self.flush_characters
            or time.monotonic() - self._last_flush >= self.flush_interval
        ):
            self.flush()

    async def publish_tool_activity(
        self,
        *,
        activity_id: str,
        tool_name: str,
        state: str,
    ) -> None:
        if state == "started":
            await self._check_cancelled(force=True)
        self.flush()
        self.store.append_tool_activity(
            self.turn_id,
            self.lease_id,
            activity_id=activity_id,
            tool_name=tool_name,
            state=state,
        )
        if state != "started":
            await self._check_cancelled(force=True)

    async def check_cancelled(self) -> None:
        await self._check_cancelled(force=True)

    async def begin_finalization(self) -> None:
        self.flush()
        if self.store.begin_finalization(self.turn_id, self.lease_id) is None:
            raise TurnCancelled()

    async def _check_cancelled(self, *, force: bool) -> None:
        now = time.monotonic()
        if not force and now - self._last_cancel_check < self.flush_interval:
            return
        self._last_cancel_check = now
        if self.store.cancel_requested(self.turn_id, self.lease_id):
            raise TurnCancelled()

    def flush(self) -> None:
        if self.content == self._flushed_content:
            return
        self.store.append_content_snapshot(
            self.turn_id,
            self.lease_id,
            self.content,
        )
        self._flushed_content = self.content
        self._last_flush = time.monotonic()


class TurnWorker:
    def __init__(
        self,
        *,
        store: TurnQueueStore,
        runner: TurnRunner,
        poll_interval: float = 0.5,
        heartbeat_interval: float = 10.0,
        flush_characters: int = 128,
        flush_interval: float = 0.1,
        message_store: TurnMessageStore | None = None,
        stale_after_seconds: float = 120.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.poll_interval = float(poll_interval)
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))
        self.flush_characters = max(1, int(flush_characters))
        self.flush_interval = max(0.01, float(flush_interval))
        self.message_store = message_store
        self.stale_after_seconds = max(1.0, float(stale_after_seconds))
        self.stats = WorkerStats()

    async def run_once(self) -> bool:
        turn = self.store.claim_next_pending()
        if turn is None:
            return False
        self.stats.claimed += 1
        if turn.lease_id is None:
            raise RuntimeError("turn store claimed a turn without a lease")
        logger.info(
            "Processing turn id=%s user_id=%s session_id=%s",
            turn.id,
            turn.user_id,
            turn.session_id,
        )
        stream = PersistedTurnStream(
            store=self.store,
            turn=turn,
            flush_characters=self.flush_characters,
            flush_interval=self.flush_interval,
        )
        try:
            answer = await self._run_with_heartbeat(turn, stream)
            await stream.begin_finalization()
        except TurnCancelled:
            stream.flush()
            self.store.mark_cancelled(turn.id, turn.lease_id)
            self.stats.cancelled += 1
            return True
        except Exception as exc:
            stream.flush()
            self.stats.failed += 1
            logger.exception("Turn failed id=%s", turn.id)
            self.store.mark_failed(turn.id, turn.lease_id, safe_turn_error(exc))
            return True
        stream.flush()
        self.store.mark_done(turn.id, turn.lease_id, answer)
        self.stats.completed += 1
        return True

    async def _run_with_heartbeat(
        self,
        turn: Turn,
        stream: PersistedTurnStream,
    ) -> str:
        task = asyncio.create_task(self.runner.run(turn, stream))
        while True:
            done, _ = await asyncio.wait(
                {task},
                timeout=self.heartbeat_interval,
            )
            if task in done:
                return await task
            if self.store.heartbeat(turn.id, stream.lease_id):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                raise TurnCancelled()

    async def run_forever(self) -> None:
        while True:
            self.recover_stale_once()
            worked = await self.run_once()
            if not worked:
                await asyncio.sleep(self.poll_interval)

    def recover_stale_once(self) -> int:
        if self.message_store is None:
            return 0
        recovered = 0
        for turn in self.store.list_stale_processing(
            stale_after_seconds=self.stale_after_seconds
        ):
            if turn.lease_id is None:
                continue
            message = self.message_store.find_message_by_turn(
                turn.id,
                role="assistant",
            )
            answer = str(message["content"]) if message is not None else None
            self.store.reconcile_interrupted(
                turn.id,
                lease_id=turn.lease_id,
                stale_after_seconds=self.stale_after_seconds,
                assistant_answer=answer,
            )
            recovered += 1
        return recovered


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
        session_store = PostgresSessionStore(app.config.postgres_dsn)
        worker = TurnWorker(
            store=store,
            runner=PassiveAppTurnRunner(app),
            poll_interval=args.poll_interval,
            message_store=session_store,
            heartbeat_interval=app.config.turn_heartbeat_interval_seconds,
            flush_characters=app.config.turn_stream_flush_characters,
            flush_interval=app.config.turn_stream_flush_interval_seconds,
            stale_after_seconds=app.config.turn_stale_after_seconds,
        )
        try:
            await worker.run_forever()
        finally:
            store.close()
            session_store.close()
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


def safe_turn_error(error: Exception) -> TurnError:
    if isinstance(error, TimeoutError):
        return TurnError(
            code="provider_timeout",
            message="模型响应超时，请重试",
            retryable=True,
        )
    return TurnError(
        code="runtime_error",
        message="处理请求时发生错误，请重试",
        retryable=True,
    )


if __name__ == "__main__":
    main()
