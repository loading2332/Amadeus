"""Amadeus runtime context and prompt assembly package."""

from amadeus.context import (
    ContextBuilder,
    ContextRenderResult,
    Message,
    MessageEnvelopeBuilder,
    PromptDebugEntry,
    RuntimeContext,
    SystemPromptBuilder,
    SystemPromptResult,
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
    "ContextBuilder",
    "ContextRenderResult",
    "DEFAULT_SELF_MD",
    "IdentityPromptBlock",
    "LongTermMemoryPromptBlock",
    "Message",
    "MessageEnvelopeBuilder",
    "PromptBlock",
    "PromptBlockRenderResult",
    "PromptDebugEntry",
    "RecentContextPromptBlock",
    "RetrievedMemoryPromptBlock",
    "RuntimeContext",
    "RuntimeMetadataPromptBlock",
    "SelfModelPromptBlock",
    "SystemPromptBuilder",
    "SystemPromptResult",
    "initialize_workspace",
]
