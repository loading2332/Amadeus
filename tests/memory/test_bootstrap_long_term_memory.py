from __future__ import annotations

from dataclasses import MISSING, fields

import pytest
from amadeus.app.bootstrap import load_runtime_config
from amadeus.memory.engine import (
    MemoryContextResult,
    MemoryRecallRequest,
    MemoryScope,
    MemoryWriteRequest,
)


def test_long_term_memory_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.long_term_memory_enabled is False
    assert config.embedding_model is None


def test_long_term_memory_config_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_TOP_K", "5")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.long_term_memory_enabled is True
    assert config.embedding_model == "text-embedding-v4"
    assert config.long_term_memory_top_k == 5
    assert config.memory_lexical_retrieval_enabled is True
    assert config.memory_hypothesis_retrieval_enabled is True
    assert config.memory_hypothesis_timeout_seconds == 2.0
    assert config.light_model is None


def test_memory_hypothesis_retrieval_config_can_be_disabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED", "0")
    monkeypatch.setenv("AMADEUS_MEMORY_HYPOTHESIS_TIMEOUT_SECONDS", "0.75")
    monkeypatch.setenv("OPENAI_LIGHT_MODEL", "light-model")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.memory_hypothesis_retrieval_enabled is False
    assert config.memory_hypothesis_timeout_seconds == 0.75
    assert config.light_model == "light-model"


def test_memory_lexical_retrieval_config_can_be_disabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_MEMORY_LEXICAL_RETRIEVAL_ENABLED", "0")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.memory_lexical_retrieval_enabled is False


def test_long_term_memory_config_supports_dedicated_embedding_provider(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://chat.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "chat-secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://embed.example.test/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "embed-secret")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.embedding_model == "text-embedding-v4"
    assert config.embedding_base_url == "https://embed.example.test/v1"
    assert config.embedding_api_key == "embed-secret"


def test_memory_runtime_config_targets_postgres_memory_user(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-v4")
    monkeypatch.setenv("AMADEUS_MEMORY_USER_ID", "42")

    config = load_runtime_config(
        env_path=tmp_path / ".env",
        workspace_root=tmp_path,
    )

    assert config.long_term_memory_enabled is True
    assert config.default_memory_user_id == 42


def test_memory_protocol_dataclasses_match_task1_plan_shape():
    assert [field.name for field in fields(MemoryScope)] == [
        "channel",
        "chat_id",
        "session",
    ]
    assert MemoryScope().channel is None
    assert MemoryScope().chat_id is None
    assert MemoryScope().session is None
    assert [field.name for field in fields(MemoryRecallRequest)] == [
        "text",
        "intent",
        "memory_types",
        "limit",
        "time_start",
        "time_end",
        "scope",
        "context",
    ]
    assert [field.name for field in fields(MemoryWriteRequest)] == [
        "summary",
        "memory_type",
        "source_ref",
        "happened_at",
        "scope",
        "extra",
    ]
    write_fields = fields(MemoryWriteRequest)
    assert write_fields[1].default is MISSING
    assert write_fields[2].default is MISSING
    assert [field.name for field in fields(MemoryContextResult)] == [
        "text",
        "injected_ids",
        "omitted_ids",
        "trace",
    ]


def test_long_term_memory_enablement_requires_embedding_model(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_EMBEDDING_MODEL"):
        load_runtime_config(
            env_path=tmp_path / ".env",
            workspace_root=tmp_path,
        )
