from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuthConfig:
    github_client_id: str
    github_client_secret: str
    public_base_url: str
    jwt_secret: str
    jwt_issuer: str = "amadeus"
    jwt_audience: str = "amadeus-web"
    access_ttl_seconds: int = 900
    refresh_ttl_seconds: int = 604_800

    def __post_init__(self) -> None:
        missing = [
            name
            for name, value in (
                ("AMADEUS_GITHUB_CLIENT_ID", self.github_client_id),
                ("AMADEUS_GITHUB_CLIENT_SECRET", self.github_client_secret),
                ("AMADEUS_PUBLIC_BASE_URL", self.public_base_url),
                ("AMADEUS_JWT_SECRET", self.jwt_secret),
            )
            if not value.strip() or "replace-me" in value.lower()
        ]
        if missing:
            raise ValueError(f"Missing Amadeus auth config: {', '.join(missing)}")
        if not self.public_base_url.startswith("https://"):
            raise ValueError("AMADEUS_PUBLIC_BASE_URL must use https")
        if len(self.jwt_secret) < 32:
            raise ValueError("AMADEUS_JWT_SECRET must be at least 32 characters")
        if self.access_ttl_seconds <= 0 or self.refresh_ttl_seconds <= 0:
            raise ValueError("Amadeus token TTL values must be positive")


def load_auth_config(env_path: str | Path = ".env") -> AuthConfig:
    values = _read_dotenv(Path(env_path))

    def get(name: str) -> str:
        return os.environ.get(name, values.get(name, "")).strip()

    return AuthConfig(
        github_client_id=get("AMADEUS_GITHUB_CLIENT_ID"),
        github_client_secret=get("AMADEUS_GITHUB_CLIENT_SECRET"),
        public_base_url=get("AMADEUS_PUBLIC_BASE_URL"),
        jwt_secret=get("AMADEUS_JWT_SECRET"),
        jwt_issuer=get("AMADEUS_JWT_ISSUER") or "amadeus",
        jwt_audience=get("AMADEUS_JWT_AUDIENCE") or "amadeus-web",
    )


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values
