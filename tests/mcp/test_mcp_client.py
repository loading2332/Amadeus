from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest
from amadeus.mcp.client import McpCallResult, McpClient, McpProtocolError

_FAKE_SERVER = str(Path(__file__).parent / "fake_stdio_server.py")


def _make_client() -> McpClient:
    return McpClient(
        name="fake",
        command=[sys.executable, _FAKE_SERVER],
    )


def _structured(result: McpCallResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


def test_connect_handshake_handles_server_ping_and_paginated_tool_list() -> None:
    async def scenario() -> tuple[list[str], dict[str, Any]]:
        client = _make_client()
        try:
            tools = await client.connect()
            state = await client.call("__test_state", {})
            assert client.is_alive is True
            assert [tool.name for tool in client.tool_infos] == ["echo", "add"]
            return [tool.name for tool in tools], _structured(state)
        finally:
            await client.disconnect()

    names, state = asyncio.run(scenario())

    assert names == ["echo", "add"]
    assert state["initialized"] is True
    assert state["pingAcknowledged"] is True
    assert state["listCursors"] == [None, "page-2"]


@pytest.mark.parametrize(
    "env",
    [
        {"FAKE_MCP_PROTOCOL_VERSION": "2024-11-05"},
        {"FAKE_MCP_NO_TOOLS": "1"},
    ],
)
def test_connect_rejects_incompatible_handshake(env: dict[str, str]) -> None:
    async def scenario() -> None:
        client = McpClient(
            name="incompatible",
            command=[sys.executable, _FAKE_SERVER],
            env=env,
        )
        try:
            with pytest.raises(McpProtocolError):
                await client.connect()
            assert client.is_alive is False
        finally:
            await client.disconnect()

    asyncio.run(scenario())


def test_child_environment_uses_allowlist_plus_explicit_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MCP_TEST_UNSAFE", "must-not-be-inherited")

    async def scenario() -> dict[str, Any]:
        client = McpClient(
            name="env",
            command=[sys.executable, _FAKE_SERVER],
            env={"MCP_TEST_EXPLICIT": "explicit-value"},
        )
        try:
            await client.connect()
            return _structured(await client.call("__test_state", {}))
        finally:
            await client.disconnect()

    state = asyncio.run(scenario())

    assert state["explicitEnv"] == "explicit-value"
    assert state["unsafeParentInherited"] is False


def test_call_preserves_structured_content_and_remote_error_flag() -> None:
    async def scenario() -> McpCallResult:
        client = _make_client()
        try:
            await client.connect()
            return await client.call("__test_structured_error", {})
        finally:
            await client.disconnect()

    result = asyncio.run(scenario())

    assert result.content == [
        {"type": "text", "text": "remote validation failed"}
    ]
    assert result.structured_content == {
        "kind": "validation",
        "field": "value",
    }
    assert result.is_error is True


def test_call_rejects_result_without_required_content() -> None:
    async def scenario() -> None:
        client = _make_client()
        try:
            await client.connect()
            with pytest.raises(McpProtocolError, match="content"):
                await client.call("__test_missing_content", {})
        finally:
            await client.disconnect()

    asyncio.run(scenario())


def test_calls_to_same_client_are_serialized() -> None:
    async def scenario() -> tuple[list[str], dict[str, Any]]:
        client = _make_client()
        try:
            await client.connect()
            results = await asyncio.gather(
                client.call(
                    "__test_serial_probe",
                    {"label": "first", "delay": 0.08},
                ),
                client.call(
                    "__test_serial_probe",
                    {"label": "second", "delay": 0.08},
                ),
            )
            state = await client.call("__test_state", {})
            labels = [result.content[0]["text"] for result in results]
            return labels, _structured(state)
        finally:
            await client.disconnect()

    labels, state = asyncio.run(scenario())

    assert labels == ["first", "second"]
    assert state["maxActiveCalls"] == 1


def test_timeout_sends_cancellation_and_next_call_skips_late_response() -> None:
    async def scenario() -> tuple[McpCallResult, dict[str, Any]]:
        client = _make_client()
        try:
            await client.connect()
            with pytest.raises(TimeoutError, match="超时"):
                await client.call(
                    "__test_slow_late",
                    {"delay": 0.12},
                    timeout=0.02,
                )

            # 让超时请求的响应先进入 stdout。下一次调用必须跳过这个旧 id，
            # 才能读到自己的 echo 响应。
            await asyncio.sleep(0.2)
            echo = await client.call("echo", {"text": "after timeout"})
            state = await client.call("__test_state", {})
            return echo, _structured(state)
        finally:
            await client.disconnect()

    echo, state = asyncio.run(scenario())

    assert echo.content == [
        {"type": "text", "text": "echo: after timeout"}
    ]
    assert echo.is_error is False
    assert len(state["cancelledRequestIds"]) == 1


def test_timeout_covers_stdin_backpressure_and_disconnect_remains_bounded() -> None:
    async def scenario() -> tuple[float, list[dict[str, Any]]]:
        loop = asyncio.get_running_loop()
        loop_errors: list[dict[str, Any]] = []
        loop.set_exception_handler(lambda _loop, context: loop_errors.append(context))
        client = _make_client()
        try:
            await client.connect()
            await client.call("__test_pause_reads", {})
            started = asyncio.get_running_loop().time()
            with pytest.raises(TimeoutError, match="超时"):
                await client.call(
                    "echo",
                    {"text": "x" * (8 * 1024 * 1024)},
                    timeout=0.05,
                )
            elapsed = asyncio.get_running_loop().time() - started
        finally:
            await asyncio.wait_for(client.disconnect(), timeout=5.0)
        await asyncio.sleep(0.05)
        return elapsed, loop_errors

    elapsed, loop_errors = asyncio.run(scenario())

    assert elapsed < 1.5
    assert loop_errors == []


def test_unexpected_server_disconnect_fails_the_inflight_call() -> None:
    async def scenario() -> None:
        client = _make_client()
        try:
            await client.connect()
            with pytest.raises(ConnectionError, match="stdout"):
                await client.call("__test_crash", {})
        finally:
            await client.disconnect()

    asyncio.run(scenario())


def test_protocol_channel_failure_marks_live_process_disconnected() -> None:
    async def scenario() -> bool:
        client = _make_client()
        try:
            await client.connect()
            with pytest.raises(ConnectionError, match="stdout"):
                await client.call("__test_close_stdout", {})
            return client.is_alive
        finally:
            await client.disconnect()

    assert asyncio.run(scenario()) is False


def test_large_stderr_without_newline_is_continuously_drained() -> None:
    async def scenario() -> McpCallResult:
        client = _make_client()
        try:
            await client.connect()
            return await client.call("__test_large_stderr", {}, timeout=3.0)
        finally:
            await client.disconnect()

    result = asyncio.run(scenario())

    assert result.content == [{"type": "text", "text": "stderr drained"}]


def test_disconnect_reaps_the_child_process() -> None:
    async def scenario() -> bool:
        client = _make_client()
        try:
            await client.connect()
            assert client.is_alive is True
        finally:
            await client.disconnect()
        return client.is_alive

    assert asyncio.run(scenario()) is False


def test_connect_reports_missing_command_and_remains_disconnectable() -> None:
    async def scenario() -> None:
        client = McpClient(
            name="missing",
            command=["amadeus-command-that-does-not-exist-7f5d3e"],
        )
        try:
            with pytest.raises(ConnectionError, match="命令不存在"):
                await client.connect()
        finally:
            await client.disconnect()

    asyncio.run(scenario())
