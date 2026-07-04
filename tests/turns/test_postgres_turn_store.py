from __future__ import annotations

from amadeus.session import PostgresSessionStore
from amadeus.turns import TURN_PENDING, TURN_PROCESSING, PostgresTurnStore

from tests.db.postgres_helpers import clean_postgres


def test_postgres_turn_store_claims_once_and_serializes_same_session() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        sessions.create_session(user_id=1, title="first")
        sessions.create_session(user_id=1, title="second")
        store = PostgresTurnStore(db=db)
        first = store.create_turn(user_id=1, session_id=1, content="first")
        second = store.create_turn(user_id=1, session_id=1, content="second")
        other = store.create_turn(user_id=1, session_id=2, content="other")

        claimed = store.claim_next_pending()
        next_claim = store.claim_next_pending()

        assert claimed is not None
        assert claimed.id == first.id
        assert claimed.status == TURN_PROCESSING
        assert next_claim is not None
        assert next_claim.id == other.id
        pending = store.get_turn(second.id)
        assert pending is not None
        assert pending.status == TURN_PENDING
    finally:
        db.close()


def test_postgres_turn_store_terminal_update_keeps_late_failure_from_overwrite() -> None:
    db = clean_postgres()
    try:
        sessions = PostgresSessionStore(db=db)
        sessions.create_session(user_id=1, title="first")
        store = PostgresTurnStore(db=db)
        turn = store.create_turn(user_id=1, session_id=1, content="hello")
        assert store.claim_next_pending() is not None

        done = store.mark_done(turn.id, "answer")
        late = store.mark_failed(turn.id, "late")

        assert done.status == "done"
        assert late.status == "done"
        assert late.answer == "answer"
        assert late.error is None
    finally:
        db.close()
