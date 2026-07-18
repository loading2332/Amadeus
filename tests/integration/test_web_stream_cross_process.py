from __future__ import annotations

import asyncio
import multiprocessing
import os
import socket
import subprocess
import sys
import time
from typing import Protocol

import httpx
from amadeus.runtime.streaming import TurnStreamSink
from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore, Turn
from amadeus.worker.turn_worker import TurnWorker

from tests.db.postgres_helpers import clean_postgres, postgres_dsn


class _CrossProcessRunner:
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_content("A")
        await asyncio.sleep(0.4)
        await stream_sink.publish_content("B")
        return "AB"


class _StartSignal(Protocol):
    def wait(self, timeout: float | None = None) -> bool: ...

    def set(self) -> None: ...


def _run_worker(
    dsn: str,
    start_signal: _StartSignal,
    ready_signal: _StartSignal,
) -> None:
    ready_signal.set()
    if not start_signal.wait(timeout=20):
        raise RuntimeError("API did not release the worker start signal")

    async def scenario() -> None:
        store = PostgresTurnStore(dsn)
        try:
            worker = TurnWorker(
                store=store,
                runner=_CrossProcessRunner(),
                flush_characters=1,
                heartbeat_interval=0.1,
            )
            assert await worker.run_once() is True
        finally:
            store.close()

    asyncio.run(scenario())


def test_api_and_worker_restore_stream_after_sse_disconnect() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="cross-process")
        turns = PostgresTurnStore(db=db)
        turn = turns.create_turn(
            user_id=1,
            session_id=int(session["session_id"]),
            content="smoke",
        )
        port = _free_port()
        context = multiprocessing.get_context("spawn")
        start_signal = context.Event()
        worker_ready = context.Event()
        worker = context.Process(
            target=_run_worker,
            args=(postgres_dsn(), start_signal, worker_ready),
        )
        worker.start()
        assert worker_ready.wait(timeout=20), "worker process did not become ready"
        api = _start_api(port)
        try:
            _wait_for_api(port, api)
            start_signal.set()
            _wait_for_worker_start(turns, turn.id, worker)
            cursor = _disconnect_after_first_snapshot(port, turn.id)
            worker.join(timeout=10)
            assert worker.exitcode == 0

            with httpx.Client(trust_env=False, timeout=10) as client:
                response = client.get(
                    f"http://127.0.0.1:{port}/api/turns/{turn.id}/events",
                    params={"after_seq": cursor},
                )

            assert response.status_code == 200
            assert '"content": "AB"' in response.text
            assert '"status": "done"' in response.text
        finally:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)
            api.terminate()
            try:
                api.wait(timeout=5)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait(timeout=5)
    finally:
        db.close()


def _disconnect_after_first_snapshot(port: int, turn_id: str) -> int:
    cursor = 0
    url = f"http://127.0.0.1:{port}/api/turns/{turn_id}/events"
    with httpx.Client(trust_env=False, timeout=10) as client:
        with client.stream("GET", url) as response:
            block: list[str] = []
            for line in response.iter_lines():
                if line:
                    block.append(line)
                    if line.startswith("id: "):
                        cursor = int(line.removeprefix("id: "))
                    continue
                if "content_snapshot" in "\n".join(block):
                    return cursor
                block = []
    raise AssertionError("SSE closed before the first content snapshot")


def _start_api(port: int) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "AMADEUS_POSTGRES_DSN": postgres_dsn(),
            "AMADEUS_OWNER_USER_ID": "1",
            "OPENAI_BASE_URL": "https://example.invalid/v1",
            "OPENAI_API_KEY": "smoke-only",
            "OPENAI_MODEL": "fake-model",
        }
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "amadeus.web.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_api(port: int, api: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 20
    url = f"http://127.0.0.1:{port}/api/health"
    with httpx.Client(trust_env=False, timeout=0.5) as client:
        while time.monotonic() < deadline:
            if api.poll() is not None:
                stdout, stderr = api.communicate()
                raise AssertionError(
                    "FastAPI process exited before readiness: "
                    f"{api.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
                )
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
    raise AssertionError("FastAPI process did not become ready")


def _wait_for_worker_start(
    turns: PostgresTurnStore,
    turn_id: str,
    worker: multiprocessing.Process,
) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        turn = turns.get_turn(turn_id)
        if turn is not None and turn.status != "pending":
            return
        if worker.exitcode is not None:
            raise AssertionError(
                f"worker exited before claiming the turn: {worker.exitcode}"
            )
        time.sleep(0.05)
    raise AssertionError("worker did not claim the turn")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
