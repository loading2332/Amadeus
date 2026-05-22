from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from amadeus.context import RuntimeContext
from amadeus.prompts import build_behavior_rules_prompt, build_static_identity_prompt


@dataclass(frozen=True)
class PromptBlockRenderResult:
    content: str
    empty_reason: str | None = None

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


def _strip_section_heading(content: str) -> str:
    lines = content.strip().splitlines()
    if not lines or not lines[0].startswith("#"):
        return content.strip()
    return "\n".join(lines[1:]).strip()


def _strip_recent_turns(content: str) -> str:
    kept_lines = []
    for line in content.splitlines():
        if line.strip() == "## Recent Turns":
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


def _recent_context_result(content: str) -> PromptBlockRenderResult:
    trimmed = _strip_recent_turns(content)
    if not trimmed:
        return PromptBlockRenderResult("", "recent context only contained recent turns")
    return PromptBlockRenderResult(_strip_section_heading(trimmed))


@dataclass(frozen=True)
class IdentityPromptBlock:
    label: str = "identity"
    priority: int = 10
    is_static: bool = True

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        return PromptBlockRenderResult(_strip_section_heading(build_static_identity_prompt()))


@dataclass(frozen=True)
class BehaviorRulesPromptBlock:
    label: str = "behavior_rules"
    priority: int = 20
    is_static: bool = True

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        return PromptBlockRenderResult(
            _strip_section_heading(build_behavior_rules_prompt())
        )


@dataclass(frozen=True)
class SelfModelPromptBlock:
    label: str = "self_model"
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
        return PromptBlockRenderResult(result.content)


@dataclass(frozen=True)
class LongTermMemoryPromptBlock:
    label: str = "long_term_memory"
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
        return PromptBlockRenderResult(result.content)


@dataclass(frozen=True)
class RecentContextPromptBlock:
    label: str = "recent_context"
    priority: int = 50
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if context.recent_context_override and context.recent_context_override.strip():
            return _recent_context_result(context.recent_context_override)

        result = _read_markdown(
            Path(context.workspace_root) / "memory" / "RECENT_CONTEXT.md",
            "missing RECENT_CONTEXT.md",
            "empty RECENT_CONTEXT.md",
        )
        if not result.rendered:
            return result
        return _recent_context_result(result.content)


@dataclass(frozen=True)
class RetrievedMemoryPromptBlock:
    label: str = "retrieved_memory"
    priority: int = 60
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if not context.retrieved_memory or not context.retrieved_memory.strip():
            return PromptBlockRenderResult("", "no retrieved memory")
        return PromptBlockRenderResult(context.retrieved_memory)


@dataclass(frozen=True)
class ActiveSkillsPromptBlock:
    label: str = "active_skills"
    priority: int = 70
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        skills = [skill.strip() for skill in context.active_skills if skill.strip()]
        if not skills:
            return PromptBlockRenderResult("", "no active skills")
        return PromptBlockRenderResult("\n".join(f"- {skill}" for skill in skills))


@dataclass(frozen=True)
class RuntimeMetadataPromptBlock:
    label: str = "runtime_metadata"
    priority: int = 80
    is_static: bool = False

    def render(self, context: RuntimeContext) -> PromptBlockRenderResult:
        if not context.runtime_metadata:
            return PromptBlockRenderResult("", "no runtime metadata")

        lines = [
            f"- {key}: {context.runtime_metadata[key]}"
            for key in sorted(context.runtime_metadata)
        ]
        return PromptBlockRenderResult("\n".join(lines))
