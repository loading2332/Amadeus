from __future__ import annotations

from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

HookEvent = Literal["pre_tool_use", "post_tool_use", "post_tool_error"]
ToolSource = Literal["passive", "proactive", "subagent"]
HookDecision = Literal["pass", "deny"]
ToolExecStatus = Literal["success", "denied", "error"]


@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""
    source: ToolSource = "passive"
    session_key: str = ""
    # tool_batch 保留 dict 类型（与 tool_runtime.tool_call_batch_snapshot 现状一致）
    tool_batch: dict[str, Any] = field(default_factory=dict)
    tool_batch_index: int = 0


@dataclass(frozen=True)
class ToolResult:
    tool_name: str
    output: Any
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookOutcome:
    """Pre hook 的返回值：decision / updated_input / reason 三字段正交。

    - decision: "pass" 放行 / "deny" 拒绝
    - updated_input: 不为 None 时整体替换参数（与 decision 正交，可同时表达"改参 + deny"）
    - reason: deny 时给模型看的理由；pass 时可空
    """

    decision: HookDecision = "pass"
    updated_input: dict[str, Any] | None = None
    reason: str = ""


@dataclass(frozen=True)
class HookContext:
    event: HookEvent
    request: ToolExecutionRequest
    current_arguments: dict[str, Any]
    result: Any = ""
    error: str = ""


@dataclass(frozen=True)
class HookTraceItem:
    hook_name: str
    event: HookEvent
    matched: bool
    decision: HookDecision = "pass"
    reason: str = ""


@dataclass(frozen=True)
class ToolExecutionResult:
    status: ToolExecStatus
    output: Any
    final_arguments: dict[str, Any]
    pre_hook_trace: list[HookTraceItem] = field(default_factory=list)
    post_hook_trace: list[HookTraceItem] = field(default_factory=list)


@dataclass(frozen=True)
class ToolTrace:
    """旧调用点的兼容 trace 结构（与新 ToolExecutionResult 并存）。"""

    tool_name: str
    arguments: dict[str, Any]
    status: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]

    def execute(self, **kwargs: Any) -> ToolResult | Awaitable[ToolResult]:
        ...


class ToolHook(Protocol):
    """新 hook 协议：matches + run，按 event 分发，返回 HookOutcome。"""

    name: str
    event: HookEvent

    def matches(self, ctx: HookContext) -> bool:
        ...

    def run(self, ctx: HookContext) -> Awaitable[HookOutcome] | HookOutcome:
        ...