import asyncio

from amadeus.runtime.streaming import TurnStreamSink
from amadeus.session import PostgresSessionStore
from amadeus.session.identity import SessionRef
from amadeus.turns import (
    TURN_DONE,
    TURN_FAILED,
    PostgresTurnStore,
    Turn,
)
from amadeus.worker.turn_worker import TurnWorker

from tests.db.postgres_helpers import clean_postgres


class FakeRunner:
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_content("reply:")
        await stream_sink.publish_tool_activity(
            activity_id="search-1", tool_name="search", state="started"
        )
        await stream_sink.publish_tool_activity(
            activity_id="search-1", tool_name="search", state="completed"
        )
        await stream_sink.publish_content(turn.content)
        return f"reply:{turn.content}"


class FailingRunner:
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_content("partial secret-safe answer")
        raise RuntimeError("runtime unavailable at C:/secret/path?api_key=hidden")


class InterleavedRunner:
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_content("I will check. ")
        await stream_sink.publish_tool_activity(
            activity_id="search-1", tool_name="search", state="started"
        )
        await stream_sink.publish_tool_activity(
            activity_id="search-1", tool_name="search", state="completed"
        )
        await stream_sink.publish_content("Final answer.")
        return "Final answer."


class SlowRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        self.started.set()
        while True:
            await stream_sink.publish_content("x")
            await asyncio.sleep(0.01)


class ToolBoundaryRunner:
    def __init__(self) -> None:
        self.first_completed = asyncio.Event()
        self.continue_after_cancel = asyncio.Event()

    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_tool_activity(
            activity_id="external-write-1",
            tool_name="external_write",
            state="started",
        )
        await stream_sink.publish_tool_activity(
            activity_id="external-write-1",
            tool_name="external_write",
            state="completed",
        )
        self.first_completed.set()
        await self.continue_after_cancel.wait()
        await stream_sink.publish_tool_activity(
            activity_id="second-tool-1",
            tool_name="second_tool",
            state="started",
        )
        raise AssertionError("cancelled turn started another tool")


class LateReturnRunner:
    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        await stream_sink.publish_content("complete answer")
        self.ready.set()
        await self.release.wait()
        return "complete answer"


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
        worker = TurnWorker(
            store=store,
            runner=FakeRunner(),
            flush_characters=1,
        )

        assert asyncio.run(worker.run_once()) is True

        completed = store.get_turn(turn.id)
        assert completed is not None
        assert completed.status == TURN_DONE
        assert completed.answer == "reply:hello"
        assert completed.partial_answer == "reply:hello"
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
        assert failed.status == TURN_FAILED
        assert failed.error_code == "runtime_error"
        assert failed.error == "处理请求时发生错误，请重试"
        assert "secret" not in failed.error
        assert failed.partial_answer == "partial secret-safe answer"
        assert worker.stats.failed == 1
    finally:
        db.close()


def test_turn_worker_keeps_text_emitted_before_tool_in_event_timeline():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="interleaved")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        worker = TurnWorker(
            store=store,
            runner=InterleavedRunner(),
            flush_characters=1,
        )

        assert asyncio.run(worker.run_once()) is True

        completed = store.get_turn(turn.id)
        assert completed is not None
        assert completed.answer == "Final answer."
        assert completed.partial_answer == "I will check. Final answer."
        events = store.list_events(turn.id)
        assert [event.type for event in events] == [
            "turn_status",
            "turn_status",
            "content_snapshot",
            "tool_activity",
            "tool_activity",
            "content_snapshot",
            "turn_status",
            "turn_terminal",
        ]
        assert events[3].data["activity_id"] == "search-1"
        assert events[4].data["activity_id"] == "search-1"
        assert events[5].data["content"] == "I will check. Final answer."
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


def test_turn_worker_reconciles_stale_turn_from_committed_assistant_message():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="recovery")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        claimed = store.claim_next_pending()
        assert claimed is not None
        sessions.insert_message(
            SessionRef(1, int(session["session_id"])),
            role="assistant",
            content="already committed",
            ts="2026-07-18T00:00:00+00:00",
            seq=0,
            extra={"turn_id": turn.id},
        )
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET heartbeat_at = now() - interval '10 minutes'
                    WHERE id = %s
                    """,
                    (turn.id,),
                )
            conn.commit()
        worker = TurnWorker(
            store=store,
            runner=FakeRunner(),
            message_store=sessions,
            stale_after_seconds=1,
        )

        assert worker.recover_stale_once() == 1

        recovered = store.get_turn(turn.id)
        assert recovered is not None
        assert recovered.status == TURN_DONE
        assert recovered.answer == "already committed"
        assert recovered.partial_answer == "already committed"
    finally:
        db.close()


def test_turn_worker_observes_persisted_cancel_and_keeps_partial_answer():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="cancel")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        runner = SlowRunner()
        worker = TurnWorker(
            store=store,
            runner=runner,
            flush_characters=1,
            heartbeat_interval=0.05,
        )

        async def scenario() -> None:
            working = asyncio.create_task(worker.run_once())
            await runner.started.wait()
            await asyncio.sleep(0.02)
            store.request_cancel(turn.id)
            assert await working is True

        asyncio.run(scenario())

        cancelled = store.get_turn(turn.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.partial_answer
        assert cancelled.answer is None
        assert worker.stats.cancelled == 1
    finally:
        db.close()


def test_turn_worker_preserves_completed_tool_event_and_starts_no_new_tool_after_cancel():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="tool cancel")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        runner = ToolBoundaryRunner()
        worker = TurnWorker(store=store, runner=runner)

        async def scenario() -> None:
            working = asyncio.create_task(worker.run_once())
            await runner.first_completed.wait()
            store.request_cancel(turn.id)
            runner.continue_after_cancel.set()
            assert await working is True

        asyncio.run(scenario())

        events = store.list_events(turn.id)
        tool_events = [event.data for event in events if event.type == "tool_activity"]
        assert tool_events == [
            {
                "activity_id": "external-write-1",
                "tool_name": "external_write",
                "state": "started",
            },
            {
                "activity_id": "external-write-1",
                "tool_name": "external_write",
                "state": "completed",
            },
        ]
        cancelled = store.get_turn(turn.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
    finally:
        db.close()


def test_turn_worker_marks_stale_turn_interrupted_without_reexecuting():
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="interrupted")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        claimed = store.claim_next_pending()
        assert claimed is not None
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET heartbeat_at = now() - interval '10 minutes'
                    WHERE id = %s
                    """,
                    (turn.id,),
                )
            conn.commit()
        worker = TurnWorker(
            store=store,
            runner=FakeRunner(),
            message_store=sessions,
            stale_after_seconds=1,
        )

        assert worker.recover_stale_once() == 1

        interrupted = store.get_turn(turn.id)
        assert interrupted is not None
        assert interrupted.status == TURN_FAILED
        assert interrupted.error_code == "interrupted"
        assert interrupted.error == "处理进程意外中断，请重试"
        assert worker.stats.claimed == 0
    finally:
        db.close()


def test_turn_worker_cancel_wins_before_finalization() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="cancel race")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        runner = LateReturnRunner()
        worker = TurnWorker(store=store, runner=runner, flush_characters=1)

        async def scenario() -> None:
            working = asyncio.create_task(worker.run_once())
            await runner.ready.wait()
            store.request_cancel(turn.id)
            runner.release.set()
            assert await working is True

        asyncio.run(scenario())

        cancelled = store.get_turn(turn.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.answer is None
        assert cancelled.partial_answer == "complete answer"
    finally:
        db.close()
