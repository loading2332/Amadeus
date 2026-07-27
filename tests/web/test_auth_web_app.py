from __future__ import annotations

from amadeus.auth import AuthConfig, AuthService, AuthStore
from amadeus.session import PostgresSessionStore
from amadeus.turns import PostgresTurnStore
from amadeus.web.app import create_app
from amadeus.web.auth_routes import ACCESS_COOKIE, REFRESH_COOKIE
from fastapi.testclient import TestClient

from tests.db.postgres_helpers import clean_postgres


def _config() -> AuthConfig:
    return AuthConfig(
        github_client_id="client-id",
        github_client_secret="client-secret",
        public_base_url="https://testserver",
        jwt_secret="test-secret-that-is-at-least-32-bytes",
    )


def _app_client():
    db = clean_postgres()
    config = _config()
    service = AuthService(AuthStore(db), config)
    app = create_app(
        store=PostgresTurnStore(db=db),
        session_store=PostgresSessionStore(db=db),
        owner_user_id=1,
        auth_config=config,
        auth_service=service,
    )
    return db, service, TestClient(app, base_url="https://testserver")


def _authenticate(client: TestClient, service: AuthService, subject: str):
    tokens = service.login_github_user(subject)
    client.cookies.set(
        ACCESS_COOKIE,
        tokens.access_token,
        domain="testserver.local",
        path="/",
    )
    client.cookies.set(
        REFRESH_COOKIE,
        tokens.refresh_token,
        domain="testserver.local",
        path="/auth",
    )
    return tokens


def test_anonymous_chat_is_rejected_but_health_and_oauth_entry_are_public() -> None:
    db, _service, client = _app_client()
    try:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/bootstrap").status_code == 401
        assert client.post("/api/sessions", json={}).status_code == 401
        assert client.get("/openapi.json").status_code == 404

        login = client.get("/auth/github/login", follow_redirects=False)
        assert login.status_code in {302, 307}
        assert login.headers["location"].startswith(
            "https://github.com/login/oauth/authorize"
        )
        assert "state=" in login.headers["location"]
        session_cookie = login.headers["set-cookie"].lower()
        assert "secure" in session_cookie
        assert "httponly" in session_cookie
    finally:
        client.close()
        db.close()


def test_jwt_identity_scopes_resources_and_ignores_guessed_numeric_ids() -> None:
    db, service, first = _app_client()
    second = TestClient(first.app, base_url="https://testserver")
    try:
        _authenticate(first, service, "github-user-1")
        _authenticate(second, service, "github-user-2")
        first_user = first.get("/api/bootstrap").json()["owner_user_id"]
        second_user = second.get("/api/bootstrap").json()["owner_user_id"]
        assert first_user != second_user

        private_session = second.post("/api/sessions", json={}).json()["session_id"]
        assert first.get(f"/api/sessions/{private_session}/messages").status_code == 404
        assert first.post(
            "/api/messages",
            json={
                "session_id": private_session,
                "message": "guessing an id must not authorize access",
            },
        ).status_code == 404
    finally:
        second.close()
        first.close()
        db.close()


def test_refresh_rotates_cookie_and_logout_revokes_server_session() -> None:
    db, service, client = _app_client()
    try:
        original = _authenticate(client, service, "github-user-1")
        refreshed = client.post("/auth/refresh")
        assert refreshed.status_code == 204
        cookies = [header.lower() for header in refreshed.headers.get_list("set-cookie")]
        assert any(
            f"{ACCESS_COOKIE}=" in header
            and "httponly" in header
            and "secure" in header
            and "samesite=lax" in header
            and "path=/" in header
            for header in cookies
        )
        assert any(
            f"{REFRESH_COOKIE}=" in header
            and "httponly" in header
            and "secure" in header
            and "samesite=lax" in header
            and "path=/auth" in header
            for header in cookies
        )

        rotated_refresh = client.cookies.get(REFRESH_COOKIE)
        logout = client.post("/auth/logout")
        assert logout.status_code == 204
        cleared = [header.lower() for header in logout.headers.get_list("set-cookie")]
        assert any(
            f"{ACCESS_COOKIE}=" in header and "max-age=0" in header
            for header in cleared
        )
        assert any(
            f"{REFRESH_COOKIE}=" in header and "max-age=0" in header
            for header in cleared
        )
        assert client.get("/api/bootstrap").status_code == 401
        assert rotated_refresh is not None
        client.cookies.set(
            REFRESH_COOKIE,
            rotated_refresh,
            domain="testserver.local",
            path="/auth",
        )
        assert client.post("/auth/refresh").status_code == 401

        # The initially issued refresh token was rotated and cannot be reused.
        client.cookies.set(
            REFRESH_COOKIE,
            original.refresh_token,
            domain="testserver.local",
            path="/auth",
        )
        assert client.post("/auth/refresh").status_code == 401
    finally:
        client.close()
        db.close()
