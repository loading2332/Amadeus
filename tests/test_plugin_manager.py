from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from amadeus.events import EventBus
from amadeus.lifecycle import BeforeTurnContext
from amadeus.memory_engine import MemoryEngine
from amadeus.plugin import (
    Plugin,
    PluginLoadReport,
    PluginLoadStatus,
    PluginManager,
    plugin_registry,
)
from amadeus.session import SessionManager
from amadeus.tools.registry import ToolRegistry

PLUGIN_TEMPLATE = """\
from amadeus.plugin import Plugin, on_before_turn

class {class_name}(Plugin):
    name = {plugin_name!r}
    version = "class-version"
    desc = "class-desc"
    author = "class-author"

    @on_before_turn(priority={priority})
    async def before_turn(self, context):
        context.runtime_metadata["order"] = context.runtime_metadata.get("order", "") + {effect!r}
        return context

    async def initialize(self):
        {initialize}

    async def terminate(self):
        {terminate}
"""


def _write_plugin(
    root: Path,
    name: str,
    *,
    plugin_name: str | None = None,
    priority: int = 0,
    effect: str = "",
    initialize: str = "pass",
    terminate: str = "pass",
    source: str | None = None,
    files: dict[str, str] | None = None,
) -> Path:
    plugin_dir = root / name
    plugin_dir.mkdir(parents=True)
    body = source or PLUGIN_TEMPLATE.format(
        class_name="P" + "".join(char if char.isalnum() else "_" for char in name),
        plugin_name=plugin_name,
        priority=priority,
        effect=effect,
        initialize=initialize,
        terminate=terminate,
    )
    (plugin_dir / "plugin.py").write_text(body, encoding="utf-8")
    for filename, content in (files or {}).items():
        (plugin_dir / filename).write_text(content, encoding="utf-8")
    return plugin_dir


def _manager(
    roots: list[tuple[str, Path]],
    *,
    bus: EventBus | None = None,
    tools: ToolRegistry | None = None,
    workspace: Path | None = None,
    session_manager: SessionManager | None = None,
    memory_engine: MemoryEngine | None = None,
) -> PluginManager:
    return PluginManager(
        plugin_roots=roots,
        event_bus=bus or EventBus(),
        tool_registry=tools or ToolRegistry(),
        workspace=workspace or roots[0][1].parent,
        session_manager=session_manager,
        memory_engine=memory_engine,
    )


@pytest.fixture(autouse=True)
def _isolate_global_registry() -> Any:
    plugin_registry.clear()
    yield
    plugin_registry.clear()
    for module_name in tuple(sys.modules):
        if module_name.startswith("amadeus_plugin_"):
            sys.modules.pop(module_name, None)


def _before_turn() -> BeforeTurnContext:
    return BeforeTurnContext(
        session_key="test", user_message="hello", history=[], retrieved_memory=None
    )


def _loaded_instance(report: PluginLoadReport) -> Plugin:
    instance = plugin_registry.get_instance(report.loaded[0].import_path)
    assert isinstance(instance, Plugin)
    return instance


def test_successful_plugin_contributes_before_turn_modules(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "phase_marker",
        source="""\
from amadeus.plugin import Plugin

class MarkerModule:
    slot = "phase_marker.before_turn"
    requires = ("before_turn.build_ctx", "session:ctx")
    produces = ("session:ctx",)
    async def run(self, frame):
        return frame

class PhaseMarker(Plugin):
    name = "phase_marker"
    def before_turn_modules(self):
        return [MarkerModule()]
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert len(report.loaded) == 1
    assert [module.slot for module in manager.before_turn_modules] == [
        "phase_marker.before_turn"
    ]


def test_successful_plugin_contributes_prompt_render_modules(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "prompt_marker",
        source="""\
from amadeus.plugin import Plugin

class PromptMarkerModule:
    slot = "prompt_marker.prompt"
    requires = ("prompt_render.emit", "prompt:ctx")
    produces = ("prompt:ctx",)
    async def run(self, frame):
        return frame

class PromptMarker(Plugin):
    name = "prompt_marker"
    def prompt_render_modules(self):
        return [PromptMarkerModule()]
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert len(report.loaded) == 1
    assert [module.slot for module in manager.prompt_render_modules] == [
        "prompt_marker.prompt"
    ]


def test_successful_plugin_contributes_all_lifecycle_phase_modules(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "lifecycle_modules",
        source="""\
from amadeus.plugin import Plugin

class M:
    def __init__(self, slot):
        self.slot = slot
    async def run(self, frame):
        return frame

class LifecycleModules(Plugin):
    name = "lifecycle_modules"
    def before_reasoning_modules(self):
        return [M("plugin.before_reasoning")]
    def before_step_modules(self):
        return [M("plugin.before_step")]
    def after_step_modules(self):
        return [M("plugin.after_step")]
    def after_reasoning_modules(self):
        return [M("plugin.after_reasoning")]
    def after_turn_modules(self):
        return [M("plugin.after_turn")]
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert len(report.loaded) == 1
    assert [module.slot for module in manager.before_reasoning_modules] == [
        "plugin.before_reasoning"
    ]
    assert [module.slot for module in manager.before_step_modules] == [
        "plugin.before_step"
    ]
    assert [module.slot for module in manager.after_step_modules] == [
        "plugin.after_step"
    ]
    assert [module.slot for module in manager.after_reasoning_modules] == [
        "plugin.after_reasoning"
    ]
    assert [module.slot for module in manager.after_turn_modules] == [
        "plugin.after_turn"
    ]


def test_invalid_before_turn_module_collection_fails_plugin_transaction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "invalid_modules",
        source="""\
from amadeus.plugin import Plugin
class InvalidModules(Plugin):
    def before_turn_modules(self):
        return (object(),)
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert report.records[0].status is PluginLoadStatus.FAILED
    assert report.records[0].stage == "phase_modules"
    assert manager.before_turn_modules == []
    assert manager.loaded_names == []


def test_invalid_prompt_render_module_collection_fails_plugin_transaction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "invalid_prompt_modules",
        source="""\
from amadeus.plugin import Plugin
class InvalidPromptModules(Plugin):
    def prompt_render_modules(self):
        return (object(),)
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert report.records[0].status is PluginLoadStatus.FAILED
    assert report.records[0].stage == "phase_modules"
    assert manager.prompt_render_modules == []
    assert manager.loaded_names == []


def test_invalid_lifecycle_module_collection_fails_plugin_transaction(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "invalid_lifecycle_modules",
        source="""\
from amadeus.plugin import Plugin
class InvalidLifecycleModules(Plugin):
    def after_reasoning_modules(self):
        return (object(),)
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert report.records[0].status is PluginLoadStatus.FAILED
    assert report.records[0].stage == "phase_modules"
    assert manager.after_reasoning_modules == []
    assert manager.loaded_names == []


def test_initialize_failure_does_not_commit_before_turn_modules(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "crash_after_modules",
        source="""\
from amadeus.plugin import Plugin
class MarkerModule:
    slot = "crash.marker"
    async def run(self, frame):
        return frame
class CrashAfterModules(Plugin):
    def before_turn_modules(self):
        return [MarkerModule()]
    async def initialize(self):
        raise RuntimeError("initialize failed")
""",
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    assert report.records[0].status is PluginLoadStatus.FAILED
    assert report.records[0].stage == "initialize"
    assert manager.before_turn_modules == []
    assert manager.prompt_render_modules == []


def test_terminate_removes_owned_before_turn_modules(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "owned_module",
        source="""\
from amadeus.plugin import Plugin
class OwnedModule:
    slot = "owned.before_turn"
    async def run(self, frame):
        return frame
class Owner(Plugin):
    def before_turn_modules(self):
        return [OwnedModule()]
""",
    )
    manager = _manager([("workspace", root)])
    asyncio.run(manager.load_all())

    asyncio.run(manager.terminate_all())

    assert manager.before_turn_modules == []


def test_terminate_removes_owned_prompt_render_modules(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "owned_prompt_module",
        source="""\
from amadeus.plugin import Plugin
class OwnedPromptModule:
    slot = "owned.prompt"
    async def run(self, frame):
        return frame
class Owner(Plugin):
    def prompt_render_modules(self):
        return [OwnedPromptModule()]
""",
    )
    manager = _manager([("workspace", root)])
    asyncio.run(manager.load_all())

    asyncio.run(manager.terminate_all())

    assert manager.prompt_render_modules == []


def test_terminate_removes_owned_lifecycle_phase_modules(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "owned_lifecycle_module",
        source="""\
from amadeus.plugin import Plugin
class OwnedModule:
    slot = "owned.after_reasoning"
    async def run(self, frame):
        return frame
class Owner(Plugin):
    def after_reasoning_modules(self):
        return [OwnedModule()]
""",
    )
    manager = _manager([("workspace", root)])
    asyncio.run(manager.load_all())

    asyncio.run(manager.terminate_all())

    assert manager.after_reasoning_modules == []


def test_discovery_is_ordered_first_wins_and_does_not_import_duplicate(
    tmp_path: Path,
) -> None:
    builtin = tmp_path / "builtin"
    workspace = tmp_path / "workspace"
    _write_plugin(builtin, "same", effect="B")
    duplicate = _write_plugin(
        workspace,
        "same",
        source='raise RuntimeError("duplicate code was imported")',
    )
    _write_plugin(workspace, "user-plugin", effect="U")

    manager = _manager([("builtin", builtin), ("workspace", workspace)])
    discovery = manager.discover()

    assert [candidate.source for candidate in discovery.candidates] == [
        "builtin",
        "workspace",
    ]
    assert discovery.candidates[1].import_path.startswith(
        "amadeus_plugin_workspace_user_plugin_"
    )
    duplicate_record = discovery.records[0]
    assert duplicate_record.status is PluginLoadStatus.DUPLICATE
    assert duplicate_record.name == duplicate.name


def test_sanitized_names_get_collision_resistant_import_paths(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "a-b")
    _write_plugin(root, "a_b")
    manager = _manager([("workspace", root)])

    discovery = manager.discover()
    report = asyncio.run(manager.load_all())

    import_paths = [candidate.import_path for candidate in discovery.candidates]
    assert len(set(import_paths)) == 2
    assert all(path.isidentifier() for path in import_paths)
    assert [record.name for record in report.loaded] == ["a-b", "a_b"]


def test_non_ascii_names_get_valid_distinct_loadable_import_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    source = PLUGIN_TEMPLATE.format(
        class_name="SafePlugin",
        plugin_name=None,
        priority=0,
        effect="",
        initialize="pass",
        terminate="pass",
    )
    _write_plugin(root, "²", source=source)
    _write_plugin(root, "_", source=source.replace("SafePlugin", "OtherPlugin"))
    manager = _manager([("workspace", root)])

    discovery = manager.discover()
    report = asyncio.run(manager.load_all())

    import_paths = [candidate.import_path for candidate in discovery.candidates]
    assert all(path.isidentifier() for path in import_paths)
    assert len(set(import_paths)) == 2
    assert {record.name for record in report.loaded} == {"²", "_"}


def test_disabled_is_checked_immediately_before_import(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = _write_plugin(
        root, "disabled", source='raise RuntimeError("must not import")'
    )
    manager = _manager([("workspace", root)])
    assert manager.discover().candidates
    (plugin_dir / "plugin.disabled").touch()

    report = asyncio.run(manager.load_all())

    assert report.disabled[0].stage is None
    assert report.disabled[0].import_path not in sys.modules


def test_load_report_is_idempotent_and_manifest_overrides_metadata(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "manifested",
        plugin_name=None,
        files={
            "manifest.yaml": (
                "name: manifest_name\nversion: 0.2\ndesc: from manifest\nauthor: tester\n"
            )
        },
    )
    manager = _manager([("workspace", root)])

    first = asyncio.run(manager.load_all())
    second = asyncio.run(manager.load_all())

    assert first.loaded[0].name == "manifested"
    assert second.already_loaded[0].name == "manifested"
    instance = _loaded_instance(first)
    assert instance.context.plugin_id == "manifest_name"
    assert (instance.name, instance.version, instance.desc, instance.author) == (
        "manifest_name",
        "0.2",
        "from manifest",
        "tester",
    )


@pytest.mark.parametrize(
    ("schema", "override", "expected"),
    [
        ('{"greeting":{"default":"Hi"},"volume":{"default":5}}', '{"greeting":"Gday","extra":true}', {"greeting": "Gday", "volume": 5, "extra": True}),
        ("{}", None, {}),
        ('{"greeting":{"default":"Hi"}}', "not-json", {"greeting": "Hi"}),
    ],
)
def test_config_defaults_override_empty_and_bad_override_degrade(
    tmp_path: Path,
    schema: str,
    override: str | None,
    expected: dict[str, object],
) -> None:
    root = tmp_path / "plugins"
    files = {"_conf_schema.json": schema}
    if override is not None:
        files["plugin_config.json"] = override
    _write_plugin(root, "configured", files=files)
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    instance = _loaded_instance(report)
    assert instance.context.config is not None
    assert instance.context.config.as_dict() == expected


@pytest.mark.parametrize("schema", ["not-json", "[]"])
def test_bad_schema_degrades_to_none(tmp_path: Path, schema: str) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "bad_schema", files={"_conf_schema.json": schema})
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    instance = _loaded_instance(report)
    assert instance.context.config is None


def test_no_manifest_and_no_schema_use_class_metadata_and_none_config(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "plain", plugin_name="class-name")
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    instance = _loaded_instance(report)
    assert instance.name == "class-name"
    assert instance.context.config is None


def test_bad_manifest_degrades_to_class_metadata(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "bad_manifest",
        plugin_name="class-name",
        files={"manifest.yaml": "[not, a, mapping]"},
    )
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    instance = _loaded_instance(report)
    assert instance.context.plugin_id == "class-name"


def test_context_injects_exact_shared_dependencies(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    plugin_dir = _write_plugin(root, "context")
    bus = EventBus()
    tools = ToolRegistry()
    workspace = tmp_path / "ws"
    session_manager = SessionManager(tmp_path / "sessions")
    memory_engine = cast(MemoryEngine, object())
    manager = _manager(
        [("workspace", root)],
        bus=bus,
        tools=tools,
        workspace=workspace,
        session_manager=session_manager,
        memory_engine=memory_engine,
    )
    report = asyncio.run(manager.load_all())
    instance = _loaded_instance(report)
    assert instance.context.event_bus is bus
    assert instance.context.tool_registry is tools
    assert instance.context.plugin_dir == plugin_dir.resolve()
    assert instance.context.workspace == workspace
    assert instance.context.session_manager is session_manager
    assert instance.context.memory_engine is memory_engine
    assert instance.context.kv_store._path == plugin_dir.resolve() / ".kv.json"
    session_manager.store.close()


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("noclass", "value = 1"),
        (
            "multiclass",
            "from amadeus.plugin import Plugin\nclass One(Plugin): pass\nclass Two(Plugin): pass\n",
        ),
    ],
)
def test_class_cardinality_failure_has_no_residue(
    tmp_path: Path, name: str, source: str
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, name, source=source)
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    record = report.failed[0]
    assert record.stage == "register"
    assert plugin_registry.get_instance(record.import_path) is None
    assert plugin_registry.get_classes(record.import_path) == []
    assert record.import_path not in sys.modules


def test_plugin_id_collision_rolls_back_later_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "first", plugin_name="shared")
    _write_plugin(root, "second", plugin_name="shared")
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    assert [record.name for record in report.loaded] == ["first"]
    assert report.failed[0].name == "second"
    assert report.failed[0].stage == "identity"
    assert report.failed[0].import_path not in sys.modules


def test_priority_applies_across_plugins(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "a_low", priority=1, effect="L")
    _write_plugin(root, "z_high", priority=100, effect="H")
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)
    asyncio.run(manager.load_all())
    result = asyncio.run(bus.emit(_before_turn()))
    assert result.runtime_metadata["order"] == "HL"


class FailingEventBus(EventBus):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def on(self, *args: Any, **kwargs: Any) -> None:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("bind failed")
        super().on(*args, **kwargs)


class RegisterThenFailEventBus(EventBus):
    def on(self, *args: Any, **kwargs: Any) -> None:
        super().on(*args, **kwargs)
        raise RuntimeError("bind failed after registration")


@pytest.mark.parametrize(
    ("name", "source", "stage"),
    [
        ("import_fail", 'raise RuntimeError("import secret")', "import"),
        (
            "constructor_fail",
            "from amadeus.plugin import Plugin\nclass Broken(Plugin):\n    def __init__(self): raise RuntimeError('constructor secret')\n",
            "instantiate",
        ),
        (
            "initialize_fail",
            PLUGIN_TEMPLATE.format(class_name="InitializeFail", plugin_name="init", priority=0, effect="X", initialize="raise RuntimeError('initialize secret')", terminate="pass"),
            "initialize",
        ),
    ],
)
def test_executable_failures_are_atomic_and_do_not_block_good_plugin(
    tmp_path: Path, name: str, source: str, stage: str
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, name, source=source)
    _write_plugin(root, "zz_good", effect="G")
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)
    report = asyncio.run(manager.load_all())
    failed = next(record for record in report.failed if record.name == name)
    assert failed.stage == stage
    assert [record.name for record in report.loaded] == ["zz_good"]
    assert plugin_registry.get_instance(failed.import_path) is None
    assert plugin_registry.get_handlers_by_module_path(failed.import_path) == []
    assert failed.import_path not in sys.modules
    result = asyncio.run(bus.emit(_before_turn()))
    assert result.runtime_metadata["order"] == "G"


def test_mid_bind_failure_removes_first_exact_binding(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    source = """\
from amadeus.plugin import Plugin, on_before_turn
class BrokenBind(Plugin):
    @on_before_turn()
    async def first(self, context):
        context.runtime_metadata["ghost"] = "first"
        return context
    @on_before_turn()
    async def second(self, context):
        return context
"""
    _write_plugin(root, "bind_fail", source=source)
    bus = FailingEventBus()
    manager = _manager([("workspace", root)], bus=bus)
    report = asyncio.run(manager.load_all())
    assert report.failed[0].stage == "bind"
    result = asyncio.run(bus.emit(_before_turn()))
    assert "ghost" not in result.runtime_metadata


def test_bind_failure_after_registration_removes_ghost_and_ledger(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "bind_fail", effect="ghost")
    bus = RegisterThenFailEventBus()
    manager = _manager([("workspace", root)], bus=bus)

    report = asyncio.run(manager.load_all())

    assert report.failed[0].stage == "bind"
    assert manager._bindings == {}
    result = asyncio.run(bus.emit(_before_turn()))
    assert "order" not in result.runtime_metadata


def test_initialize_failure_calls_terminate_and_terminate_error_does_not_leak(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "plugins"
    marker = tmp_path / "terminated"
    source = PLUGIN_TEMPLATE.format(
        class_name="FailBoth",
        plugin_name="fail-both",
        priority=0,
        effect="X",
        initialize="raise RuntimeError('api_key=super-secret')",
        terminate=f"Path({str(marker)!r}).write_text('yes'); raise RuntimeError('api_key=super-secret')",
    ).replace(
        "from amadeus.plugin import Plugin, on_before_turn",
        "from pathlib import Path\nfrom amadeus.plugin import Plugin, on_before_turn",
    )
    _write_plugin(root, "fail_both", source=source)
    caplog.set_level(logging.WARNING)
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    assert marker.read_text() == "yes"
    assert report.failed[0].import_path not in sys.modules
    assert "super-secret" not in caplog.text
    assert "api_key=" not in caplog.text
    assert "function=terminate" in caplog.text


def test_failure_report_and_logs_never_expose_exception_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "secret",
        source=(
            'def explode():\n    raise RuntimeError("api_key=super-secret")\nexplode()'
        ),
    )
    caplog.set_level(logging.WARNING)
    report = asyncio.run(_manager([("workspace", root)]).load_all())
    combined = " ".join(
        [record.message or "" for record in report.records] + [caplog.text]
    )
    assert "super-secret" not in combined
    assert "api_key=" not in combined
    assert "RuntimeError" in (report.failed[0].message or "")
    assert "function=explode" in caplog.text


def test_terminate_then_fresh_reload_has_one_initialize_and_one_handler(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    source = """\
from amadeus.plugin import Plugin, on_before_turn
class Reloadable(Plugin):
    async def initialize(self):
        self.context.kv_store.increment("initialize_count")
    @on_before_turn()
    async def before_turn(self, context):
        context.runtime_metadata["hits"] = context.runtime_metadata.get("hits", "") + "x"
        return context
"""
    plugin_dir = _write_plugin(root, "reloadable", source=source)
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)

    first = asyncio.run(manager.load_all())
    assert first.loaded
    assert asyncio.run(bus.emit(_before_turn())).runtime_metadata["hits"] == "x"
    asyncio.run(manager.terminate_all())
    second = asyncio.run(manager.load_all())

    assert second.loaded
    assert asyncio.run(bus.emit(_before_turn())).runtime_metadata["hits"] == "x"
    assert (plugin_dir / ".kv.json").read_text(encoding="utf-8").count(
        '"initialize_count": 2'
    ) == 1


def test_dynamic_relative_submodule_is_removed_on_terminate(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "with_helper",
        source="from . import helper\nfrom amadeus.plugin import Plugin\nclass UsesHelper(Plugin): pass\n",
        files={"helper.py": "VALUE = 42\n"},
    )
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    import_path = report.loaded[0].import_path
    assert f"{import_path}.helper" in sys.modules

    asyncio.run(manager.terminate_all())

    assert f"{import_path}.helper" not in sys.modules


def test_relative_submodule_declarations_are_removed_on_terminate(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "with_declaring_helper",
        source=(
            "from . import helper\n"
            "from amadeus.plugin import Plugin\n"
            "class RootPlugin(Plugin): pass\n"
        ),
        files={
            "helper.py": (
                "from amadeus.plugin import Plugin, on_before_turn\n"
                "class HelperPlugin(Plugin):\n"
                "    @on_before_turn()\n"
                "    async def helper_handler(self, context): return context\n"
            )
        },
    )
    manager = _manager([("workspace", root)])
    report = asyncio.run(manager.load_all())
    import_path = report.loaded[0].import_path
    helper_path = f"{import_path}.helper"
    assert plugin_registry.get_classes(helper_path)
    assert plugin_registry.get_handlers_by_module_path(helper_path)

    asyncio.run(manager.terminate_all())

    for module_path in (import_path, helper_path):
        assert plugin_registry.get_classes(module_path) == []
        assert plugin_registry.get_instance(module_path) is None
        assert plugin_registry.get_handlers_by_module_path(module_path) == []
        assert module_path not in sys.modules


@pytest.mark.parametrize("failure_stage", ["import", "initialize"])
def test_relative_submodule_declarations_are_removed_on_load_failure(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    root = tmp_path / "plugins"
    root_tail = (
        'raise RuntimeError("import failed")\n'
        if failure_stage == "import"
        else (
            "from amadeus.plugin import Plugin\n"
            "class RootPlugin(Plugin):\n"
            "    async def initialize(self):\n"
            '        raise RuntimeError("initialize failed")\n'
        )
    )
    _write_plugin(
        root,
        "failing_tree",
        source="from . import helper\n" + root_tail,
        files={
            "helper.py": (
                "from amadeus.plugin import Plugin, on_before_turn\n"
                "class HelperPlugin(Plugin):\n"
                "    @on_before_turn()\n"
                "    async def helper_handler(self, context): return context\n"
            )
        },
    )
    manager = _manager([("workspace", root)])

    report = asyncio.run(manager.load_all())

    failed = report.failed[0]
    helper_path = f"{failed.import_path}.helper"
    assert failed.stage == failure_stage
    for module_path in (failed.import_path, helper_path):
        assert plugin_registry.get_classes(module_path) == []
        assert plugin_registry.get_instance(module_path) is None
        assert plugin_registry.get_handlers_by_module_path(module_path) == []
        assert module_path not in sys.modules


def test_foreign_manager_cannot_import_or_cleanup_owned_plugin(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "owned", effect="x")
    first_bus = EventBus()
    second_bus = EventBus()
    first = _manager([("workspace", root)], bus=first_bus)
    second = _manager([("workspace", root)], bus=second_bus)

    first_report = asyncio.run(first.load_all())
    import_path = first_report.loaded[0].import_path
    instance = plugin_registry.get_instance(import_path)
    module = sys.modules[import_path]
    handlers = plugin_registry.get_handlers_by_module_path(import_path)

    second_report = asyncio.run(second.load_all())

    assert second_report.failed[0].stage == "ownership"
    assert first.loaded_names == ["owned"]
    assert plugin_registry.get_instance(import_path) is instance
    assert sys.modules[import_path] is module
    assert plugin_registry.get_handlers_by_module_path(import_path) == handlers
    assert asyncio.run(first_bus.emit(_before_turn())).runtime_metadata["order"] == "x"

    asyncio.run(first.terminate_all())
    retry_report = asyncio.run(second.load_all())
    assert retry_report.loaded
    assert asyncio.run(second_bus.emit(_before_turn())).runtime_metadata["order"] == "x"


def test_concurrent_loads_are_serialized_and_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "concurrent",
        source="""\
import asyncio
from amadeus.plugin import Plugin, on_before_turn
class ConcurrentPlugin(Plugin):
    async def initialize(self):
        await asyncio.sleep(0)
        self.context.kv_store.increment("initialize_count")
    @on_before_turn()
    async def before_turn(self, context):
        context.runtime_metadata["hits"] = context.runtime_metadata.get("hits", "") + "x"
        return context
""",
    )
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)

    async def run_loads() -> tuple[PluginLoadReport, PluginLoadReport]:
        first, second = await asyncio.gather(manager.load_all(), manager.load_all())
        return first, second

    first, second = asyncio.run(run_loads())

    statuses = [first.records[0].status, second.records[0].status]
    assert statuses.count(PluginLoadStatus.LOADED) == 1
    assert statuses.count(PluginLoadStatus.ALREADY_LOADED) == 1
    assert asyncio.run(bus.emit(_before_turn())).runtime_metadata["hits"] == "x"
    kv = root / "concurrent" / ".kv.json"
    assert '"initialize_count": 1' in kv.read_text(encoding="utf-8")


def test_concurrent_load_then_terminate_finishes_fully_terminated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(
        root,
        "slow",
        source="""\
import asyncio
from amadeus.plugin import Plugin, on_before_turn
class SlowPlugin(Plugin):
    async def initialize(self):
        await asyncio.sleep(0.02)
    @on_before_turn()
    async def before_turn(self, context):
        context.runtime_metadata["hit"] = True
        return context
""",
    )
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)
    import_path = manager.discover().candidates[0].import_path

    async def load_then_terminate() -> None:
        loading = asyncio.create_task(manager.load_all())
        await asyncio.sleep(0)
        terminating = asyncio.create_task(manager.terminate_all())
        await asyncio.gather(loading, terminating)

    asyncio.run(load_then_terminate())

    assert manager.loaded_names == []
    assert plugin_registry.get_instance(import_path) is None
    assert plugin_registry.get_classes(import_path) == []
    assert plugin_registry.get_handlers_by_module_path(import_path) == []
    assert import_path not in sys.modules
    assert "hit" not in asyncio.run(bus.emit(_before_turn())).runtime_metadata


def test_terminate_all_reverse_cleanup_removes_handlers_modules_and_is_idempotent(
    tmp_path: Path,
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "one", effect="1")
    _write_plugin(root, "two", effect="2")
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)
    report = asyncio.run(manager.load_all())
    import_paths = [record.import_path for record in report.loaded]
    terminated: list[str] = []
    for record in report.loaded:
        instance = plugin_registry.get_instance(record.import_path)
        assert isinstance(instance, Plugin)

        async def terminate(name: str = record.name) -> None:
            terminated.append(name)

        instance.terminate = terminate  # type: ignore[method-assign]
    asyncio.run(manager.terminate_all())
    asyncio.run(manager.terminate_all())
    assert manager.loaded_names == []
    assert all(import_path not in sys.modules for import_path in import_paths)
    assert terminated == ["two", "one"]
    result = asyncio.run(bus.emit(_before_turn()))
    assert "order" not in result.runtime_metadata


def test_cancelled_terminate_all_cleans_every_plugin_and_releases_ownership(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "plugins"
    _write_plugin(root, "first", effect="1")
    _write_plugin(
        root,
        "second",
        source=(
            "from . import helper\n"
            "from amadeus.plugin import Plugin, on_before_turn\n"
            "class Second(Plugin):\n"
            "    @on_before_turn()\n"
            "    async def before_turn(self, context):\n"
            "        context.runtime_metadata['order'] = '2'\n"
            "        return context\n"
        ),
        files={
            "helper.py": (
                "from amadeus.plugin import Plugin, on_before_turn\n"
                "class Helper(Plugin):\n"
                "    @on_before_turn()\n"
                "    async def before_turn(self, context): return context\n"
            )
        },
    )
    bus = EventBus()
    manager = _manager([("workspace", root)], bus=bus)

    async def scenario() -> tuple[list[str], list[str]]:
        report = await manager.load_all()
        import_paths = [record.import_path for record in report.loaded]
        first_path = next(
            record.import_path for record in report.loaded if record.name == "first"
        )
        second_path = next(
            record.import_path for record in report.loaded if record.name == "second"
        )
        first = plugin_registry.get_instance(first_path)
        second = plugin_registry.get_instance(second_path)
        assert isinstance(first, Plugin)
        assert isinstance(second, Plugin)
        first_terminated = False
        terminate_entered = asyncio.Event()
        release_terminate = asyncio.Event()

        async def record_first_terminate() -> None:
            nonlocal first_terminated
            first_terminated = True

        async def blocking_terminate() -> None:
            terminate_entered.set()
            await release_terminate.wait()

        first.terminate = record_first_terminate  # type: ignore[method-assign]
        second.terminate = blocking_terminate  # type: ignore[method-assign]
        terminating = asyncio.create_task(manager.terminate_all())
        await terminate_entered.wait()
        terminating.cancel()
        with pytest.raises(asyncio.CancelledError):
            await terminating

        assert first_terminated
        assert "plugin terminate failed" not in caplog.text
        assert manager.loaded_names == []
        assert manager._bindings == {}
        assert manager._plugin_ids == {}
        assert manager._loaded == set()
        assert manager._load_order == []
        for import_path in import_paths:
            for module_path in (import_path, f"{import_path}.helper"):
                assert plugin_registry.get_classes(module_path) == []
                assert plugin_registry.get_instance(module_path) is None
                assert plugin_registry.get_handlers_by_module_path(module_path) == []
                assert module_path not in sys.modules
        assert "order" not in (await bus.emit(_before_turn())).runtime_metadata

        fresh = _manager([("workspace", root)], bus=EventBus())
        fresh_report = await fresh.load_all()
        assert len(fresh_report.loaded) == 2
        fresh_names = fresh.loaded_names
        await fresh.terminate_all()
        return import_paths, fresh_names

    import_paths, fresh_names = asyncio.run(scenario())
    assert len(import_paths) == 2
    assert fresh_names == ["first", "second"]
