from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

from amadeus.context import ContextBuilder, RuntimeContext
from amadeus.events import EventBus
from amadeus.lifecycle import PromptRenderContext, TurnLifecycle
from amadeus.phase import Phase, inspect_phase
from amadeus.prompt_render import (
    PromptRenderFrame,
    PromptRenderInput,
    PromptRenderResult,
    default_prompt_render_modules,
)
from amadeus.prompting import PromptSectionRender


def _input(
    tmp_path: Path,
    *,
    session_key: str = "chat:1",
    attempt_index: int = 0,
    attempt_name: str = "full",
    runtime_context: RuntimeContext | None = None,
) -> PromptRenderInput:
    context = RuntimeContext(
        workspace_root=tmp_path,
        history=[],
        current_user_message="hello",
        retrieved_memory="remember this",
    )
    return PromptRenderInput(
        session_key=session_key,
        attempt_index=attempt_index,
        attempt_name=attempt_name,
        runtime_context=runtime_context or context,
    )


def _phase(
    *,
    lifecycle: TurnLifecycle | None = None,
    context_builder: ContextBuilder | None = None,
    plugin_modules: list[object] | None = None,
) -> Phase[PromptRenderInput, PromptRenderResult, PromptRenderFrame]:
    return Phase(
        default_prompt_render_modules(
            lifecycle=lifecycle or TurnLifecycle(EventBus()),
            context_builder=context_builder or ContextBuilder(),
            plugin_modules=cast(Any, plugin_modules or []),
        ),
        frame_factory=PromptRenderFrame,
    )


class _DirectBottomModule:
    slot = "plugin.direct_bottom"
    requires = ("prompt_render.emit", "prompt:ctx")
    produces = ("prompt:ctx",)

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        ctx = cast(Any, frame.slots["prompt:ctx"])
        ctx.system_sections_bottom.append(
            PromptSectionRender(
                label="plugin_bottom",
                content="bottom plugin section",
                priority=8_000,
                is_static=False,
            )
        )
        return frame


class _ExportModule:
    slot = "plugin.exports"
    requires = ("prompt_render.emit", "prompt:ctx")
    produces = (
        "prompt:section_top:plugin_top",
        "prompt:section_bottom:plugin_bottom_export",
        "prompt:extra_hint:plugin_hint",
    )

    async def run(self, frame: PromptRenderFrame) -> PromptRenderFrame:
        frame.slots["prompt:section_top:plugin_top"] = PromptSectionRender(
            label="plugin_top",
            content="top export section",
            priority=-100,
            is_static=False,
        )
        frame.slots["prompt:section_bottom:plugin_bottom_export"] = (
            "bottom export section"
        )
        frame.slots["prompt:extra_hint:plugin_hint"] = "remember plugin hint"
        return frame


def test_prompt_render_phase_renders_lifecycle_and_plugin_sections(
    tmp_path: Path,
) -> None:
    lifecycle = TurnLifecycle(EventBus())

    def mark(context: PromptRenderContext) -> None:
        context.runtime_context.turn_injection_context["lifecycle"] = (
            "lifecycle marker"
        )

    lifecycle.on_prompt_render(mark)
    phase = _phase(lifecycle=lifecycle, plugin_modules=[_DirectBottomModule()])

    result = asyncio.run(phase.run(_input(tmp_path)))

    rendered_text = "\n".join(str(message["content"]) for message in result.messages)
    assert "bottom plugin section" in rendered_text
    assert "lifecycle marker" in rendered_text
    assert result.rendered.messages == result.messages


def test_prompt_render_phase_collects_export_slots_and_extra_hints(
    tmp_path: Path,
) -> None:
    phase = _phase(plugin_modules=[_ExportModule()])

    result = asyncio.run(phase.run(_input(tmp_path)))

    rendered_text = "\n".join(str(message["content"]) for message in result.messages)
    assert "top export section" in rendered_text
    assert "bottom export section" in rendered_text
    assert "remember plugin hint" in rendered_text
    assert result.rendered.system_prompt.breakdown[0].label == "plugin_top"


def test_prompt_render_phase_respects_disabled_plugin_sections(
    tmp_path: Path,
) -> None:
    phase = _phase(plugin_modules=[_DirectBottomModule()])
    input = _input(tmp_path)
    input.runtime_context.disabled_sections.add("plugin_bottom")

    result = asyncio.run(phase.run(input))

    rendered_text = "\n".join(str(message["content"]) for message in result.messages)
    assert "bottom plugin section" not in rendered_text
    assert "plugin_bottom" not in [
        entry.label for entry in result.rendered.system_prompt.breakdown
    ]


def test_prompt_render_phase_inspection_exposes_real_graph() -> None:
    modules = default_prompt_render_modules(
        lifecycle=TurnLifecycle(EventBus()),
        context_builder=ContextBuilder(),
        plugin_modules=[_DirectBottomModule()],
    )

    report = inspect_phase(modules)

    assert "prompt_render.build_ctx" in report
    assert "prompt_render.emit" in report
    assert "plugin.direct_bottom" in report
    assert "prompt_render.collect_exports" in report
    assert "prompt_render.render" in report
    assert "prompt_render.return" in report
