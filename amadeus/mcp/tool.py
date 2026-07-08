from __future__ import annotations

from typing import Any

from amadeus.mcp.client import McpClient
from amadeus.mcp.transport import McpToolInfo
from amadeus.tools.base import ToolResult

_DEFAULT_CALL_TIMEOUT = 30.0


def _make_wrapper_name(server_name: str, tool_name: str) -> str:
    """命名规则 mcp_{server}__{tool}（双下划线，可逆解析）。"""
    return f"mcp_{server_name}__{tool_name}"


def parse_wrapper_name(wrapper_name: str) -> tuple[str, str] | None:
    """从 mcp_{server}__{tool} 反解 (server, tool)。无法解析返回 None。"""
    if not wrapper_name.startswith("mcp_"):
        return None
    rest = wrapper_name[len("mcp_"):]
    sep = rest.find("__")
    if sep < 0:
        return None
    server = rest[:sep]
    tool = rest[sep + 2:]
    if not server or not tool:
        return None
    return server, tool


class McpToolWrapper:
    """把单个远端 MCP 工具包成本地 Tool 协议实现。

    命名 mcp_{server}__{tool}；description 加 [MCP:{server}] 前缀；
    parameters 直接透传远端 input_schema（已校验）；execute 通过
    McpClient.call 发 tools/call。
    """

    def __init__(
        self,
        client: McpClient,
        info: McpToolInfo,
        server_name: str,
    ) -> None:
        self._client = client
        self._info = info
        self._server_name = server_name
        self.name = _make_wrapper_name(server_name, info.name)
        desc = info.description or ""
        self.description = f"[MCP:{server_name}] {desc}".strip()
        self.parameters = info.input_schema

    async def execute(self, **kwargs: Any) -> ToolResult:
        result_text = await self._client.call(
            self._info.name,
            kwargs,
            timeout=_DEFAULT_CALL_TIMEOUT,
        )
        is_error = result_text.startswith("MCP error")
        return ToolResult(
            tool_name=self.name,
            output=result_text,
            is_error=is_error,
            metadata={"mcp_server": self._server_name, "mcp_tool": self._info.name},
        )