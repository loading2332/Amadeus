from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class HandlerType(Enum):
    """Gate handler can modify event; Tap handler is read-only."""
    GATE = auto()
    TAP = auto()


class MetadataKind(Enum):
    """What kind of extension this metadata describes."""
    LIFECYCLE = auto()


class PluginEventType(Enum):
    """Which lifecycle seam this handler attaches to."""
    BEFORE_TURN = "before_turn"
    PROMPT_RENDER = "prompt_render"
    AFTER_TURN = "after_turn"


@dataclass
class PluginHandlerMetadata:
    """One row in the handler registry: what function, from what plugin,
    listens to what event, and how it should be invoked."""
    kind: MetadataKind
    event_type: PluginEventType
    handler_type: HandlerType
    handler: Callable[..., Any]
    handler_name: str
    plugin_module_path: str
    priority: int = 0


class PluginHandlerRegistry:
    """Ordered list of handler metadata entries, with lookup by (event, name, module)."""

    def __init__(self) -> None:
        self._handlers: list[PluginHandlerMetadata] = []

    def append(self, md: PluginHandlerMetadata) -> None:
        self._handlers.append(md)
        self._handlers.sort(key=lambda handler: -handler.priority)

    def get_by_name(
        self,
        event_type: PluginEventType,
        handler_name: str,
        module_path: str,
    ) -> PluginHandlerMetadata | None:
        for h in self._handlers:
            if (
                h.event_type == event_type
                and h.handler_name == handler_name
                and h.plugin_module_path == module_path
            ):
                return h
        return None

    def get_by_module_path(self, mp: str) -> list[PluginHandlerMetadata]:
        return [h for h in self._handlers if h.plugin_module_path == mp]

    def remove_by_module_path(self, mp: str) -> None:
        self._handlers = [h for h in self._handlers if h.plugin_module_path != mp]

    def clear(self) -> None:
        self._handlers.clear()


class PluginRegistry:
    """Container for all plugin-related registration state.

    Three kinds of state live here:
    - Handler metadata  (registered by decorators at import time)
    - Plugin classes    (registered by ``Plugin.__init_subclass__`` at import time)
    - Plugin instances  (registered by PluginManager after instantiation)
    """

    def __init__(self) -> None:
        self._handlers = PluginHandlerRegistry()
        self._classes: dict[str, list[type]] = {}
        self._instances: dict[str, object] = {}

    def register_class(self, cls: type) -> None:
        self._classes.setdefault(cls.__module__, []).append(cls)

    def get_classes(self, mp: str) -> list[type]:
        return list(self._classes.get(mp, []))

    def class_count(self, mp: str) -> int:
        return len(self._classes.get(mp, []))

    def register_instance(self, mp: str, inst: object) -> None:
        self._instances[mp] = inst

    def get_instance(self, mp: str) -> object | None:
        return self._instances.get(mp)

    def get_handlers_by_module_path(self, mp: str) -> list[PluginHandlerMetadata]:
        return self._handlers.get_by_module_path(mp)

    def remove_plugin(self, mp: str) -> None:
        self._handlers.remove_by_module_path(mp)
        self._classes.pop(mp, None)
        self._instances.pop(mp, None)

    def clear(self) -> None:
        self._handlers.clear()
        self._classes.clear()
        self._instances.clear()


# Global singleton — same pattern as Akashic's plugin_registry.
# Tests must clear() before and after each relevant test.
plugin_registry = PluginRegistry()
