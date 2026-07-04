from __future__ import annotations

import importlib
from pathlib import Path

import yaml
from amadeus.memory.store import _content_hash


def test_docker_compose_defines_pgvector_postgres_service() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    postgres = compose["services"]["postgres"]

    assert postgres["image"] == "pgvector/pgvector:pg16"
    assert postgres["environment"]["POSTGRES_DB"] == "amadeus"
    assert "healthcheck" in postgres
    assert "postgres-data" in compose["volumes"]


def test_docker_compose_defines_runtime_services_and_workspace_volume() -> None:
    compose = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))

    services = compose["services"]

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    assert services["api"]["ports"] == ["8000:8000"]
    assert services["worker"]["command"] == [
        "python",
        "-m",
        "amadeus.worker.turn_worker",
        "--workspace-root",
        "/workspace",
    ]
    assert "amadeus-workspace" in compose["volumes"]
    assert services["api"]["environment"]["AMADEUS_POSTGRES_DSN"].endswith(
        "@postgres:5432/amadeus"
    )
    assert services["worker"]["environment"]["AMADEUS_POSTGRES_DSN"].endswith(
        "@postgres:5432/amadeus"
    )


def test_initial_migration_creates_vector_extension_and_foundation_tables() -> None:
    migration = Path(
        "migrations/versions/20260704_0001_postgres_foundation.py"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "conversation_sessions" in migration
    assert "conversation_turns" in migration
    assert "memory_items" in migration
    assert "memory_markdown_writes" in migration


def test_content_hash_migration_uses_memory_store_hash_contract() -> None:
    content_hash_migration = importlib.import_module(
        "migrations.versions.20260704_0002_memory_items_content_hash"
    )
    migration = Path(
        "migrations/versions/20260704_0002_memory_items_content_hash.py"
    ).read_text(encoding="utf-8")

    assert "md5(" not in migration
    assert content_hash_migration._memory_content_hash(
        " 默认   用中文 ",
        "preference",
    ) == _content_hash(" 默认   用中文 ", "preference")
