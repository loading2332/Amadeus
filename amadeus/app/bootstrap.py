from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from amadeus.app.workspace import initialize_workspace
from amadeus.events import EventBus
from amadeus.memory import (
    MarkdownMemoryRuntime,
    MemoryEngine,
    MemoryWriteRequest,
    build_markdown_memory_runtime,
)
from amadeus.memory.vector import (
    LLMHypothesisProvider,
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
    VectorMemoryEngine,
    VectorMemoryStore,
)
from amadeus.plugin.manager import PluginManager
from amadeus.plugin.types import PluginLoadReport
from amadeus.provider import ChatClient, LLMProvider, LLMProviderConfig
from amadeus.runtime.passive import PassiveRuntime
from amadeus.session.store import SessionManager
from amadeus.tools.defaults import (
    EditFileTool,
    FetchMessagesTool,
    ListDirTool,
    ReadFileTool,
    SearchMessagesTool,
    WriteFileTool,
)
from amadeus.tools.base import ToolResult
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.registry import ToolRegistry


def default_workspace_root() -> Path:
    return Path.home() / ".amadeus" / "workspace"


@dataclass(frozen=True)
class RuntimeConfig:
    workspace_root: Path
    provider: LLMProviderConfig
    default_session_key: str = "cli:default"
    memory_keep_count: int = 12
    vector_memory_enabled: bool = False
    vector_memory_db_path: Path | None = None
    embedding_model: str | None = None
    vector_memory_top_k: int = 8


class AppState(str, Enum):  # noqa: UP042
    """Explicit lifecycle states for a composed passive application."""

    NEW = "new"
    STARTED = "started"
    CLOSED = "closed"


@dataclass
class MemorizeTool:
    memory_engine: MemoryEngine | None
    name: str = "memorize"
    description: str = "将已核对的事实写入长期记忆。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "memory_type": {"type": "string"},
                "source_ref": {"type": "string"},
                "happened_at": {"type": "string"},
            },
            "required": ["summary", "source_ref"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={"error": "vector memory is not configured"},
                is_error=True,
            )

        request = MemoryWriteRequest(
            summary=str(kwargs.get("summary") or "").strip(),
            source_ref=str(kwargs.get("source_ref") or "").strip(),
            happened_at=str(kwargs.get("happened_at") or "").strip() or None,
            memory_type=str(kwargs.get("memory_type") or "event").strip() or "event",
        )
        if not request.summary or not request.source_ref:
            return ToolResult(
                tool_name=self.name,
                output={"error": "summary and source_ref are required"},
                is_error=True,
            )

        result = await self.memory_engine.memorize(request)
        return ToolResult(
            tool_name=self.name,
            output={
                "item_id": result.item_id,
                "status": result.status,
                "trace": dict(result.trace),
            },
            is_error=result.status not in {"created", "accepted"},
        )


@dataclass
class UndoMemoryBySourceTool:
    memory_engine: MemoryEngine | None
    name: str = "undo_memory_by_source"
    description: str = "按 source_ref 撤销对应长期记忆。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"source_ref": {"type": "string"}},
            "required": ["source_ref"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        if self.memory_engine is None:
            return ToolResult(
                tool_name=self.name,
                output={"error": "vector memory is not configured"},
                is_error=True,
            )

        source_ref = str(kwargs.get("source_ref") or "").strip()
        if not source_ref:
            return ToolResult(
                tool_name=self.name,
                output={"error": "source_ref is required"},
                is_error=True,
            )

        result = self.memory_engine.undo_by_source(source_ref)

        return ToolResult(
            tool_name=self.name,
            output={
                "source_ref": source_ref,
                "status": result.status,
                "affected_ids": result.affected_ids,
                "missing_ids": result.missing_ids,
                "items": result.items,
                "trace": dict(result.trace),
            },
            is_error=not result.accepted,
        )


@dataclass
class PassiveApp:
    config: RuntimeConfig
    provider: LLMProvider
    session_manager: SessionManager
    event_bus: EventBus
    memory: MarkdownMemoryRuntime
    runtime: PassiveRuntime
    tool_registry: ToolRegistry
    tool_executor: ToolExecutor
    plugin_manager: PluginManager
    _state: AppState = field(default=AppState.NEW, init=False)
    _lifecycle_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )
    _plugin_report: PluginLoadReport | None = field(default=None, init=False, repr=False)

    async def start(self) -> PluginLoadReport:
        """Load plugins once after all host dependencies have been composed."""
        async with self._lifecycle_lock:
            if self._state is AppState.CLOSED:
                raise RuntimeError("PassiveApp is closed; build a new app to restart")
            if self._state is AppState.STARTED:
                if self._plugin_report is None:  # pragma: no cover - state invariant
                    raise RuntimeError("PassiveApp started without a plugin load report")
                return self._plugin_report
            try:
                report = await self.plugin_manager.load_all()
                self.runtime.set_before_turn_plugin_modules(
                    self.plugin_manager.before_turn_modules
                )
                self.runtime.set_prompt_render_plugin_modules(
                    self.plugin_manager.prompt_render_modules
                )
                self.runtime.set_before_reasoning_plugin_modules(
                    self.plugin_manager.before_reasoning_modules
                )
                self.runtime.set_before_step_plugin_modules(
                    self.plugin_manager.before_step_modules
                )
                self.runtime.set_after_step_plugin_modules(
                    self.plugin_manager.after_step_modules
                )
                self.runtime.set_after_reasoning_plugin_modules(
                    self.plugin_manager.after_reasoning_modules
                )
                self.runtime.set_after_turn_plugin_modules(
                    self.plugin_manager.after_turn_modules
                )
            except BaseException:
                try:
                    self.runtime.set_before_turn_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_prompt_render_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_before_reasoning_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_before_step_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_after_step_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_after_reasoning_plugin_modules([])
                except BaseException:
                    pass
                try:
                    self.runtime.set_after_turn_plugin_modules([])
                except BaseException:
                    pass
                try:
                    await self.plugin_manager.terminate_all()
                except BaseException:
                    pass
                raise
            self._plugin_report = report
            self._state = AppState.STARTED
            return report

    async def aclose(self) -> None:
        """Terminate plugins before closing their shared session dependency."""
        async with self._lifecycle_lock:
            if self._state is AppState.CLOSED:
                return

            first_error: BaseException | None = None
            try:
                await self.plugin_manager.terminate_all()
            except BaseException as error:
                first_error = error
            try:
                self.runtime.set_before_turn_plugin_modules([])
            except BaseException as error:
                if first_error is None:
                    first_error = error
            try:
                self.runtime.set_prompt_render_plugin_modules([])
            except BaseException as error:
                if first_error is None:
                    first_error = error
            for reset in (
                self.runtime.set_before_reasoning_plugin_modules,
                self.runtime.set_before_step_plugin_modules,
                self.runtime.set_after_step_plugin_modules,
                self.runtime.set_after_reasoning_plugin_modules,
                self.runtime.set_after_turn_plugin_modules,
            ):
                try:
                    reset([])
                except BaseException as error:
                    if first_error is None:
                        first_error = error
            try:
                self.session_manager.store.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
            finally:
                self._state = AppState.CLOSED

            if first_error is not None:
                raise first_error


def load_runtime_config(
    *,
    env_path: str | Path = ".env",
    workspace_root: str | Path | None = None,
) -> RuntimeConfig:
    root = (
        Path(workspace_root).resolve()
        if workspace_root is not None
        else default_workspace_root()
    )
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
    vector_memory_enabled = _bool_config("AMADEUS_VECTOR_MEMORY_ENABLED", file_values)
    vector_memory_db_path = root / "memory" / "memory2.db"
    embedding_model = _config_value("OPENAI_EMBEDDING_MODEL", file_values)
    vector_memory_top_k = _int_config(
        "AMADEUS_VECTOR_MEMORY_TOP_K", file_values, default=8
    )
    if vector_memory_enabled and not embedding_model:
        raise ValueError("Missing Amadeus runtime config: OPENAI_EMBEDDING_MODEL")
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
        vector_memory_enabled=vector_memory_enabled,
        vector_memory_db_path=vector_memory_db_path,
        embedding_model=embedding_model,
        vector_memory_top_k=vector_memory_top_k,
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
    tool_registry = ToolRegistry()
    tool_registry.register(FetchMessagesTool(store=session_manager.store))
    tool_registry.register(SearchMessagesTool(store=session_manager.store))
    tool_registry.register(ReadFileTool())
    tool_registry.register(WriteFileTool())
    tool_registry.register(EditFileTool())
    tool_registry.register(ListDirTool())
    tool_executor = ToolExecutor(registry=tool_registry)
    vector_memory = None
    if (
        config.vector_memory_enabled
        and config.embedding_model
        and config.vector_memory_db_path is not None
    ):
        vector_memory = VectorMemoryEngine(
            store=VectorMemoryStore(config.vector_memory_db_path),
            embedding_provider=OpenAIEmbeddingProvider(
                OpenAIEmbeddingConfig(
                    api_key=config.provider.api_key,
                    base_url=config.provider.base_url,
                    model=config.embedding_model,
                    timeout_seconds=config.provider.timeout_seconds,
                )
            ),
            hypothesis_provider=LLMHypothesisProvider(provider=provider),
            top_k=config.vector_memory_top_k,
        )
    memory = build_markdown_memory_runtime(
        workspace_root=config.workspace_root,
        provider=provider,
        model=config.provider.model,
        session_manager=session_manager,
        event_bus=event_bus,
        keep_count=config.memory_keep_count,
        vector_memory=vector_memory,
    )
    tool_registry.register(RecallMemoryTool(memory_engine=vector_memory))
    tool_registry.register(MemorizeTool(memory_engine=vector_memory))
    tool_registry.register(ForgetMemoryTool(memory_engine=vector_memory))
    tool_registry.register(UndoMemoryBySourceTool(memory_engine=vector_memory))
    runtime = PassiveRuntime(
        workspace_root=config.workspace_root,
        provider=provider,
        session_manager=session_manager,
        event_bus=event_bus,
        memory_engine=vector_memory,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
    )
    plugin_manager = PluginManager(
        plugin_roots=[
            ("builtin", Path(__file__).resolve().parents[1] / "builtin_plugins"),
            ("workspace", config.workspace_root / "plugins"),
        ],
        event_bus=event_bus,
        tool_registry=tool_registry,
        workspace=config.workspace_root,
        session_manager=session_manager,
        memory_engine=vector_memory,
    )
    return PassiveApp(
        config=config,
        provider=provider,
        session_manager=session_manager,
        event_bus=event_bus,
        memory=memory,
        runtime=runtime,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        plugin_manager=plugin_manager,
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


def _bool_config(name: str, file_values: Mapping[str, str]) -> bool:
    value = _config_value(name, file_values)
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


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
