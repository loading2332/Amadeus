from amadeus.lifecycle import BeforeTurnContext
from amadeus.plugin import Plugin, on_before_turn


class PromptMarker(Plugin):
    name = "prompt_marker"

    @on_before_turn(priority=50)
    async def mark_prompt(self, context: BeforeTurnContext) -> BeforeTurnContext:
        context.runtime_metadata["plugin_marker"] = "loaded through PassiveApp.start"
        return context
