"""Amadeus runtime context and prompt assembly package."""

from amadeus.context import (
    ContextFrameResult,
    ContextBuilder,
    ContextRenderResult,
    Message,
    MessageEnvelopeBuilder,
    PromptDebugEntry,
    RuntimeContext,
    SystemPromptBuilder,
    SystemPromptResult,
)
from amadeus.prompting import (
    DEFAULT_CONTEXT_TRIM_PLANS,
    PromptAssembler,
    PromptAssemblyResult,
    PromptSectionRender,
    build_context_trim_attempts,
)
from amadeus.prompt_block import (
    ActiveSkillsPromptBlock,
    BehaviorRulesPromptBlock,
    IdentityPromptBlock,
    LongTermMemoryPromptBlock,
    PromptBlock,
    PromptBlockRenderResult,
    RecentContextPromptBlock,
    RetrievedMemoryPromptBlock,
    RuntimeMetadataPromptBlock,
    SelfModelPromptBlock,
)
from amadeus.workspace import DEFAULT_SELF_MD, initialize_workspace

__all__ = [
    "ActiveSkillsPromptBlock",
    "BehaviorRulesPromptBlock",
    "ContextFrameResult",
    "ContextBuilder",
    "ContextRenderResult",
    "DEFAULT_SELF_MD",
    "DEFAULT_CONTEXT_TRIM_PLANS",
    "IdentityPromptBlock",
    "LongTermMemoryPromptBlock",
    "Message",
    "MessageEnvelopeBuilder",
    "PromptBlock",
    "PromptBlockRenderResult",
    "PromptAssembler",
    "PromptAssemblyResult",
    "PromptDebugEntry",
    "PromptSectionRender",
    "RecentContextPromptBlock",
    "RetrievedMemoryPromptBlock",
    "RuntimeContext",
    "RuntimeMetadataPromptBlock",
    "SelfModelPromptBlock",
    "SystemPromptBuilder",
    "SystemPromptResult",
    "build_context_trim_attempts",
    "initialize_workspace",
]
