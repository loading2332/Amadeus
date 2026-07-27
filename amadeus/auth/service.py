from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import jwt

from amadeus.auth.config import AuthConfig
from amadeus.auth.store import RefreshResult


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True)
class CurrentUser:
    user_id: int


@dataclass(frozen=True)
class LoginTokens:
    access_token: str
    refresh_token: str


class AuthStoreProtocol(Protocol):
    def get_or_create_identity(self, provider: str, subject: str) -> int: ...

    def create_refresh_token(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> None: ...

    def rotate_refresh_token(
        self,
        token_hash: str,
        replacement_hash: str,
        expires_at: datetime,
    ) -> RefreshResult | None: ...

    def revoke_refresh_token(self, token_hash: str) -> None: ...


class AuthService:
    def __init__(self, store: AuthStoreProtocol, config: AuthConfig) -> None:
        self.store = store
        self.config = config

    def login_github_user(self, subject: str) -> LoginTokens:
        user_id = self.store.get_or_create_identity("github", subject)
        return self._issue(user_id)

    def verify_access(self, token: str) -> CurrentUser:
        try:
            claims = jwt.decode(
                token,
                self.config.jwt_secret,
                algorithms=["HS256"],
                audience=self.config.jwt_audience,
                issuer=self.config.jwt_issuer,
                options={"require": ["sub", "iat", "exp", "iss", "aud"]},
            )
            user_id = int(claims["sub"])
        except (jwt.PyJWTError, ValueError, TypeError) as error:
            raise AuthenticationError("Invalid access token") from error
        if user_id <= 0:
            raise AuthenticationError("Invalid access token")
        return CurrentUser(user_id=user_id)

    def refresh(self, token: str) -> LoginTokens:
        replacement = secrets.token_urlsafe(48)
        result = self.store.rotate_refresh_token(
            _hash_token(token), _hash_token(replacement), self._expiry()
        )
        if result is None:
            raise AuthenticationError("Invalid refresh token")
        return LoginTokens(
            access_token=self._access(result.user_id),
            refresh_token=replacement,
        )

    def logout(self, token: str | None) -> None:
        if token:
            self.store.revoke_refresh_token(_hash_token(token))

    def _issue(self, user_id: int) -> LoginTokens:
        raw_refresh = secrets.token_urlsafe(48)
        self.store.create_refresh_token(user_id, _hash_token(raw_refresh), self._expiry())
        return LoginTokens(access_token=self._access(user_id), refresh_token=raw_refresh)

    def _access(self, user_id: int) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "iss": self.config.jwt_issuer,
                "aud": self.config.jwt_audience,
                "iat": now,
                "exp": now + timedelta(seconds=self.config.access_ttl_seconds),
                "jti": str(uuid.uuid4()),
            },
            self.config.jwt_secret,
            algorithm="HS256",
        )

    def _expiry(self) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=self.config.refresh_ttl_seconds)

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
