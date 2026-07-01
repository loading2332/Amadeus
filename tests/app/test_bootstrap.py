from __future__ import annotations

import asyncio
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from amadeus.app.bootstrap import AppState, build_passive_app, load_runtime_config
from amadeus.plugin import Plugin, plugin_registry
from amadeus.plugin.types import PluginLoadReport
from amadeus.provider import ChatCompletionsClient, ChatNamespace
from amadeus.runtime.lifecycle import BeforeTurnContext


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

    async def scenario():
        await app.start()
        try:
            return await app.runtime.run_turn(session_key="chat:1", user_message="hello")
        finally:
            await app.aclose()

    result = asyncio.run(scenario())

    session = app.session_manager.get_or_create("chat:1")
    recent = app.memory.store.read_recent_context()
    assert result.assistant_response == "assistant reply"
    assert [message["id"] for message in session.messages] == ["chat:1:0", "chat:1:1"]
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
                session_key="plugin:e2e",
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
                session_key="plugin:after-close",
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
            session_key="phase:rollback",
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
            session_key="prompt-phase:rollback",
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
            session_key="after-reasoning-phase:rollback",
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
                session_key="plugin:after-cancelled-close",
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
