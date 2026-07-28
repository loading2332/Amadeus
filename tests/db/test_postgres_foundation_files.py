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
    assert services["memory-worker"]["command"] == [
        "python",
        "-m",
        "amadeus.worker.post_response_memory_worker",
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
    assert services["memory-worker"]["environment"][
        "AMADEUS_POSTGRES_DSN"
    ].endswith("@postgres:5432/amadeus")


def test_initial_migration_creates_vector_extension_and_foundation_tables() -> None:
    migration = Path(
        "migrations/versions/20260704_0001_postgres_foundation.py"
    ).read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector" in migration
    assert "conversation_sessions" in migration
    assert "conversation_turns" in migration
    assert "memory_items" in migration
    assert "memory_markdown_writes" in migration


def test_turn_streaming_migration_adds_durable_state_and_constraints() -> None:
    migration = Path(
        "migrations/versions/20260718_0005_turn_streaming_runtime.py"
    ).read_text(encoding="utf-8")

    assert "conversation_turn_events" in migration
    assert "uq_conversation_turns_active_session" in migration
    assert "partial_answer" in migration
    assert "heartbeat_at" in migration
    assert "retry_of_turn_id" in migration
    assert "uq_conversation_messages_turn_role" in migration


def test_post_response_memory_job_migration_adds_durable_queue() -> None:
    migration = Path(
        "migrations/versions/20260728_0008_post_response_memory_jobs.py"
    ).read_text(encoding="utf-8")

    assert "post_response_memory_jobs" in migration
    assert "uq_post_response_memory_jobs_turn_id" in migration
    assert "uq_post_response_memory_jobs_processing_session" in migration
    assert "user_message_id" in migration
    assert "assistant_message_id" in migration


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
