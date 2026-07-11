from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.provider import LLMToolCall


@dataclass
class ReasonerResult:
    """Result from a multi-step reasoner loop.

    Attributes:
        reply: Final assistant reply text.
        tool_chain: List of tool-call groups, one per LLM round that
                    produced tool_calls. Each call keeps the executed business
                    ``arguments`` alongside status, result, and hook traces.
        invocations: Flat list of all LLMToolCall made during the loop.
        provider_raw: Raw provider response object (for after_reasoning commit).
        metadata: Extra runtime metadata (tools_used, react_stats, …).
    """
    reply: str
    tool_chain: list[dict[str, Any]] = field(default_factory=list)
    invocations: list[LLMToolCall] = field(default_factory=list)
    provider_raw: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
