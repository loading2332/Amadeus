from __future__ import annotations

import hashlib

import pytest
from amadeus.auth import AuthConfig, AuthService, AuthStore
from amadeus.auth.service import AuthenticationError
from tests.db.postgres_helpers import clean_postgres


def _config() -> AuthConfig:
    return AuthConfig(
        github_client_id="client-id",
        github_client_secret="client-secret",
        public_base_url="https://amadeus.example",
        jwt_secret="test-secret-that-is-at-least-32-bytes",
    )


def test_auth_config_rejects_insecure_or_placeholder_production_values() -> None:
    with pytest.raises(ValueError, match="https"):
        AuthConfig("id", "secret", "http://amadeus.example", "x" * 32)
    with pytest.raises(ValueError, match="Missing"):
        AuthConfig("id", "secret", "https://amadeus.example", "replace-me")
    with pytest.raises(ValueError, match="Missing"):
        AuthConfig(
            "id",
            "secret",
            "https://amadeus.example",
            "replace-me-replace-me-replace-me-replace-me",
        )


def test_identity_mapping_is_stable_and_refresh_rotation_detects_replay() -> None:
    db = clean_postgres()
    try:
        store = AuthStore(db)
        service = AuthService(store, _config())

        first = service.login_github_user("12345")
        same_user = service.login_github_user("12345")
        other_device = service.login_github_user("12345")
        other_identity = service.login_github_user("67890")

        user_id = service.verify_access(first.access_token).user_id
        assert service.verify_access(same_user.access_token).user_id == user_id
        assert service.verify_access(other_identity.access_token).user_id != user_id

        replacement = service.refresh(first.refresh_token)
        assert service.verify_access(replacement.access_token).user_id == user_id
        with pytest.raises(AuthenticationError):
            service.refresh(first.refresh_token)
        with pytest.raises(AuthenticationError):
            service.refresh(replacement.refresh_token)

        # Replay revokes only this rotation chain; an independent device stays valid.
        renewed_other_device = service.refresh(other_device.refresh_token)
        assert service.verify_access(renewed_other_device.access_token).user_id == user_id

        with db.connection() as conn, conn.cursor() as cursor:
            cursor.execute(
                "SELECT token_hash FROM auth_refresh_tokens ORDER BY created_at LIMIT 1"
            )
            stored_hash = str(cursor.fetchone()["token_hash"])
        assert stored_hash != first.refresh_token
        assert stored_hash == hashlib.sha256(
            first.refresh_token.encode("utf-8")
        ).hexdigest()
    finally:
        db.close()


def test_access_token_rejects_tampering() -> None:
    db = clean_postgres()
    try:
        service = AuthService(AuthStore(db), _config())
        tokens = service.login_github_user("12345")
        header, payload, signature = tokens.access_token.split(".")
        changed = "A" if signature[0] != "A" else "B"
        tampered = f"{header}.{payload}.{changed}{signature[1:]}"

        with pytest.raises(AuthenticationError):
            service.verify_access(tampered)
    finally:
        db.close()
