from __future__ import annotations

import pytest

from amadeus.bootstrap import load_runtime_config


def test_vector_memory_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("AMADEUS_VECTOR_MEMORY_ENABLED", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.vector_memory_enabled is False
    assert config.embedding_model is None


def test_vector_memory_config_can_be_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_VECTOR_MEMORY_ENABLED", "1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    monkeypatch.setenv("AMADEUS_VECTOR_MEMORY_TOP_K", "5")

    config = load_runtime_config(workspace_root=tmp_path)

    assert config.vector_memory_enabled is True
    assert config.embedding_model == "text-embedding-3-small"
    assert config.vector_memory_top_k == 5


def test_vector_memory_enablement_requires_embedding_model(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_MODEL", "chat-model")
    monkeypatch.setenv("AMADEUS_VECTOR_MEMORY_ENABLED", "1")
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_EMBEDDING_MODEL"):
        load_runtime_config(workspace_root=tmp_path)
