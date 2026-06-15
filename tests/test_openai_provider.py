import pytest
from dev_utils.openai_provider import (
    OpenAICompatibleProvider,
    OpenAICompatibleProviderConfig,
    load_openai_compatible_config,
)


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def test_load_openai_compatible_config_reads_dotenv_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY='secret-key'",
                'OPENAI_MODEL="debug-model"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = load_openai_compatible_config(env_path)

    assert config == OpenAICompatibleProviderConfig(
        base_url="https://llm.example.test/v1",
        api_key="secret-key",
        model="debug-model",
    )


def test_environment_variables_override_dotenv_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://from-file.example.test/v1",
                "OPENAI_API_KEY=file-key",
                "OPENAI_MODEL=file-model",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://from-env.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setenv("OPENAI_MODEL", "env-model")

    config = load_openai_compatible_config(env_path)

    assert config == OpenAICompatibleProviderConfig(
        base_url="https://from-env.example.test/v1",
        api_key="env-key",
        model="env-model",
    )


def test_load_openai_compatible_config_requires_url_key_and_model(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=secret-key\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_BASE_URL, OPENAI_MODEL"):
        load_openai_compatible_config(env_path)


def test_provider_posts_chat_completion_request_and_returns_assistant_content():
    transport = RecordingTransport(
        {
            "id": "chatcmpl-debug",
            "model": "debug-model",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "hello from model",
                    }
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleProviderConfig(
            base_url="https://llm.example.test/v1/",
            api_key="secret-key",
            model="debug-model",
            timeout_seconds=12,
        ),
        transport=transport,
    )

    result = provider.chat([{"role": "user", "content": "hello"}])

    assert result.content == "hello from model"
    assert result.raw["id"] == "chatcmpl-debug"
    assert result.usage == {
        "prompt_tokens": 3,
        "completion_tokens": 4,
        "total_tokens": 7,
    }
    assert transport.calls == [
        {
            "url": "https://llm.example.test/v1/chat/completions",
            "payload": {
                "model": "debug-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
            "headers": {
                "Authorization": "Bearer secret-key",
                "Content-Type": "application/json",
            },
            "timeout": 12,
        }
    ]


def test_provider_accepts_extra_request_options():
    transport = RecordingTransport(
        {"choices": [{"message": {"content": "short answer"}}]}
    )
    provider = OpenAICompatibleProvider(
        OpenAICompatibleProviderConfig(
            base_url="https://llm.example.test/v1",
            api_key="secret-key",
            model="debug-model",
        ),
        transport=transport,
    )

    provider.chat(
        [{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=20,
    )

    assert transport.calls[0]["payload"] == {
        "model": "debug-model",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0,
        "max_tokens": 20,
    }


def test_provider_rejects_response_without_assistant_content():
    provider = OpenAICompatibleProvider(
        OpenAICompatibleProviderConfig(
            base_url="https://llm.example.test/v1",
            api_key="secret-key",
            model="debug-model",
        ),
        transport=RecordingTransport({"choices": []}),
    )

    with pytest.raises(ValueError, match="assistant content"):
        provider.chat([{"role": "user", "content": "hello"}])
