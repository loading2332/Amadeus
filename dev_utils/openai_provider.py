import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from amadeus.context import Message


Transport = Callable[
    [str, dict[str, Any], dict[str, str], float],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class OpenAICompatibleProviderConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 30


@dataclass(frozen=True)
class LLMResponse:
    content: str
    raw: Mapping[str, Any]
    model: str | None = None
    response_id: str | None = None
    usage: Mapping[str, Any] | None = None


class OpenAICompatibleProvider:
    def __init__(
        self,
        config: OpenAICompatibleProviderConfig,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or _urllib_json_transport

    def chat(self, messages: list[Message], **request_options: Any) -> LLMResponse:
        payload = {
            "model": self.config.model,
            "messages": messages,
            **request_options,
        }
        raw = self.transport(
            self._chat_completions_url(),
            payload,
            {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            self.config.timeout_seconds,
        )
        content = _assistant_content(raw)
        return LLMResponse(
            content=content,
            raw=raw,
            model=_optional_string(raw.get("model")),
            response_id=_optional_string(raw.get("id")),
            usage=_optional_mapping(raw.get("usage")),
        )

    def _chat_completions_url(self) -> str:
        return f"{self.config.base_url.rstrip('/')}/chat/completions"


def load_openai_compatible_config(
    env_path: Path = Path(".env"),
) -> OpenAICompatibleProviderConfig:
    file_values = _read_dotenv(env_path)
    values = {
        "OPENAI_BASE_URL": _config_value("OPENAI_BASE_URL", file_values),
        "OPENAI_API_KEY": _config_value("OPENAI_API_KEY", file_values),
        "OPENAI_MODEL": _config_value("OPENAI_MODEL", file_values),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing OpenAI-compatible provider config: {', '.join(missing)}")

    timeout_value = _config_value("OPENAI_TIMEOUT_SECONDS", file_values)
    timeout_seconds = float(timeout_value) if timeout_value else 30

    return OpenAICompatibleProviderConfig(
        base_url=values["OPENAI_BASE_URL"],
        api_key=values["OPENAI_API_KEY"],
        model=values["OPENAI_MODEL"],
        timeout_seconds=timeout_seconds,
    )


def _config_value(name: str, file_values: Mapping[str, str]) -> str | None:
    value = os.environ.get(name, file_values.get(name))
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _read_dotenv(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if key:
            values[key] = _strip_dotenv_quotes(value.strip())
    return values


def _strip_dotenv_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _urllib_json_transport(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> Mapping[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"LLM API request failed with HTTP {error.code}: {body}") from error
    except URLError as error:
        raise RuntimeError(f"LLM API request failed: {error.reason}") from error

    decoded = json.loads(body)
    if not isinstance(decoded, dict):
        raise ValueError("LLM API response must be a JSON object")
    return decoded


def _assistant_content(raw: Mapping[str, Any]) -> str:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LLM API response did not include assistant content")

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise ValueError("LLM API response did not include assistant content")

    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("LLM API response did not include assistant content")

    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("LLM API response did not include assistant content")
    return content


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None
