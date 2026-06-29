from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NotRequired, Protocol, TypedDict, cast

from amadeus.prompting.assembler import (
    PromptAssembler,
    PromptAssemblyResult,
    PromptSectionRender,
)


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: Any
    tool_call_id: NotRequired[str]
    tool_calls: NotRequired[list[dict[str, Any]]]
    reasoning_content: NotRequired[str]


@dataclass
class RuntimeContext:
    workspace_root: Path
    history: list[Message]
    current_user_message: str
    retrieved_memory: str | None = None
    active_skills: list[str] = field(default_factory=list)
    runtime_metadata: dict[str, str] = field(default_factory=dict)
    recent_context_override: str | None = None
    disabled_sections: set[str] = field(default_factory=set)
    turn_injection_context: dict[str, str] = field(default_factory=dict)
    history_window: int | None = None


@dataclass(frozen=True)
class PromptDebugEntry:
    label: str
    priority: int
    rendered: bool
    char_count: int
    estimated_tokens: int
    empty_reason: str | None = None
    destination: Literal["system", "context_frame"] | None = None


@dataclass(frozen=True)
class SystemPromptResult:
    prompt: str
    breakdown: list[PromptDebugEntry]
    sections: list[PromptSectionRender] = field(default_factory=list)


@dataclass(frozen=True)
class ContextFrameResult:
    prompt: str
    breakdown: list[PromptDebugEntry]
    sections: list[PromptSectionRender] = field(default_factory=list)


@dataclass(frozen=True)
class ContextRenderResult:
    messages: list[Message]
    system_prompt: SystemPromptResult
    context_frame: ContextFrameResult
    assembly: PromptAssemblyResult


class PromptBlockRenderResult(Protocol):
    content: str
    empty_reason: str | None


class PromptBlockLike(Protocol):
    label: str
    priority: int
    is_static: bool

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult: ...


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 3) // 4


class SystemPromptBuilder:
    def __init__(
        self,
        blocks: Iterable[PromptBlockLike],
        separator: str = "\n\n---\n\n",
    ) -> None:
        self.blocks = list(blocks)
        self.separator = separator
        self._static_cache: dict[str, PromptBlockRenderResult] = {}

    def build(self, context: RuntimeContext) -> SystemPromptResult:
        rendered_sections: list[str] = []
        section_renders: list[PromptSectionRender] = []
        breakdown: list[PromptDebugEntry] = []

        for block in sorted(self.blocks, key=lambda item: item.priority):
            result = self._render_block(block, context)
            content = result.content.strip()
            is_rendered = bool(content)

            if is_rendered:
                rendered_sections.append(content)
                section_renders.append(
                    PromptSectionRender(
                        label=block.label,
                        content=content,
                        priority=block.priority,
                        is_static=block.is_static,
                    )
                )

            breakdown.append(
                PromptDebugEntry(
                    label=block.label,
                    priority=block.priority,
                    rendered=is_rendered,
                    char_count=len(content),
                    estimated_tokens=_estimate_tokens(content),
                    empty_reason=None if is_rendered else result.empty_reason,
                )
            )

        return SystemPromptResult(
            prompt=self.separator.join(rendered_sections),
            breakdown=breakdown,
            sections=section_renders,
        )

    def _render_block(
        self,
        block: PromptBlockLike,
        context: RuntimeContext,
    ) -> PromptBlockRenderResult:
        if block.is_static and block.label in self._static_cache:
            return self._static_cache[block.label]

        result = block.render(context)
        if block.is_static:
            self._static_cache[block.label] = result
        return result


class MessageEnvelopeBuilder:
    def build(
        self,
        system_prompt: str,
        history: list[Message],
        current_user_message: str,
        context_frame: str = "",
    ) -> list[Message]:
        if any(message["role"] == "system" for message in history):
            raise ValueError("history must not contain system messages")

        messages: list[Message] = [
            {"role": "system", "content": system_prompt},
            *history,
        ]
        if context_frame.strip():
            messages.append({"role": "user", "content": context_frame})
        messages.append({"role": "user", "content": current_user_message})
        return messages


class ContextBuilder:
    def __init__(
        self,
        blocks: Iterable[PromptBlockLike] | None = None,
        system_prompt_builder: SystemPromptBuilder | None = None,
        message_envelope_builder: MessageEnvelopeBuilder | None = None,
        prompt_assembler: PromptAssembler | None = None,
    ) -> None:
        selected_blocks = list(blocks) if blocks is not None else list(self.default_blocks())
        self.system_prompt_builder = system_prompt_builder or SystemPromptBuilder(
            selected_blocks
        )
        self.message_envelope_builder = message_envelope_builder or MessageEnvelopeBuilder()
        self.prompt_assembler = prompt_assembler or PromptAssembler()

    @staticmethod
    def default_blocks() -> tuple[PromptBlockLike, ...]:
        from amadeus.prompt_block import (
            ActiveSkillsPromptBlock,
            BehaviorRulesPromptBlock,
            IdentityPromptBlock,
            LongTermMemoryPromptBlock,
            RecentContextPromptBlock,
            RetrievedMemoryPromptBlock,
            RuntimeMetadataPromptBlock,
            SelfModelPromptBlock,
        )

        return cast(
            tuple[PromptBlockLike, ...],
            (
            IdentityPromptBlock(),
            BehaviorRulesPromptBlock(),
            SelfModelPromptBlock(),
            LongTermMemoryPromptBlock(),
            RecentContextPromptBlock(),
            RetrievedMemoryPromptBlock(),
            ActiveSkillsPromptBlock(),
            RuntimeMetadataPromptBlock(),
            ),
        )

    def render(self, context: RuntimeContext) -> ContextRenderResult:
        return self.render_with_sections(context)

    def render_with_sections(
        self,
        context: RuntimeContext,
        *,
        system_sections_top: list[PromptSectionRender] | None = None,
        system_sections_bottom: list[PromptSectionRender] | None = None,
    ) -> ContextRenderResult:
        built = self.system_prompt_builder.build(context)
        top_sections = list(system_sections_top or [])
        bottom_sections = list(system_sections_bottom or [])
        assembly = self.prompt_assembler.assemble(
            [*top_sections, *built.sections, *bottom_sections],
            disabled_sections=context.disabled_sections,
            turn_injection_context=context.turn_injection_context,
        )
        system_breakdown = self._filtered_breakdown(
            [
                *self._section_breakdown(top_sections),
                *built.breakdown,
                *self._section_breakdown(bottom_sections),
            ],
            assembly.system_sections,
            context.disabled_sections,
            destination="system",
            context_frame_sections=self.prompt_assembler.context_frame_sections,
        )
        frame_breakdown = self._filtered_breakdown(
            [
                *self._section_breakdown(top_sections),
                *built.breakdown,
                *self._section_breakdown(bottom_sections),
            ],
            assembly.frame_sections,
            context.disabled_sections,
            destination="context_frame",
            context_frame_sections=self.prompt_assembler.context_frame_sections,
        )
        system_prompt = SystemPromptResult(
            prompt=assembly.system_prompt,
            breakdown=system_breakdown,
            sections=assembly.system_sections,
        )
        context_frame = ContextFrameResult(
            prompt=assembly.context_frame,
            breakdown=frame_breakdown,
            sections=assembly.frame_sections,
        )
        history = self._slice_history(context.history, context.history_window)
        messages = self.message_envelope_builder.build(
            system_prompt=system_prompt.prompt,
            history=history,
            context_frame=context_frame.prompt,
            current_user_message=context.current_user_message,
        )
        return ContextRenderResult(
            messages=messages,
            system_prompt=system_prompt,
            context_frame=context_frame,
            assembly=assembly,
        )

    @staticmethod
    def _section_breakdown(
        sections: list[PromptSectionRender],
    ) -> list[PromptDebugEntry]:
        return [
            PromptDebugEntry(
                label=section.label,
                priority=section.priority,
                rendered=bool(section.content.strip()),
                char_count=len(section.content.strip()),
                estimated_tokens=_estimate_tokens(section.content.strip()),
                empty_reason=None if section.content.strip() else "empty section",
            )
            for section in sections
        ]

    @staticmethod
    def _slice_history(
        history: list[Message],
        history_window: int | None,
    ) -> list[Message]:
        if history_window is None:
            return history
        if history_window <= 0:
            return []
        return history[-history_window:]

    @staticmethod
    def _filtered_breakdown(
        breakdown: list[PromptDebugEntry],
        sections: list[PromptSectionRender],
        disabled_sections: set[str],
        destination: Literal["system", "context_frame"],
        context_frame_sections: set[str],
    ) -> list[PromptDebugEntry]:
        rendered_entries = [
            PromptDebugEntry(
                label=entry.label,
                priority=entry.priority,
                rendered=entry.rendered,
                char_count=entry.char_count,
                estimated_tokens=entry.estimated_tokens,
                empty_reason=entry.empty_reason,
                destination=destination,
            )
            for entry in breakdown
            if entry.label not in disabled_sections
            and (
                entry.label in context_frame_sections
                if destination == "context_frame"
                else entry.label not in context_frame_sections
            )
        ]
        injected_entries = [
            PromptDebugEntry(
                label=section.label,
                priority=section.priority,
                rendered=True,
                char_count=len(section.content),
                estimated_tokens=_estimate_tokens(section.content),
                destination=destination,
            )
            for section in sections
            if not any(entry.label == section.label for entry in breakdown)
        ]
        return [*rendered_entries, *injected_entries]
