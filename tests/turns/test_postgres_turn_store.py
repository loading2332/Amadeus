from __future__ import annotations

import pytest
from amadeus.session import PostgresSessionStore
from amadeus.turns import (
    TURN_CANCELLED,
    TURN_DONE,
    TURN_FAILED,
    TURN_FINALIZING,
    TURN_PROCESSING,
    ActiveTurnExists,
    InvalidTurnTransition,
    PostgresTurnStore,
    TurnError,
)

from tests.db.postgres_helpers import clean_postgres


def test_postgres_turn_store_enforces_one_active_turn_per_session() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        first_session = sessions.create_session(user_id=1, title="first")
        second_session = sessions.create_session(user_id=1, title="second")
        store = PostgresTurnStore(db=db)
        first = store.create_turn(
            user_id=1,
            session_id=first_session["session_id"],
            content="first",
        )

        with pytest.raises(ActiveTurnExists):
            store.create_turn(
                user_id=1,
                session_id=first_session["session_id"],
                content="blocked",
            )

        other = store.create_turn(
            user_id=1,
            session_id=second_session["session_id"],
            content="other",
        )
        claimed = store.claim_next_pending()

        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.status == TURN_PROCESSING
        assert claimed.lease_id is not None
        assert store.get_turn(other.id) is not None
    finally:
        db.close()


def test_postgres_turn_store_persists_monotonic_safe_stream_events() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="stream")
        store = PostgresTurnStore(db=db)
        created = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )
        claimed = store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None

        store.append_content_snapshot(claimed.id, claimed.lease_id, "你")
        store.append_content_snapshot(claimed.id, claimed.lease_id, "你好")
        store.append_tool_activity(
            claimed.id,
            claimed.lease_id,
            activity_id="search-1",
            tool_name="search",
            state="started",
        )
        done = store.mark_done(claimed.id, claimed.lease_id, "你好")
        events = store.list_events(created.id)

        assert done.status == TURN_DONE
        assert done.answer == "你好"
        assert done.partial_answer == "你好"
        assert [event.seq for event in events] == list(range(1, len(events) + 1))
        assert [event.type for event in events] == [
            "turn_status",
            "turn_status",
            "content_snapshot",
            "content_snapshot",
            "tool_activity",
            "turn_terminal",
        ]
        assert events[4].data == {
            "activity_id": "search-1",
            "tool_name": "search",
            "state": "started",
        }
        assert "arguments" not in events[4].data
        with pytest.raises(InvalidTurnTransition):
            store.append_content_snapshot(claimed.id, claimed.lease_id, "late")
        with pytest.raises(InvalidTurnTransition):
            store.request_cancel(claimed.id)
    finally:
        db.close()


def test_postgres_turn_store_cancel_and_retry_keep_original_immutable() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="retry")
        store = PostgresTurnStore(db=db)
        original = store.create_turn(
            user_id=1,
            session_id=session["session_id"],
            content="hello",
        )

        cancelled = store.request_cancel(original.id)
        retry = store.retry_turn(turn_id=original.id, user_id=1)

        assert cancelled.status == TURN_CANCELLED
        assert retry.id != original.id
        assert retry.content == original.content
        assert retry.retry_of_turn_id == original.id
        assert store.get_turn(original.id) == cancelled
        with pytest.raises(InvalidTurnTransition):
            store.retry_turn(turn_id=retry.id, user_id=1)
    finally:
        db.close()


def test_postgres_turn_store_rejects_late_terminal_overwrite() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="terminal")
        store = PostgresTurnStore(db=db)
        store.create_turn(user_id=1, session_id=session["session_id"], content="hi")
        claimed = store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None

        store.mark_failed(
            claimed.id,
            claimed.lease_id,
            TurnError("runtime_error", "处理失败", True),
        )

        with pytest.raises(InvalidTurnTransition):
            store.mark_done(claimed.id, claimed.lease_id, "late")
        failed = store.get_turn(claimed.id)
        assert failed is not None
        assert failed.status == TURN_FAILED
        assert failed.error_code == "runtime_error"
    finally:
        db.close()


def test_postgres_turn_store_processing_cancel_is_cooperative() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="cancel")
        store = PostgresTurnStore(db=db)
        store.create_turn(user_id=1, session_id=session["session_id"], content="hi")
        claimed = store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None

        requested = store.request_cancel(claimed.id)

        assert requested.status == TURN_PROCESSING
        assert requested.cancel_requested_at is not None
        assert store.cancel_requested(claimed.id, claimed.lease_id) is True
        assert store.heartbeat(claimed.id, claimed.lease_id) is True
        cancelled = store.mark_cancelled(claimed.id, claimed.lease_id)
        assert cancelled.status == TURN_CANCELLED
    finally:
        db.close()


def test_postgres_turn_store_finalization_is_the_cancel_linearization_point() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="finalizing")
        store = PostgresTurnStore(db=db)
        store.create_turn(user_id=1, session_id=session["session_id"], content="hi")
        claimed = store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None

        finalizing = store.begin_finalization(claimed.id, claimed.lease_id)

        assert finalizing.status == TURN_FINALIZING
        with pytest.raises(InvalidTurnTransition):
            store.request_cancel(claimed.id)
        done = store.mark_done(claimed.id, claimed.lease_id, "answer")
        assert done.status == TURN_DONE
    finally:
        db.close()


def test_postgres_turn_store_stale_recovery_revalidates_lease_and_heartbeat() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session = sessions.create_session(user_id=1, title="recovery race")
        store = PostgresTurnStore(db=db)
        store.create_turn(user_id=1, session_id=session["session_id"], content="hi")
        claimed = store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET heartbeat_at = now() - interval '10 minutes'
                    WHERE id = %s
                    """,
                    (claimed.id,),
                )
            conn.commit()
        assert store.list_stale_processing(stale_after_seconds=1)

        store.heartbeat(claimed.id, claimed.lease_id)
        unchanged = store.reconcile_interrupted(
            claimed.id,
            lease_id=claimed.lease_id,
            stale_after_seconds=1,
            assistant_answer=None,
        )

        assert unchanged.status == TURN_PROCESSING
        assert not [
            event
            for event in store.list_events(claimed.id)
            if event.type == "turn_terminal"
        ]
    finally:
        db.close()
