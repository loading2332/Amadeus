from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from amadeus.events import EventBus
from amadeus.memory import MarkdownMemoryRuntime, build_markdown_memory_runtime
from amadeus.provider import ChatClient, LLMProvider, LLMProviderConfig
from amadeus.runtime import PassiveRuntime
from amadeus.session import SessionManager
from amadeus.workspace import initialize_workspace


def default_workspace_root() -> Path:
    return Path.home() / ".amadeus" / "workspace"


@dataclass(frozen=True)
class RuntimeConfig:
    workspace_root: Path
    provider: LLMProviderConfig
    default_session_key: str = "cli:default"
    memory_keep_count: int = 12


@dataclass
class PassiveApp:
    config: RuntimeConfig
    provider: LLMProvider
    session_manager: SessionManager
    event_bus: EventBus
    memory: MarkdownMemoryRuntime
    runtime: PassiveRuntime

    def close(self) -> None:
        self.session_manager.store.close()


def load_runtime_config(
    *,
    env_path: str | Path = ".env",
    workspace_root: str | Path | None = None,
) -> RuntimeConfig:
    root = Path(workspace_root).resolve() if workspace_root is not None else default_workspace_root()
    file_values = _read_dotenv(Path(env_path))
    values = {
        "OPENAI_BASE_URL": _config_value("OPENAI_BASE_URL", file_values),
        "OPENAI_API_KEY": _config_value("OPENAI_API_KEY", file_values),
        "OPENAI_MODEL": _config_value("OPENAI_MODEL", file_values),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing Amadeus runtime config: {', '.join(missing)}")

    timeout = _float_config("OPENAI_TIMEOUT_SECONDS", file_values, default=90.0)
    max_tokens = _int_config("OPENAI_MAX_TOKENS", file_values, default=2048)
    keep_count = _int_config("AMADEUS_MEMORY_KEEP_COUNT", file_values, default=12)
    session_key = _config_value("AMADEUS_SESSION_KEY", file_values) or "cli:default"
    return RuntimeConfig(
        workspace_root=root,
        provider=LLMProviderConfig(
            api_key=str(values["OPENAI_API_KEY"]),
            base_url=str(values["OPENAI_BASE_URL"]),
            model=str(values["OPENAI_MODEL"]),
            timeout_seconds=timeout,
            max_tokens=max_tokens,
        ),
        default_session_key=session_key,
        memory_keep_count=keep_count,
    )


def build_passive_app(
    *,
    workspace_root: str | Path | None = None,
    env_path: str | Path = ".env",
    client: ChatClient | None = None,
) -> PassiveApp:
    config = load_runtime_config(env_path=env_path, workspace_root=workspace_root)
    initialize_workspace(config.workspace_root)
    provider = LLMProvider(config.provider, client=client)
    session_manager = SessionManager(config.workspace_root)
    event_bus = EventBus()
    memory = build_markdown_memory_runtime(
        workspace_root=config.workspace_root,
        provider=provider,
        model=config.provider.model,
        session_manager=session_manager,
        event_bus=event_bus,
        keep_count=config.memory_keep_count,
    )
    runtime = PassiveRuntime(
        workspace_root=config.workspace_root,
        provider=provider,
        session_manager=session_manager,
        event_bus=event_bus,
    )
    return PassiveApp(
        config=config,
        provider=provider,
        session_manager=session_manager,
        event_bus=event_bus,
        memory=memory,
        runtime=runtime,
    )


def _config_value(name: str, file_values: Mapping[str, str]) -> str | None:
    value = os.environ.get(name, file_values.get(name))
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _int_config(name: str, file_values: Mapping[str, str], *, default: int) -> int:
    value = _config_value(name, file_values)
    if value is None:
        return default
    return int(value)


def _float_config(name: str, file_values: Mapping[str, str], *, default: float) -> float:
    value = _config_value(name, file_values)
    if value is None:
        return default
    return float(value)


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
