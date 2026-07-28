from __future__ import annotations

from datetime import datetime

import pytest
from amadeus.memory import (
    MEMORY_JOB_DONE,
    MEMORY_JOB_FAILED,
    MEMORY_JOB_PENDING,
    MEMORY_JOB_PROCESSING,
    InvalidMemoryJobTransition,
    PostgresPostResponseMemoryJobStore,
)
from amadeus.session import PostgresSessionStore
from amadeus.session.identity import SessionRef
from amadeus.turns import (
    TURN_DONE,
    TURN_FINALIZING,
    InvalidTurnTransition,
    PostgresTurnStore,
    TurnExecutionResult,
)

from tests.db.postgres_helpers import clean_postgres


def _completed_turn_with_job(db, *, user_id: int = 1, title: str = "memory-job"):
    sessions = PostgresSessionStore(db=db)
    session_row = sessions.create_session(user_id=user_id, title=title)
    session = SessionRef(user_id, int(session_row["session_id"]))
    turns = PostgresTurnStore(db=db, post_response_memory_enabled=True)
    created = turns.create_turn(
        user_id=user_id,
        session_id=session.session_id,
        content="hello",
    )
    claimed = turns.claim_next_pending()
    assert claimed is not None and claimed.lease_id is not None
    now = datetime.now().astimezone().isoformat()
    user_message = sessions.insert_message(
        session,
        role="user",
        content="hello",
        ts=now,
        seq=0,
        extra={"turn_id": created.id},
    )
    assistant_message = sessions.insert_message(
        session,
        role="assistant",
        content="answer",
        ts=now,
        seq=1,
        extra={"turn_id": created.id},
    )
    turns.begin_finalization(created.id, claimed.lease_id)
    done = turns.complete_success(
        created.id,
        claimed.lease_id,
        TurnExecutionResult(
            answer="answer",
            user_message_id=str(user_message["id"]),
            assistant_message_id=str(assistant_message["id"]),
            explicit_memory_ids=("explicit-1",),
            enqueue_post_response_memory=True,
        ),
    )
    return turns, created, done


def test_complete_success_atomically_enqueues_one_memory_job() -> None:
    db = clean_postgres()
    try:
        turns, created, done = _completed_turn_with_job(db)
        jobs = PostgresPostResponseMemoryJobStore(db=db)
        job = jobs.get_job_by_turn(created.id)

        assert done.status == TURN_DONE
        assert job is not None
        assert job.turn_id == created.id
        assert job.status == MEMORY_JOB_PENDING
        assert job.explicit_memory_ids == ("explicit-1",)
        assert [event.type for event in turns.list_events(created.id)][-1] == (
            "turn_terminal"
        )
    finally:
        db.close()


def test_complete_success_rejects_unpersisted_message_boundary() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session_row = sessions.create_session(user_id=1, title="invalid-boundary")
        turns = PostgresTurnStore(db=db, post_response_memory_enabled=True)
        created = turns.create_turn(
            user_id=1,
            session_id=int(session_row["session_id"]),
            content="hello",
        )
        claimed = turns.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        turns.begin_finalization(created.id, claimed.lease_id)

        with pytest.raises(InvalidTurnTransition):
            turns.complete_success(
                created.id,
                claimed.lease_id,
                TurnExecutionResult(
                    answer="answer",
                    user_message_id="missing-user-message",
                    assistant_message_id="missing-assistant-message",
                    enqueue_post_response_memory=True,
                ),
            )

        current = turns.get_turn(created.id)
        assert current is not None
        assert current.status == TURN_FINALIZING
        assert PostgresPostResponseMemoryJobStore(db=db).get_job_by_turn(
            created.id
        ) is None
        assert "turn_terminal" not in {
            event.type for event in turns.list_events(created.id)
        }
    finally:
        db.close()


def test_memory_job_claim_lease_terminal_and_stale_recovery() -> None:
    db = clean_postgres()
    try:
        _, created, _ = _completed_turn_with_job(db)
        jobs = PostgresPostResponseMemoryJobStore(db=db)

        claimed = jobs.claim_next_pending()
        assert claimed is not None
        assert claimed.turn_id == created.id
        assert claimed.status == MEMORY_JOB_PROCESSING
        assert claimed.lease_id is not None
        assert claimed.attempts == 1
        assert jobs.claim_next_pending() is None

        with pytest.raises(InvalidMemoryJobTransition):
            jobs.mark_done(claimed.id, "wrong-lease", {"written_count": 1})

        done = jobs.mark_done(
            claimed.id,
            claimed.lease_id,
            {"written_count": 1},
        )
        assert done.status == MEMORY_JOB_DONE
        assert done.result == {"written_count": 1}

        with pytest.raises(InvalidMemoryJobTransition):
            jobs.mark_failed(
                claimed.id,
                claimed.lease_id,
                error_code="late",
                error_message="late",
            )
    finally:
        db.close()


def test_memory_jobs_serialize_one_session_but_allow_other_sessions() -> None:
    db = clean_postgres()
    try:
        first_turns, first_created, _ = _completed_turn_with_job(
            db,
            user_id=1,
            title="first-session",
        )
        _, other_created, _ = _completed_turn_with_job(
            db,
            user_id=2,
            title="other-session",
        )
        first = first_turns.get_turn(first_created.id)
        assert first is not None
        sessions = PostgresSessionStore(db=db)
        second_created = first_turns.create_turn(
            user_id=first.user_id,
            session_id=first.session_id,
            content="second",
        )
        second_claimed = first_turns.claim_next_pending()
        assert second_claimed is not None and second_claimed.lease_id is not None
        now = datetime.now().astimezone().isoformat()
        user_message = sessions.insert_message(
            SessionRef(first.user_id, first.session_id),
            role="user",
            content="second",
            ts=now,
            seq=2,
            extra={"turn_id": second_created.id},
        )
        assistant_message = sessions.insert_message(
            SessionRef(first.user_id, first.session_id),
            role="assistant",
            content="second answer",
            ts=now,
            seq=3,
            extra={"turn_id": second_created.id},
        )
        first_turns.begin_finalization(second_created.id, second_claimed.lease_id)
        first_turns.complete_success(
            second_created.id,
            second_claimed.lease_id,
            TurnExecutionResult(
                answer="second answer",
                user_message_id=str(user_message["id"]),
                assistant_message_id=str(assistant_message["id"]),
                enqueue_post_response_memory=True,
            ),
        )
        jobs = PostgresPostResponseMemoryJobStore(db=db)

        claimed_one = jobs.claim_next_pending()
        claimed_other_session = jobs.claim_next_pending()
        assert claimed_one is not None and claimed_one.lease_id is not None
        assert claimed_other_session is not None
        assert {claimed_one.turn_id, claimed_other_session.turn_id} == {
            first_created.id,
            other_created.id,
        }
        assert jobs.claim_next_pending() is None

        first_session_job = {
            claimed_one.turn_id: claimed_one,
            claimed_other_session.turn_id: claimed_other_session,
        }[first_created.id]
        assert first_session_job.lease_id is not None
        jobs.mark_done(first_session_job.id, first_session_job.lease_id, {})
        next_same_session = jobs.claim_next_pending()
        assert next_same_session is not None
        assert next_same_session.turn_id == second_created.id
    finally:
        db.close()


def test_memory_job_failure_is_independent_from_done_turn() -> None:
    db = clean_postgres()
    try:
        turns, created, _ = _completed_turn_with_job(db)
        jobs = PostgresPostResponseMemoryJobStore(db=db)
        claimed = jobs.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None

        failed = jobs.mark_failed(
            claimed.id,
            claimed.lease_id,
            error_code="provider_error",
            error_message="后台记忆处理失败",
        )

        assert failed.status == MEMORY_JOB_FAILED
        assert failed.error_code == "provider_error"
        turn = turns.get_turn(created.id)
        assert turn is not None
        assert turn.status == TURN_DONE
    finally:
        db.close()


def test_memory_job_stale_lease_becomes_pending_again() -> None:
    db = clean_postgres()
    try:
        _, created, _ = _completed_turn_with_job(db)
        jobs = PostgresPostResponseMemoryJobStore(db=db)
        claimed = jobs.claim_next_pending()
        assert claimed is not None
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE post_response_memory_jobs
                    SET heartbeat_at = now() - interval '10 minutes'
                    WHERE id = %s
                    """,
                    (claimed.id,),
                )
            conn.commit()

        assert jobs.recover_stale(stale_after_seconds=60) == 1
        recovered = jobs.get_job_by_turn(created.id)
        assert recovered is not None
        assert recovered.status == MEMORY_JOB_PENDING
        assert recovered.lease_id is None

        reclaimed = jobs.claim_next_pending()
        assert reclaimed is not None
        assert reclaimed.id == claimed.id
        assert reclaimed.attempts == 2
    finally:
        db.close()


def test_stale_turn_reconciliation_atomically_restores_memory_job() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        session_row = sessions.create_session(user_id=1, title="stale-turn")
        session = SessionRef(1, int(session_row["session_id"]))
        turns = PostgresTurnStore(db=db, post_response_memory_enabled=True)
        created = turns.create_turn(
            user_id=1,
            session_id=session.session_id,
            content="hello",
        )
        claimed = turns.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        now = datetime.now().astimezone().isoformat()
        user_message = sessions.insert_message(
            session,
            role="user",
            content="hello",
            ts=now,
            seq=0,
            extra={"turn_id": created.id},
        )
        assistant_message = sessions.insert_message(
            session,
            role="assistant",
            content="recovered answer",
            ts=now,
            seq=1,
            extra={"turn_id": created.id},
        )
        with db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE conversation_turns
                    SET heartbeat_at = now() - interval '10 minutes'
                    WHERE id = %s
                    """,
                    (created.id,),
                )
            conn.commit()

        recovered = turns.reconcile_interrupted(
            created.id,
            lease_id=claimed.lease_id,
            stale_after_seconds=60,
            assistant_answer="recovered answer",
        )
        job = PostgresPostResponseMemoryJobStore(db=db).get_job_by_turn(created.id)

        assert recovered.status == TURN_DONE
        assert job is not None
        assert job.status == MEMORY_JOB_PENDING
        assert job.user_message_id == str(user_message["id"])
        assert job.assistant_message_id == str(assistant_message["id"])
    finally:
        db.close()
