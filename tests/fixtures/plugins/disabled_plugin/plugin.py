"""This plugin should never be loaded — a .disabled marker sits next to it."""
from amadeus.plugin import Plugin
from amadeus.plugin.decorators import on_before_turn


class Disabled(Plugin):
    name = "disabled_plugin"

    @on_before_turn()
    async def do_not_call(self, ctx):
        raise RuntimeError("disabled plugin should not be loaded")
