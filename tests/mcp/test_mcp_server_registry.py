from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
from amadeus.mcp.registry import McpServerConfig, McpServerRegistry
from amadeus.tools.registry import ToolRegistry

_FAKE_SERVER = str(Path(__file__).parent / "fake_stdio_server.py")


def _stdio_config(name: str = "fake") -> McpServerConfig:
    return McpServerConfig(
        name=name,
        transport_type="stdio",
        command=[sys.executable, _FAKE_SERVER],
    )


def test_add_registers_tools_with_mcp_source():
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)

    async def run():
        try:
            registered, skipped = await mcp_reg.add(_stdio_config())
            return registered, skipped
        finally:
            await mcp_reg.shutdown()

    registered, skipped = asyncio.run(run())

    # 假 server 提供 echo + add 两个工具
    assert set(registered) == {"mcp_fake__echo", "mcp_fake__add"}
    assert skipped == []
    # 元数据标 mcp source
    meta = registry.get_metadata("mcp_fake__echo")
    assert meta is not None
    assert meta.source_type == "mcp"
    assert meta.source_name == "fake"
    assert meta.risk == "external-side-effect"


def test_remove_unregisters_tools_and_disconnects():
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)

    async def run():
        await mcp_reg.add(_stdio_config())
        assert "mcp_fake__echo" in registry.get_registered_names()
        await mcp_reg.remove("fake")
        return registry.get_registered_names()

    names = asyncio.run(run())

    assert "mcp_fake__echo" not in names
    assert "mcp_fake__add" not in names


def test_add_idempotent_rejects_duplicate_name():
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)

    async def run():
        try:
            await mcp_reg.add(_stdio_config())
            try:
                await mcp_reg.add(_stdio_config())
            except ValueError as e:
                return str(e)
            return "no error"
        finally:
            await mcp_reg.shutdown()

    msg = asyncio.run(run())

    assert "已存在" in msg


def test_add_skips_tools_with_invalid_schema():
    """schema 含 $ref 的工具应被跳过并出现在 skipped 列表。"""
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        method = body.get("method")
        if method == "initialize":
            return httpx.Response(
                200,
                content=json.dumps(
                    {"jsonrpc": "2.0", "id": "init", "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "s", "version": "0"}, "capabilities": {}}}
                ),
                headers={"content-type": "application/json", "Mcp-Session-Id": "s1"},
            )
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "tools/list":
            return httpx.Response(
                200,
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": "tools/list",
                        "result": {
                            "tools": [
                                {"name": "good", "description": "ok", "inputSchema": {"type": "object", "properties": {}}},
                                {"name": "bad", "description": "has ref", "inputSchema": {"type": "object", "$ref": "#/$defs/X"}},
                            ]
                        },
                    }
                ),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(500)

    import amadeus.mcp.http_transport as http_mod

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    async def run():
        try:
            # 直接 patch httpx.AsyncClient 用于 transport.connect
            http_mod.httpx.AsyncClient = fake_client  # type: ignore[attr-defined]
            cfg = McpServerConfig(name="srv", transport_type="http", url="http://x/mcp")
            return await mcp_reg.add(cfg)
        finally:
            http_mod.httpx.AsyncClient = real_client  # type: ignore[attr-defined]
            await mcp_reg.shutdown()

    registered, skipped = asyncio.run(run())

    assert registered == ["mcp_srv__good"]
    assert len(skipped) == 1
    assert skipped[0][0] == "bad"
    assert any("$ref" in e for e in skipped[0][1])


def test_load_and_connect_all_parallel_does_not_block_on_failures():
    registry = ToolRegistry()
    mcp_reg = McpServerRegistry(tool_registry=registry)

    async def run():
        configs = [
            _stdio_config(name="ok1"),
            McpServerConfig(name="bad", transport_type="stdio", command=["nonexistent-bin-xyz"]),
            _stdio_config(name="ok2"),
        ]
        await mcp_reg.load_and_connect_all(configs)
        return mcp_reg.list_servers()

    servers = asyncio.run(run())

    # bad server 失败不阻断；ok1/ok2 连上
    names = {s.name for s in servers}
    assert "ok1" in names
    assert "ok2" in names
    # bad 因 connect 失败未进 _configs
    assert "bad" not in names