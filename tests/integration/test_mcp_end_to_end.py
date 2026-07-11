from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from amadeus.mcp import (
    McpAddTool,
    McpListTool,
    McpRemoveTool,
    McpServerRegistry,
)
from amadeus.provider import LLMProvider, LLMProviderConfig
from amadeus.runtime.reasoner import Reasoner
from amadeus.session.identity import SessionRef
from amadeus.tools.discovery import ToolSearchTool
from amadeus.tools.executor import ToolExecutor
from amadeus.tools.registry import ToolRegistry

_FAKE_SERVER = str(Path(__file__).parent.parent / "mcp" / "fake_stdio_server.py")
_SESSION = SessionRef(user_id=1, session_id=1)


class _ControlledCompletions:
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
            choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
            usage={},
        )


@dataclass
class _FakeChatNamespace:
    completions: _ControlledCompletions


class _FakeClient:
    def __init__(self, completions: _ControlledCompletions | None = None) -> None:
        self.completions = completions or _ControlledCompletions()
        self.chat = _FakeChatNamespace(completions=self.completions)


def _tool_call_response(
    *, tool_name: str, args: dict[str, Any] | None = None, call_id: str = "c1"
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


def _build_reasoner_with_mcp() -> tuple[Reasoner, ToolRegistry, McpServerRegistry, _FakeClient]:
    registry = ToolRegistry()
    registry.register(
        ToolSearchTool(registry=registry),
        risk="read-only",
        always_on=True,
    )
    mcp_reg = McpServerRegistry(tool_registry=registry)
    # mcp_add/remove/list 也 always_on（和 bootstrap 装配一致）
    registry.register(
        McpAddTool(mcp_registry=mcp_reg),
        risk="write",
        always_on=True,
    )
    registry.register(
        McpRemoveTool(mcp_registry=mcp_reg),
        risk="write",
        always_on=True,
    )
    registry.register(
        McpListTool(mcp_registry=mcp_reg),
        risk="read-only",
        always_on=True,
    )

    async def invoker(name: str, arguments: dict[str, Any]) -> Any:
        return await registry.execute(name, arguments)

    executor = ToolExecutor(hooks=[], invoker=invoker)
    client = _FakeClient()
    provider = LLMProvider(
        LLMProviderConfig(api_key="secret", model="fake-model"),
        client=client,
    )
    reasoner = Reasoner(
        provider=provider,
        tool_executor=executor,
        tool_registry=registry,
    )
    return reasoner, registry, mcp_reg, client


def test_mcp_add_search_call_list_and_remove():
    """完整 MCP 链路：add → search/select → call → list → remove。"""
    reasoner, registry, mcp_reg, client = _build_reasoner_with_mcp()

    async def run():
        try:
            # 1) 模型调 mcp_add 加 fake server
            # 2) 模型调 tool_search(select:mcp_fake__echo) 解锁
            # 3) 模型调 mcp_fake__echo 调用远端工具
            # 4) list 观察状态，再 remove 回收连接与 wrappers
            client.completions.responses = [
                _tool_call_response(
                    tool_name="mcp_add",
                    args={
                        "name": "fake",
                        "command": [sys.executable, _FAKE_SERVER],
                    },
                    call_id="c1",
                ),
                _tool_call_response(
                    tool_name="tool_search",
                    args={"query": "select:mcp_fake__echo"},
                    call_id="c2",
                ),
                _tool_call_response(
                    tool_name="mcp_fake__echo",
                    args={"text": "hello from mcp"},
                    call_id="c3",
                ),
                _tool_call_response(tool_name="mcp_list", call_id="c4"),
                _tool_call_response(
                    tool_name="mcp_remove",
                    args={"name": "fake"},
                    call_id="c5",
                ),
            ]
            return await reasoner.reason(
                messages=[{"role": "user", "content": "go"}], session=_SESSION
            )
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    assert result.reply == "done"
    assert len(result.tool_chain) == 5
    # 1) mcp_add 成功，注册了 mcp_fake__echo / mcp_fake__add
    add_call = result.tool_chain[0]["calls"][0]
    assert add_call["name"] == "mcp_add"
    assert add_call["status"] == "success"
    assert "mcp_fake__echo" in add_call["result"]
    # 2) tool_search select 解锁成功
    search_call = result.tool_chain[1]["calls"][0]
    assert search_call["name"] == "tool_search"
    assert search_call["status"] == "success"
    # 3) mcp_fake__echo 已解锁，调用成功，拿到远端 "echo: hello from mcp"
    echo_call = result.tool_chain[2]["calls"][0]
    assert echo_call["name"] == "mcp_fake__echo"
    assert echo_call["status"] == "success"
    assert "echo: hello from mcp" in str(echo_call["result"])
    list_call = result.tool_chain[3]["calls"][0]
    assert list_call["name"] == "mcp_list"
    assert list_call["status"] == "success"
    assert "connected" in str(list_call["result"])
    remove_call = result.tool_chain[4]["calls"][0]
    assert remove_call["name"] == "mcp_remove"
    assert remove_call["status"] == "success"
    assert registry.get("mcp_fake__echo") is None


def test_mcp_tool_not_visible_until_unlocked():
    """MCP 工具加进来后默认不可见，直接调会被引导回填。"""
    reasoner, registry, mcp_reg, client = _build_reasoner_with_mcp()

    async def run():
        try:
            # 先 mcp_add 加 server
            # 然后直接调 mcp_fake__echo（未解锁 → 引导回填）
            client.completions.responses = [
                _tool_call_response(
                    tool_name="mcp_add",
                    args={
                        "name": "fake",
                        "command": [sys.executable, _FAKE_SERVER],
                    },
                    call_id="c1",
                ),
                _tool_call_response(
                    tool_name="mcp_fake__echo",
                    args={"text": "x"},
                    call_id="c2",
                ),
            ]
            return await reasoner.reason(
                messages=[{"role": "user", "content": "go"}], session=_SESSION
            )
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    # 第二轮 mcp_fake__echo 被引导回填（deferred）
    assert result.tool_chain[1]["calls"][0]["name"] == "mcp_fake__echo"
    assert result.tool_chain[1]["calls"][0]["status"] == "deferred"
    # 但 mcp_add 第一轮成功了
    assert result.tool_chain[0]["calls"][0]["status"] == "success"
