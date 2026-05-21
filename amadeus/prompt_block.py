from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from amadeus.context import RuntimeContext
from amadeus.prompts import build_behavior_rules_prompt, build_static_identity_prompt


@dataclass(frozen=True)
class PromptBlockRenderResult:
    content: str
    empty_reason: Optional[str] = None

    @property
    def rendered(self) -> bool:
        return bool(self.content.strip())


class PromptBlock(Protocol):
    label: str
    priority: int
    is_static: bool

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        ...


def _read_markdown(path: Path, missing_reason: str, empty_reason: str) -> PromptBlockRenderResult:
    if not path.exists():
        return PromptBlockRenderResult("", missing_reason)

    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return PromptBlockRenderResult("", empty_reason)

    return PromptBlockRenderResult(content)


def _section(title: str, content: str) -> str:
    return f"## {title}\n\n{content.strip()}"


@dataclass(frozen=True)
class IdentityPromptBlock:
    label: str = "IdentityPromptBlock"
    priority: int = 10
    is_static: bool = True

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        return PromptBlockRenderResult(build_static_identity_prompt())


@dataclass(frozen=True)
class BehaviorRulesPromptBlock:
    label: str = "BehaviorRulesPromptBlock"
    priority: int = 20
    is_static: bool = True

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        return PromptBlockRenderResult(build_behavior_rules_prompt())


@dataclass(frozen=True)
class SelfModelPromptBlock:
    label: str = "SelfModelPromptBlock"
    priority: int = 30
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        result = _read_markdown(
            Path(context.workspace_root) / "memory" / "SELF.md",
            "missing SELF.md",
            "empty SELF.md",
        )
        if not result.rendered:
            return result
        return PromptBlockRenderResult(_section("Amadeus Self Model", result.content))


@dataclass(frozen=True)
class LongTermMemoryPromptBlock:
    label: str = "LongTermMemoryPromptBlock"
    priority: int = 40
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        result = _read_markdown(
            Path(context.workspace_root) / "memory" / "MEMORY.md",
            "missing MEMORY.md",
            "empty MEMORY.md",
        )
        if not result.rendered:
            return result
        return PromptBlockRenderResult(_section("User Long-Term Memory", result.content))


@dataclass(frozen=True)
class RecentContextPromptBlock:
    label: str = "RecentContextPromptBlock"
    priority: int = 50
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if context.recent_context_override and context.recent_context_override.strip():
            return PromptBlockRenderResult(
                _section("Recent Context", context.recent_context_override)
            )

        result = _read_markdown(
            Path(context.workspace_root) / "memory" / "RECENT_CONTEXT.md",
            "missing RECENT_CONTEXT.md",
            "empty RECENT_CONTEXT.md",
        )
        if not result.rendered:
            return result
        return PromptBlockRenderResult(_section("Recent Context", result.content))


@dataclass(frozen=True)
class RetrievedMemoryPromptBlock:
    label: str = "RetrievedMemoryPromptBlock"
    priority: int = 60
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if not context.retrieved_memory or not context.retrieved_memory.strip():
            return PromptBlockRenderResult("", "no retrieved memory")
        return PromptBlockRenderResult(_section("Retrieved Memory", context.retrieved_memory))


@dataclass(frozen=True)
class ActiveSkillsPromptBlock:
    label: str = "ActiveSkillsPromptBlock"
    priority: int = 70
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        skills = [skill.strip() for skill in context.active_skills if skill.strip()]
        if not skills:
            return PromptBlockRenderResult("", "no active skills")
        return PromptBlockRenderResult(
            _section("Active Skills", "\n".join(f"- {skill}" for skill in skills))
        )


@dataclass(frozen=True)
class RuntimeMetadataPromptBlock:
    label: str = "RuntimeMetadataPromptBlock"
    priority: int = 80
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if not context.runtime_metadata:
            return PromptBlockRenderResult("", "no runtime metadata")

        lines = [
            f"- {key}: {context.runtime_metadata[key]}"
            for key in sorted(context.runtime_metadata)
        ]
        return PromptBlockRenderResult(_section("Runtime Metadata", "\n".join(lines)))
