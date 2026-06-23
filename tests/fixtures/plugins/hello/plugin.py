"""Minimal plugin that marks runtime_metadata on every turn."""
from amadeus.plugin import Plugin, PluginContext
from amadeus.plugin.decorators import on_before_turn


class Hello(Plugin):
    name = "hello"
    version = "0.1.0"

    @on_before_turn()
    async def on_before(self, ctx):
        ctx.runtime_metadata["hello"] = "touched"
        return ctx

    context: PluginContext
