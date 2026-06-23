"""Plugin whose initialize() raises — should be rolled back without residue."""
from amadeus.plugin import Plugin
from amadeus.plugin.decorators import on_before_turn


class CrashInit(Plugin):
    name = "crash_init"

    @on_before_turn()
    async def handler(self, ctx):
        ctx.runtime_metadata["crash_init"] = "should not reach"
        return ctx

    async def initialize(self) -> None:
        raise RuntimeError("initialize failed as designed")
