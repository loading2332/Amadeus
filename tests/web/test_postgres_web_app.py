from __future__ import annotations

from amadeus.session import PostgresSessionStore
from amadeus.turns import TURN_PENDING, PostgresTurnStore
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
