from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import amadeus.plugin as plugin_api
import pytest
from amadeus.events import EventBus
from amadeus.memory_engine import MemoryEngine
from amadeus.plugin.config import PluginConfig
from amadeus.plugin.context import PluginContext, PluginKVStore
from amadeus.session import SessionManager
from amadeus.tools.registry import ToolRegistry


def test_plugin_contracts_are_exported_from_package() -> None:
    assert plugin_api.PluginConfig is PluginConfig
    assert plugin_api.PluginContext is PluginContext
    assert plugin_api.PluginKVStore is PluginKVStore


def test_plugin_config_exposes_an_immutable_snapshot() -> None:
    original = {"api_key": "secret", "max_results": 10}

    config = PluginConfig(original)
    original["api_key"] = "mutated"

    assert config.api_key == "secret"
    assert config.get("max_results") == 10
    assert config.get("missing", "fallback") == "fallback"

    copied = config.as_dict()
    copied["api_key"] = "changed"

    assert config.api_key == "secret"


def test_plugin_config_deep_copies_constructor_input() -> None:
    original: dict[str, Any] = {
        "provider": {"name": "openai"},
        "models": ["gpt-5"],
    }

    config = PluginConfig(original)
    original["provider"]["name"] = "mutated"
    original["models"].append("mutated-model")

    assert config.provider == {"name": "openai"}
    assert config.models == ["gpt-5"]


def test_plugin_config_deep_copies_as_dict_output() -> None:
    config = PluginConfig(
        {
            "provider": {"name": "openai"},
            "models": ["gpt-5"],
        }
    )

    copied = config.as_dict()
    copied["provider"]["name"] = "mutated"
    copied["models"].append("mutated-model")

    assert config.provider == {"name": "openai"}
    assert config.models == ["gpt-5"]


def test_plugin_config_missing_attribute_raises_attribute_error() -> None:
    config = PluginConfig({})

    with pytest.raises(AttributeError, match="missing"):
        _ = config.missing


def test_plugin_kv_store_persists_mutations_across_instances(tmp_path: Path) -> None:
    path = tmp_path / ".kv.json"
    first = PluginKVStore(path)

    assert first.get("turn_count", 0) == 0
    assert first.increment("turn_count") == 1
    first.set("last_session", "cli:default")

    second = PluginKVStore(path)
    assert second.get("turn_count") == 1
    assert second.get("last_session") == "cli:default"

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == {"turn_count": 1, "last_session": "cli:default"}


def test_plugin_kv_store_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / ".kv.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="JSON object"):
        PluginKVStore(path).get("missing")


def test_plugin_kv_store_mutation_reads_latest_file(tmp_path: Path) -> None:
    path = tmp_path / ".kv.json"
    first = PluginKVStore(path)
    second = PluginKVStore(path)

    first.set("turn_count", 4)

    assert second.increment("turn_count") == 5
    assert first.get("turn_count") == 5


def test_plugin_context_carries_approved_dependencies(tmp_path: Path) -> None:
    event_bus = EventBus()
    tool_registry = ToolRegistry()
    plugin_dir = tmp_path / "plugins" / "greeter"
    kv_store = PluginKVStore(plugin_dir / ".kv.json")
    config = PluginConfig({"greeting": "hello"})
    workspace = tmp_path / "workspace"
    session_manager = SessionManager(workspace)
    memory_engine = cast(MemoryEngine, object())

    context = PluginContext(
        event_bus=event_bus,
        tool_registry=tool_registry,
        plugin_id="greeter",
        plugin_dir=plugin_dir,
        kv_store=kv_store,
        config=config,
        workspace=workspace,
        session_manager=session_manager,
        memory_engine=memory_engine,
    )

    assert context.event_bus is event_bus
    assert context.tool_registry is tool_registry
    assert context.plugin_id == "greeter"
    assert context.plugin_dir == plugin_dir
    assert context.kv_store is kv_store
    assert context.config is config
    assert context.workspace == workspace
    assert context.session_manager is session_manager
    assert context.memory_engine is memory_engine


def test_plugin_context_preserves_absent_config(tmp_path: Path) -> None:
    event_bus = EventBus()
    tool_registry = ToolRegistry()
    kv_store = PluginKVStore(tmp_path / ".kv.json")

    absent = PluginContext(
        event_bus=event_bus,
        tool_registry=tool_registry,
        plugin_id="greeter",
        plugin_dir=tmp_path,
        kv_store=kv_store,
    )
    empty = PluginContext(
        event_bus=event_bus,
        tool_registry=tool_registry,
        plugin_id="greeter",
        plugin_dir=tmp_path,
        kv_store=kv_store,
        config=PluginConfig({}),
    )

    assert absent.config is None
    assert isinstance(empty.config, PluginConfig)
