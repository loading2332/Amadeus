from __future__ import annotations

import asyncio
import json

import httpx
from amadeus.mcp.client import McpClient
from amadeus.mcp.http_transport import StreamableHttpMcpTransport


def _mock_handler_factory(responses: list[httpx.Response]):
    """按顺序返回预设响应的 MockTransport handler。"""

    def handler(request: httpx.Request) -> httpx.Response:
        if not responses:
            return httpx.Response(500, text="no more mock responses")
        return responses.pop(0)

    return handler


def _json_resp(
    body: dict,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(body),
        headers={"content-type": "application/json", **(headers or {})},
    )


def _sse_resp(messages: list[dict], *, status: int = 200) -> httpx.Response:
    """构造 SSE 流响应：每个 message 一个 data: 事件，事件间空行。"""
    lines: list[str] = []
    for msg in messages:
        lines.append("data: " + json.dumps(msg))
        lines.append("")  # 事件分隔空行
    content = "\n".join(lines) + "\n"
    return httpx.Response(
        status,
        content=content.encode(),
        headers={"content-type": "text/event-stream"},
    )


def test_http_initialize_extracts_session_id():
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["protocol_version"] = request.headers.get("MCP-Protocol-Version")
        captured["accept"] = request.headers.get("Accept")
        captured["body"] = json.loads(request.content)
        # initialize 响应带 Mcp-Session-Id
        return _json_resp(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "result": {
                    "protocolVersion": "2025-06-18",
                    "serverInfo": {"name": "s", "version": "0"},
                    "capabilities": {},
                },
            },
            headers={"Mcp-Session-Id": "sess-123"},
        )

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        resp = await transport.send_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {},
            }
        )
        return resp

    resp = asyncio.run(run())

    assert captured["protocol_version"] == "2025-06-18"
    assert "application/json" in captured["accept"]
    assert "text/event-stream" in captured["accept"]
    assert transport._session_id == "sess-123"
    assert resp["id"] == "init"


def test_http_subsequent_requests_carry_session_id():
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")
    transport._session_id = "sess-xyz"
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["session_id"] = request.headers.get("Mcp-Session-Id")
        return _json_resp({"jsonrpc": "2.0", "id": "tools/list", "result": {"tools": []}})

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        return await transport.send_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools/list", "method": "tools/list", "params": {}}
        )

    asyncio.run(run())

    assert captured["session_id"] == "sess-xyz"


def test_http_parses_single_json_response():
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_resp(
            {"jsonrpc": "2.0", "id": "tools/call:echo", "result": {"content": [{"type": "text", "text": "hi"}]}}
        )

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        return await transport.send_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools/call:echo", "method": "tools/call", "params": {}}
        )

    resp = asyncio.run(run())

    assert resp["result"]["content"][0]["text"] == "hi"


def test_http_parses_sse_stream_response():
    """SSE 流响应：从 data 行提取匹配 id 的 JSON-RPC message。"""
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:
        # server 先发一条 notification，再发匹配 response
        return _sse_resp(
            [
                {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"p": 50}},
                {"jsonrpc": "2.0", "id": "tools/call:echo", "result": {"content": [{"type": "text", "text": "streamed"}]}},
            ]
        )

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        return await transport.send_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools/call:echo", "method": "tools/call", "params": {}}
        )

    resp = asyncio.run(run())

    assert resp["id"] == "tools/call:echo"
    assert resp["result"]["content"][0]["text"] == "streamed"


def test_http_error_status_normalized_to_jsonrpc_error():
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_resp(
            {"jsonrpc": "2.0", "id": "x", "error": {"code": -32601, "message": "boom"}},
            status=400,
        )

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        return await transport.send_jsonrpc(
            {"jsonrpc": "2.0", "id": "x", "method": "tools/call", "params": {}}
        )

    resp = asyncio.run(run())

    # 归一为 JSON-RPC error dict，不抛
    assert "error" in resp
    assert "MCP error (HTTP 400)" in resp["error"]["message"]


def test_http_notification_returns_none():
    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202)

    transport._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )

    async def run():
        return await transport.send_jsonrpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

    resp = asyncio.run(run())

    assert resp is None


def test_http_client_connect_full_handshake(monkeypatch):
    """端到端：McpClient.connect 走完整 initialize + notifications/initialized + tools/list。"""
    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200)
        body = json.loads(request.content)
        call_log.append(body.get("method", ""))
        if body.get("method") == "initialize":
            return _json_resp(
                {"jsonrpc": "2.0", "id": "init", "result": {"protocolVersion": "2025-06-18", "serverInfo": {"name": "s", "version": "0"}, "capabilities": {}}},
                headers={"Mcp-Session-Id": "sess-1"},
            )
        if body.get("method") == "notifications/initialized":
            return httpx.Response(202)
        if body.get("method") == "tools/list":
            return _json_resp(
                {"jsonrpc": "2.0", "id": "tools/list", "result": {"tools": [{"name": "echo", "description": "Echo", "inputSchema": {"type": "object", "properties": {}}}]}}
            )
        if request.method == "DELETE":
            return httpx.Response(200)
        return httpx.Response(500)

    # 让 transport.connect() 建的 AsyncClient 用 MockTransport
    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_async_client(*args, **kwargs)

    monkeypatch.setattr("amadeus.mcp.http_transport.httpx.AsyncClient", fake_async_client)

    transport = StreamableHttpMcpTransport(name="srv", url="http://srv.test/mcp")
    client = McpClient(transport=transport)
    captured_session: dict = {}

    async def run():
        try:
            tools = await client.connect()
            captured_session["sid"] = transport._session_id
            return tools
        finally:
            await client.disconnect()

    tools = asyncio.run(run())

    assert call_log == ["initialize", "notifications/initialized", "tools/list"]
    assert tools[0].name == "echo"
    assert captured_session["sid"] == "sess-1"