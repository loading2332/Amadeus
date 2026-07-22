from __future__ import annotations

import asyncio
import inspect
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, get_type_hints

import pytest
from amadeus.app.bootstrap import AppState, build_passive_app, load_runtime_config
from amadeus.memory.engine import (
    MemoryEngine,
    MemoryRecallRequest,
    MemoryWriteRequest,
)
from amadeus.plugin import Plugin, plugin_registry
from amadeus.plugin.types import PluginLoadReport
from amadeus.provider import ChatCompletionsClient, ChatNamespace
from amadeus.runtime.lifecycle import BeforeTurnContext
from amadeus.session.identity import SessionRef
from amadeus.tools.forget_memory import ForgetMemoryTool
from amadeus.tools.memorize import MemorizeTool
from amadeus.tools.recall_memory import RecallMemoryTool
from amadeus.tools.undo_memory_by_source import UndoMemoryBySourceTool

from tests.db.postgres_helpers import clean_postgres

EMBEDDING_DIM = 1024


def _embedding(values: list[float]) -> list[float]:
    return [float(v) for v in values] + [0.0] * (EMBEDDING_DIM - len(values))


def _session(session_id: int = 1, *, user_id: int = 1) -> SessionRef:
    return SessionRef(user_id=user_id, session_id=session_id)


class FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(
            id="resp",
            model=kwargs["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(content="assistant reply"))],
            usage={},
        )


@dataclass
class FakeChatNamespace:
    completions: ChatCompletionsClient


class FakeClient:
    def __init__(self) -> None:
        self.completions = FakeCompletions()
        self.chat: ChatNamespace = FakeChatNamespace(completions=self.completions)


class ControlledPluginManager:
    def __init__(self) -> None:
        self.load_calls = 0
        self.terminate_calls = 0
        self.report = PluginLoadReport(())
        self.load_entered: asyncio.Event | None = None
        self.release_load: asyncio.Event | None = None
        self.load_error: BaseException | None = None
        self.terminate_error: BaseException | None = None
        self.before_turn_modules: list[object] = []
        self.prompt_render_modules: list[object] = []
        self.before_reasoning_modules: list[object] = []
        self.before_step_modules: list[object] = []
        self.after_step_modules: list[object] = []
        self.after_reasoning_modules: list[object] = []
        self.after_turn_modules: list[object] = []

    async def load_all(self) -> PluginLoadReport:
        self.load_calls += 1
        if self.load_entered is not None:
            self.load_entered.set()
        if self.release_load is not None:
            await self.release_load.wait()
        if self.load_error is not None:
            error = self.load_error
            self.load_error = None
            raise error
        return self.report

    async def terminate_all(self) -> None:
        self.terminate_calls += 1
        if self.terminate_error is not None:
            raise self.terminate_error


def _env_path(tmp_path: Path) -> Path:
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
    return env_path


def _app_with_controlled_manager(tmp_path):
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )
    manager = ControlledPluginManager()
    app.plugin_manager = manager  # type: ignore[assignment]
    return app, manager


def test_load_runtime_config_reads_dotenv_and_environment_overrides(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://from-file.example.test/v1",
                "OPENAI_API_KEY=file-key",
                "OPENAI_MODEL=file-model",
                "OPENAI_MAX_TOKENS=333",
                "AMADEUS_OWNER_USER_ID=7",
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
    assert config.postgres_dsn == "postgresql://amadeus:amadeus@localhost:5432/amadeus"
    assert config.owner_user_id == 7
    assert config.memory_keep_count == 8
    assert config.memory_optimizer_enabled is True
    assert config.memory_optimizer_interval_seconds == 64_800
    assert config.turn_stream_flush_characters == 128
    assert config.turn_stream_flush_interval_seconds == 0.1
    assert config.turn_heartbeat_interval_seconds == 10.0
    assert config.turn_stale_after_seconds == 120.0


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
    assert config.owner_user_id == 1


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_load_runtime_config_requires_positive_owner_user_id(
    tmp_path,
    monkeypatch,
    value,
):
    monkeypatch.setenv("AMADEUS_OWNER_USER_ID", value)

    with pytest.raises(
        ValueError,
        match="AMADEUS_OWNER_USER_ID must be a positive integer",
    ):
        load_runtime_config(
            env_path=_env_path(tmp_path),
            workspace_root=tmp_path,
        )


def test_load_runtime_config_requires_stale_timeout_after_heartbeat(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AMADEUS_TURN_HEARTBEAT_INTERVAL_SECONDS", "10")
    monkeypatch.setenv("AMADEUS_TURN_STALE_AFTER_SECONDS", "10")

    with pytest.raises(
        ValueError,
        match="AMADEUS_TURN_STALE_AFTER_SECONDS must be greater",
    ):
        load_runtime_config(
            env_path=_env_path(tmp_path),
            workspace_root=tmp_path,
        )


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_load_runtime_config_requires_positive_memory_optimizer_interval(
    tmp_path,
    monkeypatch,
    value,
):
    monkeypatch.setenv("AMADEUS_MEMORY_OPTIMIZER_INTERVAL_SECONDS", value)

    with pytest.raises(
        ValueError,
        match="AMADEUS_MEMORY_OPTIMIZER_INTERVAL_SECONDS must be a positive integer",
    ):
        load_runtime_config(
            env_path=_env_path(tmp_path),
            workspace_root=tmp_path,
        )


@pytest.mark.parametrize(
    ("configured_mode", "expected_mode"),
    [
        (None, "disabled"),
        ("stdio", "disabled"),
        ("LOCAL_TRUSTED", "disabled"),
        ("local_trusted", "local_trusted"),
    ],
)
def test_load_runtime_config_normalizes_mcp_mode(
    tmp_path,
    monkeypatch,
    configured_mode,
    expected_mode,
):
    env_path = _env_path(tmp_path)
    if configured_mode is None:
        monkeypatch.delenv("AMADEUS_MCP_MODE", raising=False)
    else:
        monkeypatch.setenv("AMADEUS_MCP_MODE", configured_mode)

    config = load_runtime_config(env_path=env_path, workspace_root=tmp_path)

    assert config.mcp_mode == expected_mode


def test_load_runtime_config_requires_provider_values(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=secret\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    with pytest.raises(ValueError, match="OPENAI_BASE_URL, OPENAI_MODEL"):
        load_runtime_config(env_path=env_path, workspace_root=tmp_path)


def test_load_runtime_config_requires_postgres_dsn(tmp_path, monkeypatch):
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
    monkeypatch.delenv("AMADEUS_POSTGRES_DSN", raising=False)

    with pytest.raises(ValueError, match="AMADEUS_POSTGRES_DSN"):
        load_runtime_config(env_path=env_path, workspace_root=tmp_path)


def test_build_passive_app_runs_real_runtime_and_refreshes_memory(tmp_path):
    clean_postgres().close()
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

    async def scenario():
        await app.start()
        try:
            return await app.runtime.run_turn(
                session=_session(),
                user_message="hello",
            )
        finally:
            await app.aclose()

    result = asyncio.run(scenario())

    session = app.session_manager.get_or_create(_session())
    recent = app.memory.store.read_recent_context()
    assert result.assistant_response == "assistant reply"
    assert [message["id"] for message in session.messages] == [
        "session:1:1:0",
        "session:1:1:1",
    ]
    assert "## Recent Turns" in recent
    assert "[user] hello" in recent
    assert "[a-preview] assistant reply" in recent


def test_build_passive_app_registers_memory_tools_without_correct_memory(tmp_path):
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )

    tool_names = set(app.tool_registry.names())

    assert "recall_memory" in tool_names
    assert "memorize" in tool_names
    assert "forget_memory" in tool_names
    assert "undo_memory_by_source" in tool_names
    assert "correct_memory" not in tool_names

    asyncio.run(app.aclose())


def test_build_passive_app_runs_post_response_memory_worker_when_long_term_memory_enabled(
    tmp_path,
    monkeypatch,
):
    clean_postgres().close()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                "OPENAI_EMBEDDING_MODEL=fake-embedding",
            ]
        ),
        encoding="utf-8",
    )

    class StableEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            if "中文" in text:
                return _embedding([1.0, 0.0, 0.0])
            return _embedding([0.8, 0.2, 0.0])

    class FakeExtractor:
        def __init__(self, *, provider, model: str) -> None:
            self.provider = provider
            self.model = model

        async def extract(self, *, session: SessionRef, messages: list[dict[str, Any]]):
            assert session == _session()
            return [
                {
                    "summary": "用户明确要求长期记住：默认用中文",
                    "memory_type": "preference",
                    "source_ref": '["session:1:1:0"]#h:extract',
                }
            ]

    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.LLMMemoryExtractor",
        FakeExtractor,
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=FakeClient(),
    )

    async def scenario():
        result = await app.runtime.run_turn(
            session=_session(),
            user_message="以后默认中文回复",
        )
        assert app.runtime.memory_engine is not None
        recalled = await app.runtime.memory_engine.recall(
            MemoryRecallRequest(
                text="默认用中文",
                memory_types=("preference",),
            )
        )
        await app.aclose()
        return result, recalled

    result, recalled = asyncio.run(scenario())

    assert result.memory_trace["post_response"]["written_count"] == 1
    assert recalled.records


def test_build_passive_app_uses_dedicated_embedding_provider_config(
    tmp_path,
    monkeypatch,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://chat.example.test/v1",
                "OPENAI_API_KEY=chat-secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                "OPENAI_EMBEDDING_MODEL=text-embedding-v4",
                "OPENAI_EMBEDDING_BASE_URL=https://embed.example.test/compatible-mode/v1",
                "OPENAI_EMBEDDING_API_KEY=embed-secret",
            ]
        ),
        encoding="utf-8",
    )
    captured: dict[str, Any] = {}

    class StableEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            return _embedding([0.8, 0.2, 0.0])

    def fake_embedding_provider(config):
        captured["api_key"] = config.api_key
        captured["base_url"] = config.base_url
        captured["model"] = config.model
        captured["timeout_seconds"] = config.timeout_seconds
        return StableEmbeddingProvider()

    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        fake_embedding_provider,
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=FakeClient(),
    )
    try:
        assert app.runtime.memory_engine is not None
        assert captured == {
            "api_key": "embed-secret",
            "base_url": "https://embed.example.test/compatible-mode/v1",
            "model": "text-embedding-v4",
            "timeout_seconds": 90.0,
        }
    finally:
        asyncio.run(app.aclose())

def test_memory_enabled_runtime_recall_forget_and_undo_flow(tmp_path, monkeypatch):
    clean_postgres().close()
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "OPENAI_BASE_URL=https://llm.example.test/v1",
                "OPENAI_API_KEY=secret",
                "OPENAI_MODEL=fake-model",
                "AMADEUS_LONG_TERM_MEMORY_ENABLED=1",
                "OPENAI_EMBEDDING_MODEL=text-embedding-v4",
            ]
        ),
        encoding="utf-8",
    )

    class StableEmbeddingProvider:
        async def embed(self, text: str) -> list[float]:
            if "中文" in text:
                return _embedding([1.0, 0.0, 0.0])
            return _embedding([0.8, 0.2, 0.0])

    class FakeExtractor:
        def __init__(self, *, provider, model: str) -> None:
            self.provider = provider
            self.model = model

        async def extract(self, *, session: SessionRef, messages: list[dict[str, Any]]):
            assert session == _session()
            return []

    monkeypatch.setattr(
        "amadeus.app.bootstrap.OpenAIEmbeddingProvider",
        lambda _config: StableEmbeddingProvider(),
    )
    monkeypatch.setattr(
        "amadeus.app.bootstrap.LLMMemoryExtractor",
        FakeExtractor,
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=env_path,
        client=FakeClient(),
    )
    engine = app.runtime.memory_engine
    assert engine is not None

    async def scenario():
        try:
            remembered = await MemorizeTool(memory_engine=engine).execute(
                summary="用户长期偏好中文输出",
                memory_type="preference",
                source_ref='["session:1:1:0"]#h:pref',
            )
            replacement = await engine.memorizer.replace(
                target_id=remembered.output["memory_id"],
                request=MemoryWriteRequest(
                    summary="用户长期偏好英文输出",
                    memory_type="preference",
                    source_ref='["session:1:1:1"]#h:new',
                ),
            )
            restored = UndoMemoryBySourceTool(memory_engine=engine).execute(
                source_ref='["session:1:1:1"]#h:new'
            )
            recalled = await RecallMemoryTool(memory_engine=engine).execute(
                query="中文输出"
            )
            turn = await app.runtime.run_turn(
                session=_session(),
                user_message="继续这个任务",
            )
            forgotten = ForgetMemoryTool(memory_engine=engine).execute(
                ids=[remembered.output["memory_id"]]
            )
            return remembered, replacement, restored, recalled, turn, forgotten
        finally:
            await app.aclose()

    remembered, replacement, restored, recalled, turn, forgotten = asyncio.run(scenario())

    assert remembered.output["memory_id"]
    assert replacement.accepted is True
    assert remembered.output["memory_id"] in restored.output["restored_ids"]
    assert forgotten.output["superseded_ids"] == [remembered.output["memory_id"]]
    assert remembered.output["memory_id"] in [
        item["id"] for item in recalled.output["items"]
    ]
    assert turn.memory_trace["injected_ids"]
    assert "用户长期偏好中文输出" in (turn.context.messages[-2]["content"])


def test_memory_engine_protocol_exposes_task1_plan_methods():
    public_methods = {
        name
        for name, value in inspect.getmembers(MemoryEngine)
        if inspect.isfunction(value) and not name.startswith("_")
    }

    assert public_methods == {
        "recall",
        "memorize",
        "forget",
        "undo_by_source",
        "build_context",
        "run_post_response",
    }
    assert inspect.iscoroutinefunction(MemoryEngine.recall)
    assert inspect.iscoroutinefunction(MemoryEngine.memorize)
    assert not inspect.iscoroutinefunction(MemoryEngine.forget)
    assert not inspect.iscoroutinefunction(MemoryEngine.undo_by_source)
    assert inspect.iscoroutinefunction(MemoryEngine.build_context)
    assert inspect.iscoroutinefunction(MemoryEngine.run_post_response)
    assert list(inspect.signature(MemoryEngine.recall).parameters) == [
        "self",
        "request",
    ]
    assert list(inspect.signature(MemoryEngine.memorize).parameters) == [
        "self",
        "request",
    ]
    assert list(inspect.signature(MemoryEngine.forget).parameters) == [
        "self",
        "ids",
    ]
    assert list(inspect.signature(MemoryEngine.undo_by_source).parameters) == [
        "self",
        "source_ref",
    ]
    assert list(inspect.signature(MemoryEngine.build_context).parameters) == [
        "self",
        "request",
    ]
    assert (
        get_type_hints(MemoryEngine.build_context)["request"] is MemoryRecallRequest
    )
    assert list(inspect.signature(MemoryEngine.run_post_response).parameters) == [
        "self",
        "session",
        "messages",
        "explicit_memory_ids",
    ]


def test_build_is_composition_only_and_defers_plugin_import(tmp_path):
    marker = tmp_path / "imported.txt"
    plugin_dir = tmp_path / "plugins" / "observable"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('imported')\n",
        encoding="utf-8",
    )

    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )

    assert app._state is AppState.NEW
    assert not marker.exists()
    asyncio.run(app.aclose())


def test_user_plugin_changes_real_turn_prompt_and_is_unbound_on_close(tmp_path):
    fixture = (
        Path(__file__).parents[1]
        / "fixtures"
        / "bootstrap_plugins"
        / "prompt_marker"
    )
    shutil.copytree(fixture, tmp_path / "plugins" / "prompt_marker")
    client = FakeClient()
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=client,
    )

    async def scenario() -> None:
        try:
            assert app.plugin_manager.loaded_names == []
            report = await app.start()
            assert ("prompt_marker", "workspace") in [
                (record.name, record.source) for record in report.loaded
            ]

            result = await app.runtime.run_turn(
                session=_session(21),
                user_message="hello",
            )
            assert len(client.completions.calls) == 1
            messages = client.completions.calls[0]["messages"]
            assert messages[-1] == {"role": "user", "content": "hello"}
            context_frames = [
                message
                for message in messages[:-1]
                if message["role"] == "user"
                and str(message["content"]).lstrip().startswith("<system-reminder")
            ]
            assert len(context_frames) == 1
            assert "loaded through PassiveApp.start" in str(
                context_frames[0]["content"]
            )
            assert all(
                "loaded through PassiveApp.start" not in str(message["content"])
                for message in messages
                if message is not context_frames[0]
            )
            assert "prompt render module reached provider" in str(
                messages[0]["content"]
            )
            assert result.assistant_response == "assistant reply"
        finally:
            await app.aclose()

        assert app.plugin_manager.loaded_names == []
        after_close = await app.runtime.lifecycle.before_turn(
            BeforeTurnContext(
                session=_session(22),
                user_message="hello again",
                history=[],
                retrieved_memory=None,
                runtime_metadata={},
            )
        )
        assert "plugin_marker" not in after_close.runtime_metadata

    asyncio.run(scenario())


def test_build_wires_plugin_manager_roots_and_dependency_identity(tmp_path, monkeypatch):
    captured: dict[str, Any] = {}

    class CapturingManager(ControlledPluginManager):
        def __init__(self, plugin_roots, event_bus, tool_registry, workspace,
                     session_manager=None, memory_engine=None):
            super().__init__()
            captured.update(
                plugin_roots=plugin_roots,
                event_bus=event_bus,
                tool_registry=tool_registry,
                workspace=workspace,
                session_manager=session_manager,
                memory_engine=memory_engine,
            )

    monkeypatch.setattr("amadeus.app.bootstrap.PluginManager", CapturingManager)
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )

    import amadeus.app.bootstrap as bootstrap

    assert captured["plugin_roots"] == [
        ("builtin", Path(bootstrap.__file__).resolve().parents[1] / "builtin_plugins"),
        ("workspace", tmp_path / "plugins"),
    ]
    assert captured["event_bus"] is app.event_bus
    assert captured["tool_registry"] is app.tool_registry
    assert captured["workspace"] is app.config.workspace_root
    assert captured["session_manager"] is app.session_manager
    assert captured["memory_engine"] is app.runtime.memory_engine
    asyncio.run(app.aclose())


def test_start_is_idempotent_sequentially_and_concurrently(tmp_path):
    app, manager = _app_with_controlled_manager(tmp_path)

    async def scenario() -> None:
        first, second = await asyncio.gather(app.start(), app.start())
        third = await app.start()
        assert first is manager.report
        assert second is manager.report
        assert third is manager.report
        await app.aclose()

    asyncio.run(scenario())
    assert manager.load_calls == 1


def test_aclose_is_idempotent_for_started_app(tmp_path, monkeypatch):
    app, manager = _app_with_controlled_manager(tmp_path)
    close_calls = 0
    original_close = app.session_manager.store.close

    def close_store() -> None:
        nonlocal close_calls
        close_calls += 1
        original_close()

    monkeypatch.setattr(app.session_manager.store, "close", close_store)

    async def scenario() -> None:
        await app.start()
        await asyncio.gather(app.aclose(), app.aclose())
        await app.aclose()

    asyncio.run(scenario())
    assert manager.terminate_calls == 1
    assert close_calls == 1
    assert app._state is AppState.CLOSED


def test_start_runs_memory_optimizer_loop_and_aclose_cancels_it(tmp_path, monkeypatch):
    app, _manager = _app_with_controlled_manager(tmp_path)
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingOptimizerLoop:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def run(self) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    monkeypatch.setattr("amadeus.app.bootstrap.MemoryOptimizerLoop", BlockingOptimizerLoop)

    async def scenario() -> None:
        await app.start()
        await started.wait()
        await app.aclose()

    asyncio.run(scenario())
    assert cancelled.is_set()
    assert app._memory_optimizer_task is None


def test_start_does_not_create_memory_optimizer_loop_when_disabled(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AMADEUS_MEMORY_OPTIMIZER_ENABLED", "0")
    app, _manager = _app_with_controlled_manager(tmp_path)

    class UnexpectedOptimizerLoop:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("optimizer loop must be disabled")

    monkeypatch.setattr("amadeus.app.bootstrap.MemoryOptimizerLoop", UnexpectedOptimizerLoop)

    async def scenario() -> None:
        await app.start()
        assert app._memory_optimizer_task is None
        await app.aclose()

    asyncio.run(scenario())


def test_new_app_can_close_and_closed_app_cannot_restart(tmp_path):
    app, manager = _app_with_controlled_manager(tmp_path)

    async def scenario() -> None:
        await app.aclose()
        with pytest.raises(RuntimeError, match="closed"):
            await app.start()

    asyncio.run(scenario())
    assert manager.load_calls == 0
    assert manager.terminate_calls == 1


def test_failed_start_cleans_up_stays_new_and_can_retry(tmp_path):
    app, manager = _app_with_controlled_manager(tmp_path)
    manager.load_error = RuntimeError("unexpected loader failure")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="unexpected loader failure"):
            await app.start()
        assert app._state is AppState.NEW
        assert await app.start() is manager.report
        await app.aclose()

    asyncio.run(scenario())
    assert manager.load_calls == 2
    assert manager.terminate_calls == 2


def test_phase_rebuild_failure_rolls_back_runtime_and_plugin_lifecycle(tmp_path):
    class DuplicateModule:
        slot = "plugin.duplicate"
        requires: tuple[str, ...] = ()
        produces: tuple[str, ...] = ()

        async def run(self, frame):
            return frame

    app, manager = _app_with_controlled_manager(tmp_path)
    manager.before_turn_modules = [DuplicateModule(), DuplicateModule()]

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="模块 slot 重复"):
            await app.start()
        assert app._state is AppState.NEW
        assert manager.terminate_calls == 1

        result = await app.runtime.run_turn(
            session=_session(31),
            user_message="still available",
        )
        assert result.assistant_response == "assistant reply"

        manager.before_turn_modules = []
        assert await app.start() is manager.report
        await app.aclose()

    asyncio.run(scenario())
    assert manager.load_calls == 2
    assert manager.terminate_calls == 2


def test_prompt_phase_rebuild_failure_rolls_back_runtime_and_plugin_lifecycle(tmp_path):
    class DuplicatePromptModule:
        slot = "plugin.duplicate_prompt"
        requires: tuple[str, ...] = ()
        produces: tuple[str, ...] = ()

        async def run(self, frame):
            return frame

    app, manager = _app_with_controlled_manager(tmp_path)
    manager.prompt_render_modules = [DuplicatePromptModule(), DuplicatePromptModule()]

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="模块 slot 重复"):
            await app.start()
        assert app._state is AppState.NEW
        assert manager.terminate_calls == 1

        result = await app.runtime.run_turn(
            session=_session(32),
            user_message="still available",
        )
        assert result.assistant_response == "assistant reply"

        manager.prompt_render_modules = []
        assert await app.start() is manager.report
        await app.aclose()

    asyncio.run(scenario())
    assert manager.load_calls == 2
    assert manager.terminate_calls == 2


def test_lifecycle_phase_rebuild_failure_rolls_back_runtime_and_plugin_lifecycle(
    tmp_path,
):
    class DuplicateAfterReasoningModule:
        slot = "plugin.duplicate_after_reasoning"
        requires: tuple[str, ...] = ()
        produces: tuple[str, ...] = ()

        async def run(self, frame):
            return frame

    app, manager = _app_with_controlled_manager(tmp_path)
    manager.after_reasoning_modules = [
        DuplicateAfterReasoningModule(),
        DuplicateAfterReasoningModule(),
    ]

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="模块 slot 重复"):
            await app.start()
        assert app._state is AppState.NEW
        assert manager.terminate_calls == 1

        result = await app.runtime.run_turn(
            session=_session(33),
            user_message="still available",
        )
        assert result.assistant_response == "assistant reply"

        manager.after_reasoning_modules = []
        assert await app.start() is manager.report
        await app.aclose()

    asyncio.run(scenario())
    assert manager.load_calls == 2
    assert manager.terminate_calls == 2


def test_terminate_error_still_closes_store_and_marks_closed(tmp_path, monkeypatch):
    app, manager = _app_with_controlled_manager(tmp_path)
    manager.terminate_error = RuntimeError("terminate failed")
    close_calls = 0
    original_close = app.session_manager.store.close

    def close_store() -> None:
        nonlocal close_calls
        close_calls += 1
        original_close()

    monkeypatch.setattr(app.session_manager.store, "close", close_store)

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="terminate failed"):
            await app.aclose()

    asyncio.run(scenario())
    assert close_calls == 1
    assert app._state is AppState.CLOSED


def test_start_and_close_share_one_transition_lock(tmp_path):
    app, manager = _app_with_controlled_manager(tmp_path)

    async def scenario() -> None:
        manager.load_entered = asyncio.Event()
        manager.release_load = asyncio.Event()
        start_task = asyncio.create_task(app.start())
        await manager.load_entered.wait()
        close_task = asyncio.create_task(app.aclose())
        await asyncio.sleep(0)
        assert not close_task.done()
        manager.release_load.set()
        await start_task
        await close_task

    asyncio.run(scenario())
    assert manager.load_calls == 1
    assert manager.terminate_calls == 1
    assert app._state is AppState.CLOSED


def test_cancelled_aclose_closes_store_and_removes_live_plugin_state(
    tmp_path, monkeypatch
):
    plugin_dir = tmp_path / "plugins" / "blocking"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        """\
from amadeus.plugin import Plugin, on_before_turn
class BlockingPlugin(Plugin):
    @on_before_turn()
    async def before_turn(self, context):
        context.runtime_metadata["plugin_marker"] = "live"
        return context
""",
        encoding="utf-8",
    )
    app = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )
    store_closed = False
    original_close = app.session_manager.store.close

    def close_store() -> None:
        nonlocal store_closed
        store_closed = True
        original_close()

    monkeypatch.setattr(app.session_manager.store, "close", close_store)

    async def scenario() -> str:
        report = await app.start()
        record = next(record for record in report.loaded if record.name == "blocking")
        instance = plugin_registry.get_instance(record.import_path)
        assert isinstance(instance, Plugin)
        terminate_entered = asyncio.Event()
        release_terminate = asyncio.Event()

        async def blocking_terminate() -> None:
            terminate_entered.set()
            await release_terminate.wait()

        instance.terminate = blocking_terminate  # type: ignore[method-assign]
        closing = asyncio.create_task(app.aclose())
        await terminate_entered.wait()
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing

        assert app._state is AppState.CLOSED
        assert store_closed
        assert app.plugin_manager.loaded_names == []
        assert app.plugin_manager._bindings == {}
        assert plugin_registry.get_classes(record.import_path) == []
        assert plugin_registry.get_instance(record.import_path) is None
        assert plugin_registry.get_handlers_by_module_path(record.import_path) == []
        assert record.import_path not in sys.modules
        after_close = await app.event_bus.emit(
            BeforeTurnContext(
                session=_session(23),
                user_message="hello",
                history=[],
                retrieved_memory=None,
            )
        )
        assert "plugin_marker" not in after_close.runtime_metadata
        return record.import_path

    import_path = asyncio.run(scenario())

    fresh = build_passive_app(
        workspace_root=tmp_path,
        env_path=_env_path(tmp_path),
        client=FakeClient(),
    )

    async def reload_and_close() -> None:
        report = await fresh.start()
        assert any(record.import_path == import_path for record in report.loaded)
        await fresh.aclose()

    asyncio.run(reload_and_close())
