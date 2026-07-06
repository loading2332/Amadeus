from __future__ import annotations

import logging
from typing import Any

from amadeus.mcp.transport import McpToolInfo, McpTransport

logger = logging.getLogger(__name__)

_CLIENT_INFO = {"name": "amadeus", "version": "0.1.0"}
_DEFAULT_CAPABILITIES: dict[str, Any] = {}


class McpClient:
    """MCP 协议层：封装 initialize / tools/list / tools/call 报文。

    与 transport 解耦：transport 负责字节通道，client 负责协议报文。
    """

    def __init__(self, transport: McpTransport) -> None:
        self._transport = transport
        self._tool_infos: list[McpToolInfo] = []

    @property
    def name(self) -> str:
        return self._transport.name

    @property
    def tool_infos(self) -> list[McpToolInfo]:
        return self._tool_infos

    @property
    def transport(self) -> McpTransport:
        return self._transport

    async def connect(self) -> list[McpToolInfo]:
        """建立连接 + initialize 握手 + tools/list。返回远端工具元信息列表。"""
        await self._transport.connect()
        # initialize 请求
        init_resp = await self._transport.send_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": "init",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": _DEFAULT_CAPABILITIES,
                    "clientInfo": _CLIENT_INFO,
                },
            }
        )
        if init_resp and "error" in init_resp:
            err = init_resp["error"]
            raise ConnectionError(
                f"MCP server {self.name!r} initialize 失败: "
                f"{err.get('message', err) if isinstance(err, dict) else err}"
            )
        # notifications/initialized（无 id，无响应）
        await self._transport.send_jsonrpc(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        # tools/list
        list_resp = await self._transport.send_jsonrpc(
            {"jsonrpc": "2.0", "id": "tools/list", "method": "tools/list", "params": {}}
        )
        if not list_resp or "error" in list_resp:
            err = list_resp.get("error") if list_resp else "no response"
            raise ConnectionError(
                f"MCP server {self.name!r} tools/list 失败: {err}"
            )
        raw_tools = list_resp.get("result", {}).get("tools", [])
        self._tool_infos = [
            McpToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get(
                    "inputSchema", {"type": "object", "properties": {}}
                ),
            )
            for t in raw_tools
            if isinstance(t, dict) and "name" in t
        ]
        logger.debug(
            "[mcp:%s] 已连接，工具：%s",
            self.name,
            [t.name for t in self._tool_infos],
        )
        return self._tool_infos

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> str:
        """调用远端工具，返回结果字符串。error 归一为字符串不抛。"""
        call_id = f"tools/call:{tool_name}"
        resp = await self._transport.send_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
            timeout=timeout,
        )
        if not resp:
            return f"MCP error ({self.name}/{tool_name}): 无响应"
        if "error" in resp:
            err = resp["error"]
            msg = err.get("message", err) if isinstance(err, dict) else str(err)
            return f"MCP error ({self.name}/{tool_name}): {msg}"
        content = resp.get("result", {}).get("content", [])
        if isinstance(content, list):
            return "\n".join(
                block.get("text", str(block)) if isinstance(block, dict) else str(block)
                for block in content
            )
        return str(resp.get("result", ""))

    async def disconnect(self) -> None:
        await self._transport.disconnect()