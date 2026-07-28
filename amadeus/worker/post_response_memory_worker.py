from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from amadeus.app.bootstrap import (
    build_passive_app,
    default_workspace_root,
    load_runtime_config,
)
from amadeus.memory import (
    PostgresPostResponseMemoryJobStore,
    PostResponseMemoryJob,
)
from amadeus.session.identity import SessionRef

logger = logging.getLogger(__name__)


class MemoryJobQueueStore(Protocol):
    def claim_next_pending(self) -> PostResponseMemoryJob | None: ...

    def heartbeat(self, job_id: str, lease_id: str) -> bool: ...

    def mark_done(
        self,
        job_id: str,
        lease_id: str,
        trace: dict[str, Any],
    ) -> PostResponseMemoryJob: ...

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> PostResponseMemoryJob: ...

    def recover_stale(self, *, stale_after_seconds: float) -> int: ...


class MemoryJobRunner(Protocol):
    async def run(self, job: PostResponseMemoryJob) -> dict[str, Any]: ...


@dataclass
class MemoryWorkerStats:
    claimed: int = 0
    completed: int = 0
    failed: int = 0
    recovered: int = 0


class PassiveAppMemoryJobRunner:
    def __init__(
        self,
        workspace_root: Path,
        *,
        env_path: Path = Path(".env"),
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.env_path = env_path

    async def run(self, job: PostResponseMemoryJob) -> dict[str, Any]:
        app = build_passive_app(
            workspace_root=self.workspace_root,
            env_path=self.env_path,
            user_id=job.user_id,
        )
        try:
            memory_engine = app.runtime.memory_engine
            if memory_engine is None:
                return {"status": "skipped", "reason": "memory_disabled"}
            messages = await asyncio.to_thread(
                app.session_manager.store.fetch_by_ids,
                [job.user_message_id, job.assistant_message_id],
            )
            _validate_job_messages(job, messages)
            return await memory_engine.run_post_response(
                session=SessionRef(job.user_id, job.session_id),
                messages=messages,
                explicit_memory_ids=list(job.explicit_memory_ids),
            )
        finally:
            await app.aclose()


class PostResponseMemoryWorker:
    def __init__(
        self,
        *,
        store: MemoryJobQueueStore,
        runner: MemoryJobRunner,
        poll_interval: float = 0.5,
        heartbeat_interval: float = 10.0,
        stale_after_seconds: float = 120.0,
        error_backoff_seconds: float = 0.5,
        max_error_backoff_seconds: float = 10.0,
    ) -> None:
        self.store = store
        self.runner = runner
        self.poll_interval = max(0.01, float(poll_interval))
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))
        self.stale_after_seconds = max(1.0, float(stale_after_seconds))
        self.error_backoff_seconds = max(0.01, float(error_backoff_seconds))
        self.max_error_backoff_seconds = max(
            self.error_backoff_seconds,
            float(max_error_backoff_seconds),
        )
        self.stats = MemoryWorkerStats()

    async def run_once(self) -> bool:
        job = await asyncio.to_thread(self.store.claim_next_pending)
        if job is None:
            return False
        self.stats.claimed += 1
        if job.lease_id is None:
            raise RuntimeError("claimed memory job did not include a lease")
        started = time.monotonic()
        logger.info(
            "Processing post-response memory job id=%s turn_id=%s "
            "user_id=%s session_id=%s attempt=%s",
            job.id,
            job.turn_id,
            job.user_id,
            job.session_id,
            job.attempts,
        )
        try:
            trace = await self._run_with_heartbeat(job)
        except Exception as error:
            self.stats.failed += 1
            logger.error(
                "Post-response memory job failed id=%s turn_id=%s "
                "error_type=%s duration_ms=%d",
                job.id,
                job.turn_id,
                type(error).__name__,
                int((time.monotonic() - started) * 1000),
            )
            await asyncio.to_thread(
                self.store.mark_failed,
                job.id,
                job.lease_id,
                error_code="post_response_failed",
                error_message="后台记忆处理失败",
            )
            return True
        await asyncio.to_thread(
            self.store.mark_done,
            job.id,
            job.lease_id,
            trace,
        )
        self.stats.completed += 1
        logger.info(
            "Post-response memory job completed id=%s turn_id=%s "
            "duration_ms=%d",
            job.id,
            job.turn_id,
            int((time.monotonic() - started) * 1000),
        )
        return True

    async def _run_with_heartbeat(
        self,
        job: PostResponseMemoryJob,
    ) -> dict[str, Any]:
        if job.lease_id is None:  # pragma: no cover - checked by run_once
            raise RuntimeError("claimed memory job did not include a lease")
        task = asyncio.create_task(self.runner.run(job))
        try:
            while True:
                done, _ = await asyncio.wait(
                    {task},
                    timeout=self.heartbeat_interval,
                )
                if task in done:
                    return await task
                lease_active = await asyncio.to_thread(
                    self.store.heartbeat,
                    job.id,
                    job.lease_id,
                )
                if not lease_active:
                    raise RuntimeError("memory job lease is no longer active")
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    async def run_forever(self) -> None:
        backoff = self.error_backoff_seconds
        while True:
            try:
                recovered = await asyncio.to_thread(
                    self.store.recover_stale,
                    stale_after_seconds=self.stale_after_seconds,
                )
                self.stats.recovered += recovered
                worked = await self.run_once()
            except Exception as error:
                logger.error(
                    "Memory worker iteration failed; error_type=%s "
                    "retrying_in_seconds=%.2f",
                    type(error).__name__,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_error_backoff_seconds)
                continue
            backoff = self.error_backoff_seconds
            if not worked:
                await asyncio.sleep(self.poll_interval)


def _validate_job_messages(
    job: PostResponseMemoryJob,
    messages: list[dict[str, Any]],
) -> None:
    expected = (
        (job.user_message_id, "user"),
        (job.assistant_message_id, "assistant"),
    )
    if len(messages) != len(expected):
        raise ValueError("Post-response job messages are incomplete")
    for message, (message_id, role) in zip(messages, expected, strict=True):
        if (
            str(message.get("id") or "") != message_id
            or str(message.get("role") or "") != role
            or int(message.get("user_id") or 0) != job.user_id
            or int(message.get("session_id") or 0) != job.session_id
            or str(message.get("turn_id") or "") != job.turn_id
        ):
            raise ValueError("Post-response job message boundary mismatch")


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
    config = load_runtime_config(
        workspace_root=workspace_root,
        env_path=args.env,
    )
    store = PostgresPostResponseMemoryJobStore(config.postgres_dsn)
    try:
        worker = PostResponseMemoryWorker(
            store=store,
            runner=PassiveAppMemoryJobRunner(workspace_root, env_path=args.env),
            poll_interval=args.poll_interval,
            heartbeat_interval=config.turn_heartbeat_interval_seconds,
            stale_after_seconds=config.turn_stale_after_seconds,
        )
        await worker.run_forever()
    finally:
        store.close()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(amain(argv))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the Amadeus post-response memory worker."
    )
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
        help="Seconds to wait when no pending memory job is available.",
    )
    return parser


if __name__ == "__main__":
    main()
