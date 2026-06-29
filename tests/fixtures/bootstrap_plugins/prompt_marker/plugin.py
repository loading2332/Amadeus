from typing import cast

from amadeus.before_turn import BeforeTurnFrame
from amadeus.lifecycle import BeforeTurnContext
from amadeus.plugin import Plugin
from amadeus.prompt_render import PromptRenderCtx, PromptRenderFrame
from amadeus.prompting import PromptSectionRender


class PromptMarkerModule:
    slot = "prompt_marker.before_turn"
    requires = ("before_turn.build_ctx", "session:ctx")
    produces = ("session:ctx",)

    async def run(self, frame: BeforeTurnFrame) -> BeforeTurnFrame:
        context = cast(BeforeTurnContext, frame.slots["session:ctx"])
        context.runtime_metadata["plugin_marker"] = "loaded through PassiveApp.start"
        return frame


class PromptRenderMarkerModule:
    slot = "prompt_marker.prompt_render"
    requires = ("prompt_render.emit", "prompt:ctx")
    produces = ("prompt:ctx",)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        context = cast(PromptRenderCtx, frame.slots["prompt:ctx"])
        context.system_sections_bottom.append(
            PromptSectionRender(
                label="prompt_render_marker",
                content="prompt render module reached provider",
                priority=8_000,
                is_static=False,
            )
        )
        return frame


class PromptMarker(Plugin):
    name = "prompt_marker"

    def before_turn_modules(self) -> list[object]:
        return [PromptMarkerModule()]

    def prompt_render_modules(self) -> list[object]:
        return [PromptRenderMarkerModule()]
