from __future__ import annotations

from collections.abc import Callable
from typing import Any

from amadeus.plugin.registry import (
    HandlerType,
    MetadataKind,
    PluginEventType,
    PluginHandlerMetadata,
    plugin_registry,
)


def _get_or_create_handler(
    func: Callable[..., Any],
    event_type: PluginEventType,
    handler_type: HandlerType,
    **kwargs: Any,
) -> PluginHandlerMetadata:
    """Look up an existing handler metadata entry for *func* or create one.

    This is called at **import time** (not at call time), as a side effect of
    the ``@on_before_turn()`` class-body decorator.  It writes a row into
    the global ``plugin_registry._handlers`` so that the PluginManager can
    later find and bind it.
    """
    # Idempotent: if the same (event, name, module) was already recorded
    # (e.g. because the module was re-imported), return the existing entry.
    existing = plugin_registry._handlers.get_by_name(
        event_type, func.__name__, func.__module__
    )
    if existing:
        return existing

    md = PluginHandlerMetadata(
        kind=MetadataKind.LIFECYCLE,
        event_type=event_type,
        handler_type=handler_type,
        handler=func,
        handler_name=func.__name__,
        plugin_module_path=func.__module__,
        **kwargs,
    )
    plugin_registry._handlers.append(md)
    return md


def on_before_turn(
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a method as a GATE handler for BeforeTurnContext.

    Usage::

        class MyPlugin(Plugin):
            @on_before_turn()
            async def my_handler(self, ctx: BeforeTurnContext) -> BeforeTurnContext:
                ctx.runtime_metadata["key"] = "value"
                return ctx
    """
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(
            func, PluginEventType.BEFORE_TURN, HandlerType.GATE, **options
        )
        return func
    return deco


def on_prompt_render(
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a GATE handler for PromptRenderContext."""
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(
            func, PluginEventType.PROMPT_RENDER, HandlerType.GATE, **options
        )
        return func
    return deco


def on_after_turn(
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator: register a TAP handler for AfterTurnContext (read-only)."""
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(
            func, PluginEventType.AFTER_TURN, HandlerType.TAP, **options
        )
        return func
    return deco
