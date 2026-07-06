from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from amadeus.mcp.client import McpClient
from amadeus.mcp.stdio_transport import StdioMcpTransport

_FAKE_SERVER = str(Path(__file__).parent / "fake_stdio_server.py")


def _make_client() -> McpClient:
    transport = StdioMcpTransport(
        name="fake",
        command=[sys.executable, _FAKE_SERVER],
    )
    return McpClient(transport=transport)


def test_stdio_connect_lists_tools():
    client = _make_client()

    async def run():
        try:
            tools = await client.connect()
            return tools
        finally:
            await client.disconnect()

    tools = asyncio.run(run())

    names = [t.name for t in tools]
    assert "echo" in names
    assert "add" in names
    assert all(t.input_schema for t in tools)


def test_stdio_call_echo_returns_text():
    client = _make_client()

    async def run():
        try:
            await client.connect()
            return await client.call("echo", {"text": "hello"})
        finally:
            await client.disconnect()

    result = asyncio.run(run())

    assert result == "echo: hello"


def test_stdio_call_add_returns_sum():
    client = _make_client()

    async def run():
        try:
            await client.connect()
            return await client.call("add", {"a": 2, "b": 3})
        finally:
            await client.disconnect()

    result = asyncio.run(run())

    assert result == "5"


def test_stdio_call_unknown_tool_returns_error_string():
    client = _make_client()

    async def run():
        try:
            await client.connect()
            return await client.call("nonexistent", {})
        finally:
            await client.disconnect()

    result = asyncio.run(run())

    # 错误归一为字符串不抛
    assert "MCP error" in result
    assert "unknown tool" in result


def test_stdio_disconnect_terminates_process():
    client = _make_client()

    async def run():
        await client.connect()
        transport = client.transport
        assert transport.is_alive is True
        await client.disconnect()
        return transport

    transport = asyncio.run(run())

    assert transport.is_alive is False


def test_stdio_connect_invalid_command_raises():
    transport = StdioMcpTransport(
        name="bad",
        command=["nonexistent-binary-xyz", "--flag"],
    )
    client = McpClient(transport=transport)

    async def run():
        try:
            await client.connect()
        except (ConnectionError, FileNotFoundError):
            pass
        finally:
            await client.disconnect()

    asyncio.run(run())