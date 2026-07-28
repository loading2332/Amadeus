from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace

from amadeus.memory import (
    MEMORY_JOB_DONE,
    MEMORY_JOB_FAILED,
    MEMORY_JOB_PENDING,
    MEMORY_JOB_PROCESSING,
    PostResponseMemoryJob,
)
from amadeus.worker.post_response_memory_worker import (
    PostResponseMemoryWorker,
    _validate_job_messages,
)


def _job(*, status: str = MEMORY_JOB_PROCESSING) -> PostResponseMemoryJob:
    return PostResponseMemoryJob(
        id=str(uuid.uuid4()),
        turn_id=str(uuid.uuid4()),
        user_id=7,
        session_id=70,
        user_message_id="session:7:70:0",
        assistant_message_id="session:7:70:1",
        explicit_memory_ids=("memory-1",),
        status=status,
        attempts=1,
        lease_id=str(uuid.uuid4()) if status == MEMORY_JOB_PROCESSING else None,
        heartbeat_at=None,
        result={},
        error_code=None,
        error_message=None,
        created_at=None,
        started_at=None,
        completed_at=None,
        updated_at=None,
    )


class FakeStore:
    def __init__(self, job: PostResponseMemoryJob) -> None:
        self.pending = job
        self.heartbeats = 0
        self.done_trace: dict[str, object] | None = None
        self.failed_code: str | None = None

    def claim_next_pending(self) -> PostResponseMemoryJob | None:
        job = self.pending
        self.pending = None
        return job

    def heartbeat(self, job_id: str, lease_id: str) -> bool:
        del job_id, lease_id
        self.heartbeats += 1
        return True

    def mark_done(
        self,
        job_id: str,
        lease_id: str,
        trace: dict[str, object],
    ) -> PostResponseMemoryJob:
        del job_id, lease_id
        self.done_trace = trace
        return replace(_job(), status=MEMORY_JOB_DONE, lease_id=None, result=trace)

    def mark_failed(
        self,
        job_id: str,
        lease_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> PostResponseMemoryJob:
        del job_id, lease_id, error_message
        self.failed_code = error_code
        return replace(_job(), status=MEMORY_JOB_FAILED, lease_id=None)

    def recover_stale(self, *, stale_after_seconds: float) -> int:
        del stale_after_seconds
        return 0


class SuccessfulRunner:
    async def run(self, job: PostResponseMemoryJob) -> dict[str, object]:
        return {"turn_id": job.turn_id, "written_count": 1}


class FailingRunner:
    async def run(self, job: PostResponseMemoryJob) -> dict[str, object]:
        del job
        raise RuntimeError("secret provider detail")


def test_memory_worker_completes_claimed_job() -> None:
    store = FakeStore(_job())
    worker = PostResponseMemoryWorker(store=store, runner=SuccessfulRunner())

    assert asyncio.run(worker.run_once()) is True
    assert store.done_trace is not None
    assert store.done_trace["written_count"] == 1
    assert worker.stats.completed == 1
    assert worker.stats.failed == 0


def test_memory_worker_failure_is_terminal_and_safe() -> None:
    store = FakeStore(_job())
    worker = PostResponseMemoryWorker(store=store, runner=FailingRunner())

    assert asyncio.run(worker.run_once()) is True
    assert store.failed_code == "post_response_failed"
    assert store.done_trace is None
    assert worker.stats.failed == 1


def test_memory_worker_heartbeats_while_runner_is_blocked() -> None:
    class BlockingRunner:
        async def run(self, job: PostResponseMemoryJob) -> dict[str, object]:
            del job
            await asyncio.sleep(0.06)
            return {"status": "ok"}

    store = FakeStore(_job())
    worker = PostResponseMemoryWorker(
        store=store,
        runner=BlockingRunner(),
        heartbeat_interval=0.01,
    )

    assert asyncio.run(worker.run_once()) is True
    assert store.heartbeats >= 1


def test_job_message_boundary_accepts_only_the_originating_turn() -> None:
    job = _job()
    messages = [
        {
            "id": job.user_message_id,
            "role": "user",
            "user_id": job.user_id,
            "session_id": job.session_id,
            "turn_id": job.turn_id,
            "content": "hello",
        },
        {
            "id": job.assistant_message_id,
            "role": "assistant",
            "user_id": job.user_id,
            "session_id": job.session_id,
            "turn_id": job.turn_id,
            "content": "answer",
        },
    ]

    _validate_job_messages(job, messages)

    messages[1]["turn_id"] = str(uuid.uuid4())
    try:
        _validate_job_messages(job, messages)
    except ValueError as error:
        assert str(error) == "Post-response job message boundary mismatch"
    else:  # pragma: no cover - assertion helper
        raise AssertionError("mismatched message boundary was accepted")


def test_unclaimed_memory_worker_has_no_work() -> None:
    store = FakeStore(replace(_job(), status=MEMORY_JOB_PENDING))
    store.pending = None
    worker = PostResponseMemoryWorker(store=store, runner=SuccessfulRunner())

    assert asyncio.run(worker.run_once()) is False
