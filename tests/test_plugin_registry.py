from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from pathlib import Path
from typing import Any, cast

import amadeus.plugin.decorators as plugin_decorators
import pytest
from amadeus.plugin import (
    HandlerType,
    MetadataKind,
    PluginCandidate,
    PluginDiscoveryResult,
    PluginEventType,
    PluginHandlerMetadata,
    PluginLoadRecord,
    PluginLoadReport,
    PluginLoadStatus,
    PluginRegistry,
)
from amadeus.plugin.registry import PluginHandlerRegistry


def _handler_metadata(
    name: str,
    module_path: str,
    *,
    priority: int = 0,
) -> PluginHandlerMetadata:
    def handler() -> None:
        return None

    return PluginHandlerMetadata(
        kind=MetadataKind.LIFECYCLE,
        event_type=PluginEventType.BEFORE_TURN,
        handler_type=HandlerType.GATE,
        handler=handler,
        handler_name=name,
        plugin_module_path=module_path,
        priority=priority,
    )


def test_registry_preserves_every_class_registered_by_one_module() -> None:
    registry = PluginRegistry()
    first = type("First", (), {"__module__": "test_plugin_module"})
    second = type("Second", (), {"__module__": "test_plugin_module"})

    registry.register_class(first)
    registry.register_class(second)

    assert registry.get_classes("test_plugin_module") == [first, second]
    assert registry.class_count("test_plugin_module") == 2


def test_registry_get_classes_returns_a_copy() -> None:
    registry = PluginRegistry()
    plugin_class = type("PluginClass", (), {"__module__": "test_plugin_module"})
    registry.register_class(plugin_class)

    classes = registry.get_classes("test_plugin_module")
    classes.clear()

    assert registry.get_classes("test_plugin_module") == [plugin_class]
    assert registry.get_classes("unknown") == []
    assert registry.class_count("unknown") == 0


def test_registry_registers_and_gets_instance() -> None:
    registry = PluginRegistry()
    instance = object()

    registry.register_instance("plugin.module", instance)

    assert registry.get_instance("plugin.module") is instance
    assert registry.get_instance("unknown") is None


def test_handler_registry_orders_by_descending_priority_with_stable_ties() -> None:
    handlers = PluginHandlerRegistry()
    low = _handler_metadata("low", "plugin.module", priority=0)
    high_first = _handler_metadata("high_first", "plugin.module", priority=100)
    high_second = _handler_metadata("high_second", "plugin.module", priority=100)

    handlers.append(low)
    handlers.append(high_first)
    handlers.append(high_second)

    assert handlers.get_by_module_path("plugin.module") == [
        high_first,
        high_second,
        low,
    ]


def test_handler_metadata_cannot_mutate_registry_identity_or_priority() -> None:
    metadata = _handler_metadata("handler", "plugin.module", priority=10)
    externally_typed_metadata = cast(Any, metadata)

    with pytest.raises(FrozenInstanceError):
        externally_typed_metadata.priority = 100

    with pytest.raises(FrozenInstanceError):
        externally_typed_metadata.plugin_module_path = "another.module"


def test_handler_lookup_and_removal_match_only_the_requested_module() -> None:
    handlers = PluginHandlerRegistry()
    first = _handler_metadata("shared", "plugin.first")
    second = _handler_metadata("shared", "plugin.second")
    handlers.append(first)
    handlers.append(second)

    assert (
        handlers.get_by_name(
            PluginEventType.BEFORE_TURN,
            "shared",
            "plugin.first",
        )
        is first
    )
    assert handlers.get_by_module_path("plugin.first") == [first]

    handlers.remove_by_module_path("plugin.first")

    assert handlers.get_by_module_path("plugin.first") == []
    assert handlers.get_by_module_path("plugin.second") == [second]

    handlers.clear()
    assert handlers.get_by_module_path("plugin.second") == []


def test_lifecycle_decorators_preserve_priority_and_are_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = [
        (
            plugin_decorators.on_before_turn,
            PluginEventType.BEFORE_TURN,
            HandlerType.GATE,
        ),
        (
            plugin_decorators.on_prompt_render,
            PluginEventType.PROMPT_RENDER,
            HandlerType.GATE,
        ),
        (
            plugin_decorators.on_after_turn,
            PluginEventType.AFTER_TURN,
            HandlerType.TAP,
        ),
    ]

    def handler() -> None:
        return None

    for decorator, event_type, handler_type in cases:
        registry = PluginRegistry()
        monkeypatch.setattr(plugin_decorators, "plugin_registry", registry)

        decorated = decorator(priority=42)(handler)
        decorated_again = decorator(priority=42)(handler)
        metadata = registry.get_handlers_by_module_path(handler.__module__)

        assert decorated is handler
        assert decorated_again is handler
        assert len(metadata) == 1
        assert metadata[0].event_type is event_type
        assert metadata[0].handler_type is handler_type
        assert metadata[0].priority == 42


def test_remove_plugin_removes_only_one_modules_declaration_state() -> None:
    registry = PluginRegistry()
    first_class = type("First", (), {"__module__": "plugin.first"})
    second_class = type("Second", (), {"__module__": "plugin.second"})
    first_instance = object()
    second_instance = object()
    first_handler = _handler_metadata("first", "plugin.first")
    second_handler = _handler_metadata("second", "plugin.second")
    registry.register_class(first_class)
    registry.register_class(second_class)
    registry.register_instance("plugin.first", first_instance)
    registry.register_instance("plugin.second", second_instance)
    registry._handlers.append(first_handler)
    registry._handlers.append(second_handler)

    registry.remove_plugin("plugin.first")

    assert registry.get_classes("plugin.first") == []
    assert registry.get_instance("plugin.first") is None
    assert registry.get_handlers_by_module_path("plugin.first") == []
    assert registry.get_classes("plugin.second") == [second_class]
    assert registry.get_instance("plugin.second") is second_instance
    assert registry.get_handlers_by_module_path("plugin.second") == [second_handler]


def test_registry_clear_empties_all_declaration_state() -> None:
    registry = PluginRegistry()
    plugin_class = type("PluginClass", (), {"__module__": "plugin.module"})
    registry.register_class(plugin_class)
    registry.register_instance("plugin.module", object())
    registry._handlers.append(_handler_metadata("handler", "plugin.module"))

    registry.clear()

    assert registry.get_classes("plugin.module") == []
    assert registry.get_instance("plugin.module") is None
    assert registry.get_handlers_by_module_path("plugin.module") == []


def test_plugin_load_status_has_only_the_public_status_values() -> None:
    assert [(status.name, status.value) for status in PluginLoadStatus] == [
        ("LOADED", "loaded"),
        ("DISABLED", "disabled"),
        ("DUPLICATE", "duplicate"),
        ("ALREADY_LOADED", "already_loaded"),
        ("FAILED", "failed"),
    ]


def test_candidate_discovery_and_load_record_have_stable_shapes(tmp_path: Path) -> None:
    candidate = PluginCandidate(
        name="hello",
        source="workspace",
        plugin_dir=tmp_path / "hello",
        module_path=tmp_path / "hello" / "plugin.py",
        import_path="amadeus_plugin_workspace_hello",
    )
    record = PluginLoadRecord(
        name="hello",
        source="workspace",
        import_path=candidate.import_path,
        status=PluginLoadStatus.FAILED,
        stage="initialize",
        message="initialize failed",
    )
    discovery = PluginDiscoveryResult(candidates=(candidate,), records=(record,))

    assert [field.name for field in fields(PluginCandidate)] == [
        "name",
        "source",
        "plugin_dir",
        "module_path",
        "import_path",
    ]
    assert [field.name for field in fields(PluginLoadRecord)] == [
        "name",
        "source",
        "import_path",
        "status",
        "stage",
        "message",
    ]
    assert discovery.candidates == (candidate,)
    assert discovery.records == (record,)


def test_load_report_filters_records_in_original_order() -> None:
    statuses = (
        PluginLoadStatus.LOADED,
        PluginLoadStatus.FAILED,
        PluginLoadStatus.LOADED,
        PluginLoadStatus.DISABLED,
        PluginLoadStatus.DUPLICATE,
        PluginLoadStatus.ALREADY_LOADED,
    )
    records = tuple(
        PluginLoadRecord(
            name=f"plugin-{index}",
            source="workspace",
            import_path=f"plugin_{index}",
            status=status,
        )
        for index, status in enumerate(statuses)
    )
    report = PluginLoadReport(records=records)

    assert report.records is records
    assert report.loaded == (records[0], records[2])
    assert report.failed == (records[1],)
    assert report.disabled == (records[3],)
    assert report.duplicate == (records[4],)
    assert report.already_loaded == (records[5],)


def test_load_record_exposes_only_the_structured_report_boundary() -> None:
    message = "initialize failed"
    record = PluginLoadRecord(
        name="broken",
        source="workspace",
        import_path="amadeus_plugin_workspace_broken",
        status=PluginLoadStatus.FAILED,
        stage="initialize",
        message=message,
    )

    assert [field.name for field in fields(record)] == [
        "name",
        "source",
        "import_path",
        "status",
        "stage",
        "message",
    ]
    assert record.message == message
    forbidden_fields = {
        "config",
        "traceback",
        "exception",
        "error",
        "raw_error",
    }
    assert forbidden_fields.isdisjoint(field.name for field in fields(record))
