from __future__ import annotations

from pathlib import Path

from amadeus.session import PostgresSessionStore
from amadeus.turns import TURN_DONE, TURN_PENDING, PostgresTurnStore
from amadeus.web.app import create_app
from fastapi.testclient import TestClient

from tests.db.postgres_helpers import clean_postgres


def test_postgres_web_session_and_message_api_is_user_scoped() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        app = create_app(store=turn_store, session_store=session_store)
        client = TestClient(app)

        first = client.post("/api/sessions", json={"user_id": 1, "title": "one"})
        second = client.post("/api/sessions", json={"user_id": 2, "title": "two"})

        assert first.status_code == 200
        assert second.status_code == 200
        first_session_id = first.json()["session_id"]
        assert [row["session_id"] for row in client.get("/api/sessions?user_id=1").json()] == [
            first_session_id
        ]
        assert client.get(
            f"/api/sessions/{first_session_id}/messages?user_id=2"
        ).json() == []

        response = client.post(
            "/api/messages",
            json={"user_id": 1, "session_id": first_session_id, "message": "hello"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == TURN_PENDING
        assert payload["user_id"] == 1
        assert payload["session_id"] == first_session_id
    finally:
        db.close()


def test_postgres_web_get_turn_returns_404_for_missing_turn() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        app = create_app(store=turn_store, session_store=session_store)
        client = TestClient(app)

        response = client.get("/api/turns/missing")

        assert response.status_code == 404
        assert response.json() == {"detail": "Turn not found"}
    finally:
        db.close()


def test_postgres_web_sse_endpoint_emits_terminal_turn_and_closes() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        app = create_app(store=turn_store, session_store=session_store)
        client = TestClient(app)
        session = session_store.create_session(user_id=1, title="one")

        turn = turn_store.create_turn(
            user_id=1,
            session_id=int(session["session_id"]),
            content="hello",
            metadata={"channel": "web"},
        )
        assert turn_store.claim_next_pending() is not None
        turn_store.mark_done(turn.id, "assistant reply")

        with client.stream("GET", f"/api/turns/{turn.id}/events") as response:
            body = "".join(response.iter_text())

        assert response.status_code == 200
        assert "event: done" in body
        assert f'"turn_id": "{turn.id}"' in body
        assert f'"status": "{TURN_DONE}"' in body
        assert '"answer": "assistant reply"' in body
    finally:
        db.close()


def test_web_static_uses_structured_server_session_ids() -> None:
    script = Path("amadeus/web/static/app.js").read_text(encoding="utf-8")

    assert "web:${" not in script
    assert "LEGACY" not in script
    assert "session" + "Key" not in script
    assert "session" + "_key" not in script
    assert 'fetch("/api/sessions"' in script
    assert "user_id: state.userId" in script
    assert "session_id: state.sessionId" in script
