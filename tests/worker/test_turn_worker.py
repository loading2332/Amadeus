import asyncio

from amadeus.session import PostgresSessionStore
from amadeus.turns import (
    TURN_DONE,
    PostgresTurnStore,
    Turn,
)
from amadeus.worker.turn_worker import TurnWorker

from tests.db.postgres_helpers import clean_postgres


class FakeRunner:
    async def run(self, turn: Turn) -> str:
        return f"reply:{turn.content}"


class FailingRunner:
    async def run(self, turn: Turn) -> str:
        raise RuntimeError("runtime unavailable")


def test_turn_worker_completes_postgres_turn():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="worker")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        worker = TurnWorker(store=store, runner=FakeRunner())

        assert asyncio.run(worker.run_once()) is True

        completed = store.get_turn(turn.id)
        assert completed is not None
        assert completed.status == TURN_DONE
        assert completed.answer == "reply:hello"
        assert completed.user_id == 1
        assert completed.session_id == session["session_id"]
    finally:
        db.close()


def test_turn_worker_marks_failed_on_postgres_runner_error():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="worker")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        worker = TurnWorker(store=store, runner=FailingRunner())

        assert asyncio.run(worker.run_once()) is True

        failed = store.get_turn(turn.id)
        assert failed is not None
        assert failed.error is not None
        assert "runtime unavailable" in failed.error
        assert worker.stats.failed == 1
    finally:
        db.close()


def test_turn_worker_returns_false_when_no_postgres_pending_turn():
    db = clean_postgres()
    try:
        store = PostgresTurnStore(db=db)
        worker = TurnWorker(store=store, runner=FakeRunner())

        assert asyncio.run(worker.run_once()) is False
    finally:
        db.close()
