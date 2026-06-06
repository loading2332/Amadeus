from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from amadeus.bootstrap import build_passive_app, load_runtime_config


class FakeCompletions:
    def __init__(self) -> None:
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def test_load_runtime_config_reads_dotenv_and_environment_overrides(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://from-file.example.test/v1",
                "OPENAI_API_KEY=file-key",
                "OPENAI_MODEL=file-model",
                "OPENAI_MAX_TOKENS=333",
                "AMADEUS_SESSION_KEY=chat:file",
                "AMADEUS_MEMORY_KEEP_COUNT=8",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    config = load_runtime_config(env_path=env_path, workspace_root=tmp_path)

    assert config.provider.api_key == "env-key"
    assert config.provider.base_url == "https://from-file.example.test/v1"
    assert config.provider.model == "env-model"
    assert config.provider.max_tokens == 333
    assert config.default_session_key == "chat:file"
    assert config.memory_keep_count == 8


def test_load_runtime_config_defaults_to_home_workspace(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    config = load_runtime_config(env_path=env_path)

    assert config.workspace_root == tmp_path / ".amadeus" / "workspace"


def test_load_runtime_config_requires_provider_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_BASE_URL, OPENAI_MODEL"):
        load_runtime_config(env_path=env_path, workspace_root=tmp_path)


def test_build_passive_app_runs_real_runtime_and_refreshes_memory(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_MEMORY_KEEP_COUNT=6",
            ]
        ),
        encoding="utf-8",
    )
    client = FakeClient()
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=client,
    )

    result = asyncio.run(
        app.runtime.run_turn(session_key="chat:1", user_message="hello")
    )

    session = app.session_manager.get_or_create("chat:1")
    recent = app.memory.store.read_recent_context()
    assert result.assistant_response == "assistant reply"
    assert [message["id"] for message in session.messages] == ["chat:1:0", "chat:1:1"]
    assert "## Recent Turns" in recent
    assert "[user] hello" in recent
    assert "[a-preview] assistant reply" in recent
