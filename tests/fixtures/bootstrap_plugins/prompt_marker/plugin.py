from typing import cast

from amadeus.before_turn import BeforeTurnFrame
from amadeus.lifecycle import BeforeTurnContext
from amadeus.plugin import Plugin


class PromptMarkerModule:
    slot = "prompt_marker.before_turn"
    requires = ("before_turn.build_ctx", "session:ctx")
    produces = ("session:ctx",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        context = cast(BeforeTurnContext, frame.slots["session:ctx"])
        context.runtime_metadata["plugin_marker"] = "loaded through PassiveApp.start"
        return frame


class PromptMarker(Plugin):
    name = "prompt_marker"

    def before_turn_modules(self) -> list[object]:
        return [PromptMarkerModule()]
