from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from amadeus.mcp.manage_tools import McpAddTool, McpListTool, McpRemoveTool
from amadeus.mcp.registry import McpServerRegistry
from amadeus.tools.registry import ToolRegistry

_FAKE_SERVER = str(Path(__file__).parent / "fake_stdio_server.py")


def _make_registry() -> tuple[ToolRegistry, McpServerRegistry]:
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)
    return registry, mcp_reg


def test_mcp_add_registers_tools_and_returns_names():
    registry, mcp_reg = _make_registry()
    tool = McpAddTool(mcp_registry=mcp_reg)

    async def run():
        try:
            result = await tool.execute(
                name="fake",
                transport_type="stdio",
                command=[sys.executable, _FAKE_SERVER],
            )
            return result
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    assert result.is_error is False
    assert set(result.output["registered"]) == {"mcp_fake__echo", "mcp_fake__add"}
    assert result.output["skipped"] == []
    # 工具确实进了 registry
    assert registry.get("mcp_fake__echo") is not None


def test_mcp_add_rejects_empty_name():
    _, mcp_reg = _make_registry()
    tool = McpAddTool(mcp_registry=mcp_reg)

    result = asyncio.run(tool.execute(name="", transport_type="stdio", command=[]))

    assert result.is_error is True
    assert "name" in result.output["error"]


def test_mcp_add_duplicate_returns_error():
    _, mcp_reg = _make_registry()
    tool = McpAddTool(mcp_registry=mcp_reg)

    async def run():
        try:
            await tool.execute(
                name="fake",
                transport_type="stdio",
                command=[sys.executable, _FAKE_SERVER],
            )
            return await tool.execute(
                name="fake",
                transport_type="stdio",
                command=[sys.executable, _FAKE_SERVER],
            )
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    assert result.is_error is True
    assert "已存在" in result.output["error"]


def test_mcp_remove_unregisters_tools():
    registry, mcp_reg = _make_registry()
    add_tool = McpAddTool(mcp_registry=mcp_reg)
    remove_tool = McpRemoveTool(mcp_registry=mcp_reg)

    async def run():
        try:
            await add_tool.execute(
                name="fake",
                transport_type="stdio",
                command=[sys.executable, _FAKE_SERVER],
            )
            assert "mcp_fake__echo" in registry.get_registered_names()
            return await remove_tool.execute(name="fake")
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    assert result.output["removed"] == "fake"
    assert "mcp_fake__echo" not in registry.get_registered_names()


def test_mcp_list_returns_connected_servers():
    registry, mcp_reg = _make_registry()
    add_tool = McpAddTool(mcp_registry=mcp_reg)
    list_tool = McpListTool(mcp_registry=mcp_reg)

    async def run():
        try:
            await add_tool.execute(
                name="fake",
                transport_type="stdio",
                command=[sys.executable, _FAKE_SERVER],
            )
            return await list_tool.execute()
        finally:
            await mcp_reg.shutdown()

    result = asyncio.run(run())

    servers = result.output["servers"]
    assert len(servers) == 1
    assert servers[0]["name"] == "fake"
    assert "mcp_fake__echo" in servers[0]["tools"]