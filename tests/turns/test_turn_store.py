from amadeus.turns import (
    TURN_DONE,
    TURN_PENDING,
    TURN_PROCESSING,
    TurnStore,
)


def test_turn_store_creates_and_reads_pending_turn(tmp_path):
    store = TurnStore(tmp_path / "turns.db")

    turn = store.create_turn(
        session_key="web:1",
        content="hello",
        metadata={"channel": "web"},
    )

    loaded = store.get_turn(turn.id)
    assert loaded is not None
    assert loaded.id == turn.id
    assert loaded.session_key == "web:1"
    assert loaded.content == "hello"
    assert loaded.status == TURN_PENDING
    assert loaded.metadata == {"channel": "web"}


def test_turn_store_claims_oldest_pending_turn(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    first = store.create_turn(session_key="web:1", content="first")
    store.create_turn(session_key="web:2", content="second")

    claimed = store.claim_next_pending()

    assert claimed is not None
    assert claimed.id == first.id
    assert claimed.status == TURN_PROCESSING
    assert claimed.attempts == 1


def test_turn_store_does_not_claim_second_turn_for_processing_session(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    first = store.create_turn(session_key="web:1", content="first")
    second = store.create_turn(session_key="web:1", content="second")
    other = store.create_turn(session_key="web:2", content="other")

    claimed = store.claim_next_pending()
    assert claimed is not None
    assert claimed.id == first.id
    next_claim = store.claim_next_pending()

    assert next_claim is not None
    assert next_claim.id == other.id
    loaded_second = store.get_turn(second.id)
    assert loaded_second is not None
    assert loaded_second.status == TURN_PENDING


def test_turn_store_marks_done_and_then_allows_same_session_next(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    first = store.create_turn(session_key="web:1", content="first")
    second = store.create_turn(session_key="web:1", content="second")

    claimed = store.claim_next_pending()
    assert claimed is not None
    assert claimed.id == first.id
    done = store.mark_done(first.id, "answer")
    next_claim = store.claim_next_pending()

    assert done.status == TURN_DONE
    assert done.answer == "answer"
    assert next_claim is not None
    assert next_claim.id == second.id


def test_turn_store_does_not_overwrite_terminal_turn_with_late_failure(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")
    claimed = store.claim_next_pending()
    assert claimed is not None
    assert claimed.id == turn.id

    done = store.mark_done(turn.id, "answer")
    late_failure = store.mark_failed(turn.id, "late failure")

    assert done.status == TURN_DONE
    assert late_failure.status == TURN_DONE
    assert late_failure.answer == "answer"
    assert late_failure.error is None


def test_turn_store_does_not_mark_pending_turn_terminal(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")

    result = store.mark_failed(turn.id, "not claimed")

    assert result.status == TURN_PENDING
    assert result.error is None
