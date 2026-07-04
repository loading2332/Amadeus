import asyncio

from amadeus.session import PostgresSessionStore
from amadeus.turns import (
    TURN_DONE,
    TURN_FAILED,
    TURN_PENDING,
    PostgresTurnStore,
    Turn,
    TurnStore,
)
from amadeus.worker.turn_worker import TurnWorker

from tests.db.postgres_helpers import clean_postgres


class FakeRunner:
    async def run(self, turn: Turn) -> str:
        return f"reply:{turn.content}"


class FailingRunner:
    async def run(self, turn: Turn) -> str:
        raise RuntimeError("runtime unavailable")


def test_turn_worker_completes_claimed_turn(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")
    worker = TurnWorker(store=store, runner=FakeRunner())

    assert asyncio.run(worker.run_once()) is True

    completed = store.get_turn(turn.id)
    assert completed is not None
    assert completed.status == TURN_DONE
    assert completed.answer == "reply:hello"
    assert worker.stats.completed == 1


def test_turn_worker_marks_failed_on_runner_error(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")
    worker = TurnWorker(store=store, runner=FailingRunner())

    assert asyncio.run(worker.run_once()) is True

    failed = store.get_turn(turn.id)
    assert failed is not None
    assert failed.status == TURN_FAILED
    assert failed.error is not None
    assert "runtime unavailable" in failed.error
    assert worker.stats.failed == 1


def test_turn_worker_returns_false_when_no_pending_turn(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    worker = TurnWorker(store=store, runner=FakeRunner())

    assert asyncio.run(worker.run_once()) is False


def test_turn_worker_respects_processing_session(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    active = store.create_turn(session_key="web:1", content="active")
    same = store.create_turn(session_key="web:1", content="same")
    other = store.create_turn(session_key="web:2", content="other")
    store.claim_next_pending()
    worker = TurnWorker(store=store, runner=FakeRunner())

    assert asyncio.run(worker.run_once()) is True

    loaded_active = store.get_turn(active.id)
    loaded_same = store.get_turn(same.id)
    loaded_other = store.get_turn(other.id)
    assert loaded_active is not None
    assert loaded_same is not None
    assert loaded_other is not None
    assert loaded_active.status != TURN_PENDING
    assert loaded_same.status == TURN_PENDING
    assert loaded_other.status == TURN_DONE


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
