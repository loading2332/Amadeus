from __future__ import annotations

# ruff: noqa: I001
# bootstrap 是装配文件，import 顺序有语义：memory/session 必须在 mcp 前
# 初始化，否则 amadeus.mcp.__init__ → tools.base → tools.defaults →
# session.store 会与 memory 包形成预存在循环 import。

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from amadeus.app.workspace import initialize_workspace
from amadeus.db import PostgresConfig, PostgresDatabase, normalize_psycopg_dsn
from amadeus.events import EventBus
from amadeus.memory import (
    LLMHypothesisProvider,
    LLMMemoryDecisionProvider,
    LLMMemoryExtractor,
    LongTermMemoryEngine,
    MarkdownMemoryRuntime,
    MemoryMemorizer,
    MemoryRetriever,
    OpenAIEmbeddingConfig,
    OpenAIEmbeddingProvider,
    PostResponseMemoryWorker,
    build_markdown_memory_runtime,
)
from amadeus.memory.postgres import PostgresMemoryStore
from amadeus.plugin.manager import PluginManager
from amadeus.plugin.types import PluginLoadReport
from amadeus.provider import ChatClient, LLMProvider, LLMProviderConfig
from amadeus.runtime.passive import PassiveRuntime
from amadeus.session import PostgresSessionStore, SessionManager
from amadeus.tools.defaults import (
    EditFileTool,
    FetchMessagesTool,
    ListDirTool,
    ReadFileTool,
    SearchMessagesTool,
    WriteFileTool,
)
from amadeus.tools.discovery import ToolSearchTool
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.hooks import ReadOnlyFilesystemHook
from amadeus.tools.memorize import MemorizeTool as RuntimeMemorizeTool
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.registry import ToolRegistry
from amadeus.tools.undo_memory_by_source import (
    UndoMemoryBySourceTool as RuntimeUndoMemoryBySourceTool,
)
# mcp imports 放在 memory/session/tools 之后，避免触发 amadeus.mcp.__init__
# 时机过早导致 session/memory 循环 import（见文件顶部注释）
from amadeus.mcp import (
    McpAddTool,
    McpListTool,
    McpRemoveTool,
    McpServerRegistry,
)


def default_workspace_root() -> Path:
    return Path.home() / ".amadeus" / "workspace"


@dataclass(frozen=True)
class RuntimeConfig:
    workspace_root: Path
    provider: LLMProviderConfig
    postgres_dsn: str
    memory_keep_count: int = 12
    long_term_memory_enabled: bool = False
    default_memory_user_id: int = 1
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    long_term_memory_top_k: int = 8
    memory_hypothesis_retrieval_enabled: bool = True
    memory_hypothesis_timeout_seconds: float = 2.0
    light_model: str | None = None
    mcp_mode: Literal["disabled", "local_trusted"] = "disabled"

class AppState(str, Enum):  # noqa: UP042
    """Explicit lifecycle states for a composed passive application."""

    NEW = "new"
    STARTED = "started"
    CLOSED = "closed"


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
    mcp_server_registry: McpServerRegistry | None = None
    postgres_db: PostgresDatabase | None = None
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
                if first_error is None:
                    first_error = error
            try:
                # 断开所有本地 MCP server 子进程，须在 postgres 关闭前
                if self.mcp_server_registry is not None:
                    await self.mcp_server_registry.shutdown()
            except BaseException as error:
                if first_error is None:
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
            try:
                # The session and memory stores share one pool; close it once
                # after the stores have released their references. Stores that
                # do not own the pool are no-ops on close().
                if self.postgres_db is not None:
                    self.postgres_db.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
            try:
                await _close_runtime_memory_clients(self.runtime.memory_engine)
            except BaseException as error:
                if first_error is None:
                    first_error = error
            try:
                await self.provider.aclose()
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
        "AMADEUS_POSTGRES_DSN": _config_value("AMADEUS_POSTGRES_DSN", file_values),
    }
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise ValueError(f"Missing Amadeus runtime config: {', '.join(missing)}")

    timeout = _float_config("OPENAI_TIMEOUT_SECONDS", file_values, default=90.0)
    max_tokens = _int_config("OPENAI_MAX_TOKENS", file_values, default=2048)
    keep_count = _int_config("AMADEUS_MEMORY_KEEP_COUNT", file_values, default=12)
    long_term_memory_enabled = _bool_config(
        "AMADEUS_LONG_TERM_MEMORY_ENABLED", file_values
    )
    default_memory_user_id = _int_config(
        "AMADEUS_MEMORY_USER_ID", file_values, default=1
    )
    embedding_model = _config_value("OPENAI_EMBEDDING_MODEL", file_values)
    embedding_api_key = (
        _config_value("OPENAI_EMBEDDING_API_KEY", file_values)
        or str(values["OPENAI_API_KEY"])
    )
    embedding_base_url = (
        _config_value("OPENAI_EMBEDDING_BASE_URL", file_values)
        or str(values["OPENAI_BASE_URL"])
    )
    long_term_memory_top_k = _int_config(
        "AMADEUS_LONG_TERM_MEMORY_TOP_K", file_values, default=8
    )
    memory_hypothesis_retrieval_enabled = _bool_config(
        "AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED",
        file_values,
        default=True,
    )
    memory_hypothesis_timeout_seconds = _float_config(
        "AMADEUS_MEMORY_HYPOTHESIS_TIMEOUT_SECONDS",
        file_values,
        default=2.0,
    )
    light_model = _config_value("OPENAI_LIGHT_MODEL", file_values)
    mcp_mode: Literal["disabled", "local_trusted"] = (
        "local_trusted"
        if _config_value("AMADEUS_MCP_MODE", file_values) == "local_trusted"
        else "disabled"
    )
    if long_term_memory_enabled and not embedding_model:
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
        postgres_dsn=str(values["AMADEUS_POSTGRES_DSN"]),
        memory_keep_count=keep_count,
        long_term_memory_enabled=long_term_memory_enabled,
        default_memory_user_id=default_memory_user_id,
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        embedding_base_url=embedding_base_url,
        long_term_memory_top_k=long_term_memory_top_k,
        memory_hypothesis_retrieval_enabled=memory_hypothesis_retrieval_enabled,
        memory_hypothesis_timeout_seconds=memory_hypothesis_timeout_seconds,
        light_model=light_model,
        mcp_mode=mcp_mode,
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
    # Single shared PostgreSQL connection pool for every native-SQL store.
    # ``PostgresDatabase.open`` fails fast when the pgvector extension is
    # missing, so the whole runtime refuses to start without it.
    postgres_db = PostgresDatabase(
        PostgresConfig(dsn=normalize_psycopg_dsn(config.postgres_dsn))
    )
    postgres_db.open()
    session_manager = SessionManager(
        config.workspace_root,
        store=PostgresSessionStore(db=postgres_db),
    )
    event_bus = EventBus()
    tool_registry = ToolRegistry()
    tool_registry.register(
        FetchMessagesTool(store=session_manager.store),
        risk="read-only",
        always_on=True,
    )
    tool_registry.register(
        SearchMessagesTool(store=session_manager.store),
        risk="read-only",
        always_on=True,
    )
    tool_registry.register(ReadFileTool(), risk="read-only", always_on=True)
    tool_registry.register(WriteFileTool(), risk="write", always_on=True)
    tool_registry.register(EditFileTool(), risk="write", always_on=True)
    tool_registry.register(ListDirTool(), risk="read-only", always_on=True)

    tool_executor = ToolExecutor(
        hooks=[ReadOnlyFilesystemHook(workspace_root=config.workspace_root)],
        invoker=tool_registry.execute,
    )
    long_term_memory = None
    if config.long_term_memory_enabled and config.embedding_model:
        embedding_provider = OpenAIEmbeddingProvider(
            OpenAIEmbeddingConfig(
                api_key=str(config.embedding_api_key or config.provider.api_key),
                base_url=config.embedding_base_url or config.provider.base_url,
                model=config.embedding_model,
                timeout_seconds=config.provider.timeout_seconds,
            )
        )
        store = PostgresMemoryStore(
            config.default_memory_user_id,
            db=postgres_db,
        )
        memorizer = MemoryMemorizer(
            store=store,
            embedding_provider=embedding_provider,
        )
        long_term_memory = LongTermMemoryEngine(
            store=store,
            retriever=MemoryRetriever(
                store=store,
                embedding_provider=embedding_provider,
                hypothesis_provider=LLMHypothesisProvider(
                    provider=provider,
                    model=config.light_model or config.provider.model,
                ),
                hypothesis_retrieval_enabled=(
                    config.memory_hypothesis_retrieval_enabled
                ),
                hypothesis_timeout_seconds=config.memory_hypothesis_timeout_seconds,
                top_k=config.long_term_memory_top_k,
            ),
            memorizer=memorizer,
            worker=PostResponseMemoryWorker(
                memorizer=memorizer,
                extractor=LLMMemoryExtractor(
                    provider=provider,
                    model=config.provider.model,
                ),
                decision_provider=LLMMemoryDecisionProvider(
                    memorizer=memorizer,
                    provider=provider,
                    model=config.provider.model,
                ),
            ),
        )
    memory = build_markdown_memory_runtime(
        workspace_root=config.workspace_root,
        provider=provider,
        model=config.provider.model,
        session_manager=session_manager,
        event_bus=event_bus,
        keep_count=config.memory_keep_count,
        long_term_memory=long_term_memory,
        user_id=config.default_memory_user_id,
        db=postgres_db,
    )
    tool_registry.register(
        RecallMemoryTool(memory_engine=long_term_memory),
        risk="read-only",
        always_on=True,
    )
    tool_registry.register(
        RuntimeMemorizeTool(memory_engine=long_term_memory),
        risk="write",
        always_on=True,
    )
    tool_registry.register(
        ForgetMemoryTool(memory_engine=long_term_memory),
        risk="write",
        always_on=True,
    )
    tool_registry.register(
        RuntimeUndoMemoryBySourceTool(memory_engine=long_term_memory),
        risk="write",
        always_on=True,
    )
    tool_registry.register(
        ToolSearchTool(registry=tool_registry),
        risk="read-only",
        always_on=True,
        search_hint="发现 搜索 加载 工具 tool",
    )

    mcp_server_registry: McpServerRegistry | None = None
    if config.mcp_mode == "local_trusted":
        mcp_server_registry = McpServerRegistry(tool_registry=tool_registry)
        tool_registry.register(
            McpAddTool(mcp_registry=mcp_server_registry),
            risk="write",
            always_on=True,
            search_hint="添加 连接 MCP server",
        )
        tool_registry.register(
            McpRemoveTool(mcp_registry=mcp_server_registry),
            risk="write",
            always_on=True,
            search_hint="移除 断开 MCP server",
        )
        tool_registry.register(
            McpListTool(mcp_registry=mcp_server_registry),
            risk="read-only",
            always_on=True,
            search_hint="列出 MCP server",
        )
    runtime = PassiveRuntime(
        workspace_root=config.workspace_root,
        provider=provider,
        session_manager=session_manager,
        event_bus=event_bus,
        memory_engine=long_term_memory,
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
        memory_engine=long_term_memory,
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
        mcp_server_registry=mcp_server_registry,
        postgres_db=postgres_db,
    )


async def _close_runtime_memory_clients(memory_engine: Any | None) -> None:
    if memory_engine is None:
        return
    providers: list[Any] = []
    retriever = getattr(memory_engine, "retriever", None)
    memorizer = getattr(memory_engine, "memorizer", None)
    if retriever is not None:
        providers.append(getattr(retriever, "embedding_provider", None))
    if memorizer is not None:
        providers.append(getattr(memorizer, "embedding_provider", None))
    seen: set[int] = set()
    for provider in providers:
        if provider is None or id(provider) in seen:
            continue
        seen.add(id(provider))
        close = getattr(provider, "aclose", None)
        if callable(close):
            await close()


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


def _bool_config(
    name: str,
    file_values: Mapping[str, str],
    *,
    default: bool = False,
) -> bool:
    value = _config_value(name, file_values)
    if value is None:
        return default
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
