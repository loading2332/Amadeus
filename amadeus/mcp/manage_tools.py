from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.mcp.client import McpJsonRpcError, McpProtocolError
from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.registry import McpServerNotFoundError, McpServerRegistry
from amadeus.tools.base import ToolResult


def _public_error_code(error: Exception) -> str:
    if isinstance(error, McpServerNotFoundError):
        return "not_found"
    if isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(error, McpJsonRpcError):
        return "server_rejected"
    if isinstance(error, McpProtocolError):
        return "protocol_error"
    if isinstance(error, ConnectionError):
        return "connection_failed"
    if isinstance(error, ValueError):
        return "invalid_request"
    return "internal_error"


@dataclass
class McpAddTool:
    """在 local_trusted 模式启动一个本地 stdio MCP server。"""

    mcp_registry: McpServerRegistry
    name: str = "mcp_add"
    description: str = "启动一个本地 stdio MCP server，并注册它提供的工具。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "当前进程内唯一的 MCP server 别名",
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "本地 stdio MCP server 启动命令及参数",
                },
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "只传给该子进程的环境变量",
                },
                "cwd": {
                    "type": "string",
                    "description": "可选工作目录",
                },
            },
            "required": ["name", "command"],
            "additionalProperties": False,
        }
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw_name = kwargs.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        command = kwargs.get("command")
        if not name:
            return self._error("name 不能为空")
        if not isinstance(command, list) or not command or any(
            not isinstance(part, str) or not part for part in command
        ):
            return self._error("command 必须是非空字符串数组")

        try:
            registered, skipped = await self.mcp_registry.add(
                McpServerConfig(
                    name=name,
                    command=list(command),
                    env=kwargs.get("env"),
                    cwd=kwargs.get("cwd"),
                )
            )
        except Exception as error:
            return self._error(
                "添加 MCP server 失败",
                code=_public_error_code(error),
            )
        return ToolResult(
            tool_name=self.name,
            output={
                "server": name,
                "status": "connected",
                "registered": registered,
                "skipped": [
                    {"tool": tool_name, "errors": errors}
                    for tool_name, errors in skipped
                ],
            },
            metadata={"mcp_server": name},
        )

    def _error(self, message: str, *, code: str = "invalid_request") -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            output={"error": message, "code": code},
            is_error=True,
        )


@dataclass
class McpRemoveTool:
    mcp_registry: McpServerRegistry
    name: str = "mcp_remove"
    description: str = "断开并卸载一个本地 MCP server 及其工具。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        }
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        raw_name = kwargs.get("name")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not name:
            return ToolResult(
                tool_name=self.name,
                output={"error": "name 不能为空"},
                is_error=True,
            )
        try:
            removed_tools = await self.mcp_registry.remove(name)
        except Exception as error:
            return ToolResult(
                tool_name=self.name,
                output={
                    "error": "移除 MCP server 失败",
                    "code": _public_error_code(error),
                },
                is_error=True,
            )
        return ToolResult(
            tool_name=self.name,
            output={
                "server": name,
                "status": "removed",
                "removed_tools": removed_tools,
            },
            metadata={"mcp_server": name},
        )


@dataclass
class McpListTool:
    mcp_registry: McpServerRegistry
    name: str = "mcp_list"
    description: str = "列出当前进程中的 MCP server、连接状态和工具名。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            output={
                "servers": [
                    {
                        "name": server.name,
                        "status": server.status,
                        "tools": list(server.tools),
                    }
                    for server in self.mcp_registry.list_servers()
                ]
            },
        )


__all__ = ["McpAddTool", "McpListTool", "McpRemoveTool"]
