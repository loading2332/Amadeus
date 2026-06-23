"""Plugin that reads its configured greeting from PluginContext.config."""
from amadeus.plugin import Plugin, PluginContext
from amadeus.plugin.decorators import on_before_turn


class Greeter(Plugin):
    name = "greeter"

    @on_before_turn()
    async def greet(self, ctx):
        assert self.context.config is not None
        greeting = self.context.config.get("greeting", "Hello")
        ctx.runtime_metadata["greeting"] = greeting
        return ctx

    context: PluginContext
