from __future__ import annotations

from dataclasses import MISSING
from dataclasses import fields

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

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.long_term_memory_enabled is False
    assert config.embedding_model is None


def test_long_term_memory_config_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_TOP_K", "5")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.long_term_memory_enabled is True
    assert config.embedding_model == "text-embedding-3-small"
    assert config.long_term_memory_top_k == 5


def test_memory_runtime_config_targets_long_term_memory_db(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_LONG_TERM_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.long_term_memory_enabled is True
    assert config.long_term_memory_db_path == (
        tmp_path / "memory" / "long_term_memory.db"
    )


def test_memory_protocol_dataclasses_match_task1_plan_shape():
    assert [field.name for field in fields(MemoryScope)] == ["channel", "chat_id"]
    assert MemoryScope().channel is None
    assert MemoryScope().chat_id is None
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
        load_runtime_config(workspace_root=tmp_path)
