from __future__ import annotations

from abc import ABC

from amadeus.plugin.context import PluginContext as PluginContext
from amadeus.plugin.registry import plugin_registry


class Plugin(ABC):
    """Base class for all Amadeus plugins.

    Subclasses are automatically registered in ``plugin_registry`` when
    the module is imported (via ``__init_subclass__``).

    Minimal required convention::

        class Hello(Plugin):
            name = "hello"
            version = "0.1.0"

            context: PluginContext   # set by PluginManager after instantiation
    """

    name: str | None = None
    version: str | None = None
    desc: str | None = None
    author: str | None = None
    context: PluginContext

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        plugin_registry.register_class(cls)

    async def initialize(self) -> None:
        """Override to start plugin resources (connections, timers, models).
        Called after bind but before ``_loaded`` commit.
        If this raises, the entire plugin load is rolled back."""
        return None

    async def terminate(self) -> None:
        """Override to clean up resources.
        Called during shutdown or when a plugin is unloaded."""
        return None

    def before_turn_modules(self) -> list[object]:
        """Return phase modules contributed to the before-turn graph."""
        return []
