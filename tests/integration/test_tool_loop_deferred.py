from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.runtime.reasoner import Reasoner
from amadeus.tools.base import ToolResult
from amadeus.tools.discovery import ToolSearchTool
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry


class _ControlledCompletions:
    """按顺序返回预设响应，耗尽后默认给 final reply。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses: list[SimpleNamespace] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        if self.responses:
            return self.responses.pop(0)
        return SimpleNamespace(
            id="resp_final",
            model=kwargs["model"],
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="final reply")
                )
            ],
            usage={},
        )


@dataclass
class _FakeChatNamespace:
    completions: _ControlledCompletions


class _FakeClient:
    def __init__(self, completions: _ControlledCompletions | None = None) -> None:
        self.completions: _ControlledCompletions = completions or _ControlledCompletions()
        self.chat = _FakeChatNamespace(completions=self.completions)


def _tool_call_response(
    *,
    tool_name: str,
    args: dict[str, Any] | None = None,
    call_id: str = "call_1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_tool",
        model="fake-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id=call_id,
                            function=SimpleNamespace(
                                name=tool_name,
                                arguments=json.dumps(args or {}),
                            ),
                        )
                    ],
                )
            )
        ],
        usage={},
    )


@dataclass
class HiddenTool:
    """deferred 工具：不 always_on，要 tool_search 解锁才能调。"""

    name: str = "hidden_tool"
    description: str = "A hidden tool that must be unlocked via tool_search."
    parameters: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.parameters = {
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }

    def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            tool_name=self.name, output={"hidden_result": kwargs.get("x", "")}
        )


def _make_reasoner_with_registry(client: _FakeClient) -> tuple[Reasoner, ToolRegistry]:
    registry = ToolRegistry()
    registry.register(
        ToolSearchTool(registry=registry),
        risk="read-only",
        always_on=True,
    )
    registry.register(HiddenTool(), risk="read-only", always_on=False)

    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        arguments.pop("purpose", None)
        return await registry.execute(name, arguments)

    executor = ToolExecutor(hooks=[], invoker=invoker)
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    reasoner = Reasoner(
        provider=provider,
        tool_executor=executor,
        tool_registry=registry,
    )
    return reasoner, registry


def test_deferred_tool_call_blocked_until_unlocked():
    """模型调未解锁工具 → 引导回填 → 调 tool_search 解锁 → 下一轮可调用。"""
    client = _FakeClient()
    # 1) 先调 hidden_tool（未解锁 → 引导回填）
    # 2) 调 tool_search(select:hidden_tool) → 解锁
    # 3) 再调 hidden_tool（已解锁 → 执行）
    # 4) final reply
    client.completions.responses = [
        _tool_call_response(tool_name="hidden_tool", args={"x": "first"}, call_id="c1"),
        _tool_call_response(
            tool_name="tool_search",
            args={"query": "select:hidden_tool"},
            call_id="c2",
        ),
        _tool_call_response(tool_name="hidden_tool", args={"x": "second"}, call_id="c3"),
    ]
    reasoner, registry = _make_reasoner_with_registry(client)

    result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "go"}]))

    assert result.reply == "final reply"
    # 3 个 tool_call 步骤 + 1 个 final = 4 次 provider.chat
    assert len(client.completions.calls) == 4
    # 第一轮 hidden_tool 被引导回填（status=deferred）
    assert result.tool_chain[0]["calls"][0]["status"] == "deferred"
    # 第二轮 tool_search 成功
    assert result.tool_chain[1]["calls"][0]["name"] == "tool_search"
    assert result.tool_chain[1]["calls"][0]["status"] == "success"
    # 第三轮 hidden_tool 解锁后成功执行
    assert result.tool_chain[2]["calls"][0]["name"] == "hidden_tool"
    assert result.tool_chain[2]["calls"][0]["status"] == "success"


def test_unlocked_tool_appears_in_next_round_schemas():
    """tool_search 解锁后，下一轮 provider.chat 的 tools 含该工具 schema。"""
    client = _FakeClient()
    client.completions.responses = [
        _tool_call_response(
            tool_name="tool_search",
            args={"query": "select:hidden_tool"},
            call_id="c1",
        ),
        _tool_call_response(tool_name="hidden_tool", args={"x": "y"}, call_id="c2"),
    ]
    reasoner, _ = _make_reasoner_with_registry(client)

    asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "go"}]))

    # 第 1 轮 tools 只有 always_on（tool_search）
    first_round_tools = client.completions.calls[0]["tools"]
    first_names = {t["function"]["name"] for t in first_round_tools}
    assert "tool_search" in first_names
    assert "hidden_tool" not in first_names
    # 第 2 轮 tools 含 hidden_tool（已解锁）
    second_round_tools = client.completions.calls[1]["tools"]
    second_names = {t["function"]["name"] for t in second_round_tools}
    assert "hidden_tool" in second_names


def test_tool_search_returns_matched_candidates():
    """普通 query（非 select:）返回关键词匹配的候选列表。"""
    client = _FakeClient()
    client.completions.responses = [
        _tool_call_response(
            tool_name="tool_search", args={"query": "hidden"}, call_id="c1"
        ),
    ]
    reasoner, _ = _make_reasoner_with_registry(client)

    result = asyncio.run(reasoner.reason(messages=[{"role": "user", "content": "go"}]))

    # tool_search 执行成功，返回候选
    search_call = result.tool_chain[0]["calls"][0]
    assert search_call["name"] == "tool_search"
    assert search_call["status"] == "success"
    # 普通 search 不自动解锁（只 select: 才解锁），hidden_tool 仍未解锁
    # 第二轮 tools 仍不含 hidden_tool（但这里只有 2 轮：search + final）
    second_round_tools = client.completions.calls[1]["tools"]
    second_names = {t["function"]["name"] for t in second_round_tools}
    assert "hidden_tool" not in second_names