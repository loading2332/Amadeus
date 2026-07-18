from __future__ import annotations

from pathlib import Path

from amadeus.session import PostgresSessionStore
from amadeus.turns import TURN_DONE, TURN_PENDING, PostgresTurnStore
from amadeus.web.app import create_app
from fastapi.testclient import TestClient

from tests.db.postgres_helpers import clean_postgres


def _client(
    session_store: PostgresSessionStore,
    turn_store: PostgresTurnStore,
    *,
    owner_user_id: int = 1,
) -> TestClient:
    app = create_app(
        store=turn_store,
        session_store=session_store,
        owner_user_id=owner_user_id,
    )
    return TestClient(app)


def test_postgres_web_bootstrap_and_chat_api_are_owner_scoped() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)

        bootstrap = client.get("/api/bootstrap")
        created = client.post("/api/sessions", json={"title": "one"})

        assert bootstrap.status_code == 200
        assert bootstrap.json() == {"owner_user_id": 1}
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        assert created.json()["user_id"] == 1
        assert [row["session_id"] for row in client.get("/api/sessions").json()] == [
            session_id
        ]
        assert [
            row["session_id"]
            for row in client.get("/api/sessions?user_id=999").json()
        ] == [session_id]
        assert client.get(f"/api/sessions/{session_id}/messages").json() == []

        response = client.post(
            "/api/messages",
            json={
                "session_id": session_id,
                "message": "hello",
                "metadata": {
                    "channel": "telegram",
                    "user_id": 999,
                    "session_id": 999,
                    "turn_id": "spoofed",
                    "custom": "kept",
                },
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == TURN_PENDING
        assert payload["user_id"] == 1
        assert payload["session_id"] == session_id
        assert payload["metadata"] == {"custom": "kept", "channel": "web"}
    finally:
        db.close()


def test_postgres_web_rejects_browser_supplied_user_id() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = session_store.create_session(user_id=1, title="one")

        create_session = client.post(
            "/api/sessions",
            json={"user_id": 2, "title": "spoofed"},
        )
        create_message = client.post(
            "/api/messages",
            json={
                "user_id": 2,
                "session_id": session["session_id"],
                "message": "spoofed",
            },
        )

        assert create_session.status_code == 422
        assert create_message.status_code == 422
    finally:
        db.close()


def test_postgres_web_hides_missing_and_non_owner_resources_with_same_404() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        other_session = session_store.create_session(user_id=2, title="private")
        other_session_id = int(other_session["session_id"])
        other_turn = turn_store.create_turn(
            user_id=2,
            session_id=other_session_id,
            content="private",
        )

        responses = [
            client.get("/api/turns/missing"),
            client.get(f"/api/turns/{other_turn.id}"),
            client.get(f"/api/turns/{other_turn.id}/events"),
            client.get(f"/api/sessions/{other_session_id}/messages"),
            client.post(
                "/api/messages",
                json={"session_id": other_session_id, "message": "intrude"},
            ),
        ]

        for response in responses:
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
    finally:
        db.close()


def test_postgres_web_sse_endpoint_emits_terminal_owner_turn_and_closes() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
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


def test_create_app_requires_explicit_owner_for_injected_stores() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)

        try:
            create_app(store=turn_store, session_store=session_store)
        except ValueError as error:
            assert str(error) == (
                "owner_user_id must be a positive integer when injecting Web stores"
            )
        else:
            raise AssertionError("create_app accepted injected stores without an owner")
    finally:
        db.close()


def test_web_static_bootstraps_owner_and_omits_user_id_from_requests() -> None:
    script = Path("amadeus/web/static/app.js").read_text(encoding="utf-8")

    assert "web:${" not in script
    assert "LEGACY" not in script
    assert "session" + "Key" not in script
    assert "session" + "_key" not in script
    assert 'fetch("/api/bootstrap")' in script
    assert 'fetch("/api/sessions"' in script
    assert "DEFAULT_USER_ID" not in script
    assert "user_id: state.userId" not in script
    assert "session_id: state.sessionId" in script
    assert "userId === ownerUserId" in script
    assert "window.localStorage.removeItem(SESSION_STORAGE)" in script
