from amadeus.session import SessionStore
from amadeus.turns import TURN_DONE, TURN_PENDING, TurnStore
from amadeus.web.app import create_app
from fastapi.testclient import TestClient


def _create_legacy_test_app(tmp_path, store: TurnStore):
    return create_app(
        store=store,
        session_store=SessionStore(tmp_path / "sessions.db"),
    )


def test_post_message_creates_pending_turn(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    app = _create_legacy_test_app(tmp_path, store)
    client = TestClient(app)

    response = client.post(
        "/api/messages",
        json={"session_key": "web:1", "message": "hello"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_key"] == "web:1"
    assert payload["status"] == TURN_PENDING
    assert payload["turn_id"]
    turn = store.get_turn(payload["turn_id"])
    assert turn is not None
    assert turn.content == "hello"


def test_get_turn_returns_status_and_terminal_answer(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")
    assert store.claim_next_pending() is not None
    store.mark_done(turn.id, "assistant reply")
    app = _create_legacy_test_app(tmp_path, store)
    client = TestClient(app)

    response = client.get(f"/api/turns/{turn.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == TURN_DONE
    assert payload["answer"] == "assistant reply"


def test_get_missing_turn_returns_404(tmp_path):
    app = _create_legacy_test_app(tmp_path, TurnStore(tmp_path / "turns.db"))
    client = TestClient(app)

    response = client.get("/api/turns/missing")

    assert response.status_code == 404


def test_sse_endpoint_emits_terminal_turn_and_closes(tmp_path):
    store = TurnStore(tmp_path / "turns.db")
    turn = store.create_turn(session_key="web:1", content="hello")
    assert store.claim_next_pending() is not None
    store.mark_done(turn.id, "assistant reply")
    app = _create_legacy_test_app(tmp_path, store)
    client = TestClient(app)

    with client.stream("GET", f"/api/turns/{turn.id}/events") as response:
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: done" in body
    assert '"answer": "assistant reply"' in body
