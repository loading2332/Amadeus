from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Literal, Optional, Tuple, TypedDict


class Message(TypedDict):
    role: Literal["system", "user", "assistant", "tool"]
    content: str


@dataclass
class RuntimeContext:
    workspace_root: Path
    history: List[Message]
    current_user_message: str
    retrieved_memory: Optional[str] = None
    active_skills: List[str] = field(default_factory=list)
    runtime_metadata: Dict[str, str] = field(default_factory=dict)
    recent_context_override: Optional[str] = None


@dataclass(frozen=True)
class PromptDebugEntry:
    label: str
    priority: int
    rendered: bool
    char_count: int
    estimated_tokens: int
    empty_reason: Optional[str] = None


@dataclass(frozen=True)
class SystemPromptResult:
    prompt: str
    breakdown: List[PromptDebugEntry]


@dataclass(frozen=True)
class ContextRenderResult:
    messages: List[Message]
    system_prompt: SystemPromptResult


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return (len(text) + 3) // 4


class SystemPromptBuilder:
    def __init__(self, blocks: Iterable[object], separator: str = "\n\n---\n\n") -> None:
        self.blocks = list(blocks)
        self.separator = separator
        self._static_cache: Dict[str, object] = {}

    def build(self, context: RuntimeContext) -> SystemPromptResult:
        rendered_sections: List[str] = []
        breakdown: List[PromptDebugEntry] = []

        for block in sorted(self.blocks, key=lambda item: item.priority):
            result = self._render_block(block, context)
            content = result.content.strip()
            is_rendered = bool(content)

            if is_rendered:
                rendered_sections.append(content)

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
        )

    def _render_block(self, block: object, context: RuntimeContext) -> object:
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
        history: List[Message],
        current_user_message: str,
    ) -> List[Message]:
        if any(message["role"] == "system" for message in history):
            raise ValueError("history must not contain system messages")

        return [
            {"role": "system", "content": system_prompt},
            *history,
            {"role": "user", "content": current_user_message},
        ]


class ContextBuilder:
    def __init__(
        self,
        blocks: Optional[Iterable[object]] = None,
        system_prompt_builder: Optional[SystemPromptBuilder] = None,
        message_envelope_builder: Optional[MessageEnvelopeBuilder] = None,
    ) -> None:
        selected_blocks = list(blocks) if blocks is not None else list(self.default_blocks())
        self.system_prompt_builder = system_prompt_builder or SystemPromptBuilder(
            selected_blocks
        )
        self.message_envelope_builder = message_envelope_builder or MessageEnvelopeBuilder()

    @staticmethod
    def default_blocks() -> Tuple[object, ...]:
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

        return (
            IdentityPromptBlock(),
            BehaviorRulesPromptBlock(),
            SelfModelPromptBlock(),
            LongTermMemoryPromptBlock(),
            RecentContextPromptBlock(),
            RetrievedMemoryPromptBlock(),
            ActiveSkillsPromptBlock(),
            RuntimeMetadataPromptBlock(),
        )

    def render(self, context: RuntimeContext) -> ContextRenderResult:
        system_prompt = self.system_prompt_builder.build(context)
        messages = self.message_envelope_builder.build(
            system_prompt=system_prompt.prompt,
            history=context.history,
            current_user_message=context.current_user_message,
        )
        return ContextRenderResult(messages=messages, system_prompt=system_prompt)
