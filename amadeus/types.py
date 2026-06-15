from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.provider import LLMToolCall


@dataclass
class ReasonerResult:
    """Akashic-aligned result from a multi-step reasoner loop.

    Attributes:
        reply: Final assistant reply text.
        tool_chain: List of tool-call groups, one per LLM round that
                    produced tool_calls. Each group:
                      {"text": str, "calls": [{"call_id", "name",
                       "arguments", "status", "result"}, ...]}
        invocations: Flat list of all LLMToolCall made during the loop.
        metadata: Extra runtime metadata (tools_used, react_stats, …).
    """
    reply: str
    tool_chain: list[dict[str, Any]] = field(default_factory=list)
    invocations: list[LLMToolCall] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
