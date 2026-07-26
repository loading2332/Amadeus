from __future__ import annotations

from amadeus.session import PostgresSessionStore
from amadeus.turns import TURN_DONE, TURN_PENDING, PostgresTurnStore, TurnError
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
        assert payload["content"] == "hello"
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


def test_first_turn_sets_a_deterministic_session_title_once() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = client.post("/api/sessions", json={}).json()
        content = f"  {'甲' * 18}\n{'乙' * 18}  "

        created = client.post(
            "/api/messages",
            json={"session_id": session["session_id"], "message": content},
        )
        rows = client.get("/api/sessions").json()

        assert created.status_code == 200
        assert rows[0]["title"] == f"{'甲' * 18} {'乙' * 11}…"
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
            client.post(f"/api/turns/{other_turn.id}/cancel"),
            client.post(f"/api/turns/{other_turn.id}/retry"),
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


def test_postgres_web_delete_session_returns_204_and_cascades() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = client.post("/api/sessions", json={"title": "doomed"}).json()
        session_id = session["session_id"]
        turn_id = client.post(
            "/api/messages",
            json={"session_id": session_id, "message": "hello"},
        ).json()["turn_id"]

        deleted = client.delete(f"/api/sessions/{session_id}")

        assert deleted.status_code == 204
        assert client.get("/api/sessions").json() == []
        assert client.get(f"/api/sessions/{session_id}/messages").status_code == 404
        assert client.get(f"/api/sessions/{session_id}/turns").status_code == 404
        assert turn_store.get_turn(turn_id) is None
    finally:
        db.close()


def test_postgres_web_delete_hides_missing_and_non_owner_sessions_with_same_404() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        other_session = session_store.create_session(user_id=2, title="private")
        other_session_id = int(other_session["session_id"])

        missing = client.delete("/api/sessions/999999")
        foreign = client.delete(f"/api/sessions/{other_session_id}")

        for response in (missing, foreign):
            assert response.status_code == 404
            assert response.json() == {"detail": "Resource not found"}
        assert [
            row["session_id"] for row in session_store.list_sessions(user_id=2)
        ] == [other_session_id]
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
        claimed = turn_store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        turn_store.append_content_snapshot(
            turn.id,
            claimed.lease_id,
            "assistant reply",
        )
        turn_store.mark_done(turn.id, claimed.lease_id, "assistant reply")

        with client.stream("GET", f"/api/turns/{turn.id}/events") as response:
            body = "".join(response.iter_text())

        assert response.status_code == 200
        assert "event: turn_event" in body
        assert "id: 1" in body
        assert f'"turn_id": "{turn.id}"' in body
        assert '"type": "content_snapshot"' in body
        assert '"content": "assistant reply"' in body
        assert '"type": "turn_terminal"' in body
        assert f'"status": "{TURN_DONE}"' in body
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


def test_postgres_web_cancel_retry_timeline_and_active_conflict() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = client.post("/api/sessions", json={"title": "flow"}).json()
        first = client.post(
            "/api/messages",
            json={"session_id": session["session_id"], "message": "hello"},
        )

        conflict = client.post(
            "/api/messages",
            json={"session_id": session["session_id"], "message": "blocked"},
        )
        cancelled = client.post(f"/api/turns/{first.json()['turn_id']}/cancel")
        retried = client.post(f"/api/turns/{first.json()['turn_id']}/retry")
        timeline = client.get(
            f"/api/sessions/{session['session_id']}/turns"
        ).json()

        assert conflict.status_code == 409
        assert conflict.json()["code"] == "active_turn_exists"
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert retried.status_code == 200
        assert retried.json()["retry_of_turn_id"] == first.json()["turn_id"]
        assert [turn["status"] for turn in timeline] == ["cancelled", "pending"]
        assert timeline[0]["turn_id"] == first.json()["turn_id"]
    finally:
        db.close()


def test_postgres_web_sse_reconnect_resumes_after_event_sequence() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = session_store.create_session(user_id=1, title="reconnect")
        turn_store.create_turn(
            user_id=1,
            session_id=int(session["session_id"]),
            content="hello",
        )
        claimed = turn_store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        turn_store.append_content_snapshot(claimed.id, claimed.lease_id, "A")
        turn_store.append_content_snapshot(claimed.id, claimed.lease_id, "AB")
        turn_store.mark_done(claimed.id, claimed.lease_id, "AB")

        with client.stream(
            "GET",
            f"/api/turns/{claimed.id}/events?after_seq=3",
        ) as response:
            body = "".join(response.iter_text())

        assert response.status_code == 200
        assert "id: 1\n" not in body
        assert "id: 2\n" not in body
        assert "id: 3\n" not in body
        assert "id: 4\n" in body
        assert '"content": "AB"' in body
        assert '"type": "turn_terminal"' in body

        with client.stream(
            "GET",
            f"/api/turns/{claimed.id}/events",
            headers={"Last-Event-ID": "4"},
        ) as response:
            header_body = "".join(response.iter_text())

        assert "id: 4\n" not in header_body
        assert '"type": "turn_terminal"' in header_body
    finally:
        db.close()


def test_postgres_web_rejects_cancel_and_retry_for_done_turn() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = session_store.create_session(user_id=1, title="done")
        turn_store.create_turn(
            user_id=1,
            session_id=int(session["session_id"]),
            content="hello",
        )
        claimed = turn_store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        turn_store.mark_done(claimed.id, claimed.lease_id, "answer")

        cancel = client.post(f"/api/turns/{claimed.id}/cancel")
        retry = client.post(f"/api/turns/{claimed.id}/retry")

        assert cancel.status_code == 409
        assert retry.status_code == 409
        assert cancel.json()["code"] == "invalid_turn_transition"
        assert retry.json()["code"] == "invalid_turn_transition"
        persisted = turn_store.get_turn(claimed.id)
        assert persisted is not None
        assert persisted.status == TURN_DONE
    finally:
        db.close()


def test_postgres_web_failed_timeline_and_sse_expose_only_safe_error() -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = _client(session_store, turn_store)
        session = session_store.create_session(user_id=1, title="failed")
        turn_store.create_turn(
            user_id=1,
            session_id=int(session["session_id"]),
            content="hello",
        )
        claimed = turn_store.claim_next_pending()
        assert claimed is not None and claimed.lease_id is not None
        turn_store.append_content_snapshot(claimed.id, claimed.lease_id, "partial")
        turn_store.mark_failed(
            claimed.id,
            claimed.lease_id,
            TurnError("runtime_error", "处理请求时发生错误，请重试", True),
        )

        timeline = client.get(
            f"/api/sessions/{session['session_id']}/turns"
        ).json()
        with client.stream("GET", f"/api/turns/{claimed.id}/events") as response:
            body = "".join(response.iter_text())

        assert timeline[0]["status"] == "failed"
        assert timeline[0]["partial_answer"] == "partial"
        assert timeline[0]["error_code"] == "runtime_error"
        assert timeline[0]["error_message"] == "处理请求时发生错误，请重试"
        assert timeline[0]["error_retryable"] is True
        assert "Traceback" not in body
        assert "api_key" not in body
        assert '"error_code": "runtime_error"' in body
    finally:
        db.close()


def test_web_serves_only_the_injected_react_build(tmp_path) -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        assets = tmp_path / "assets"
        assets.mkdir()
        (tmp_path / "index.html").write_text(
            '<div id="root"></div><script src="/static/assets/app.js"></script>',
            encoding="utf-8",
        )
        (assets / "app.js").write_text(
            "window.__REACT_BUILD__ = true",
            encoding="utf-8",
        )
        app = create_app(
            store=turn_store,
            session_store=session_store,
            owner_user_id=1,
            static_dir=tmp_path,
        )
        client = TestClient(app)

        index = client.get("/")
        asset = client.get("/static/assets/app.js")

        assert index.status_code == 200
        assert '<div id="root"></div>' in index.text
        assert asset.status_code == 200
        assert "__REACT_BUILD__" in asset.text
    finally:
        db.close()


def test_web_has_no_legacy_fallback_when_react_build_is_missing(tmp_path) -> None:
    db = clean_postgres()
    try:
        session_store = PostgresSessionStore(db=db)
        turn_store = PostgresTurnStore(db=db)
        client = TestClient(
            create_app(
                store=turn_store,
                session_store=session_store,
                owner_user_id=1,
                static_dir=tmp_path,
            )
        )

        response = client.get("/")

        assert response.status_code == 404
        assert response.json() == {"detail": "Web page is not available"}
    finally:
        db.close()
