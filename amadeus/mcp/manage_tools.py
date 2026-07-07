from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.registry import McpServerRegistry
from amadeus.tools.base import ToolResult


@dataclass
class McpAddTool:
    """让模型动态加 MCP server（MD2：模型可调 + 必做权限闸门）。

    模型调 mcp_add(name, transport_type, command|url, env) →
    McpServerRegistry.add 连接 + 注册工具。authorized 字段（MD5）默认 true。
    """

    mcp_registry: McpServerRegistry
    name: str = "mcp_add"
    description: str = (
        "动态添加一个 MCP server 并注册其工具。stdio 用 command（如 "
        '["npx","-y","mcp-server-xxx"]）；http 用 url。返回已注册工具名 '
        "与跳过工具的校验错误。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "MCP server 名（唯一）"},
                "transport_type": {
                    "type": "string",
                    "enum": ["stdio", "http"],
                },
                "command": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "stdio 启动命令",
                },
                "url": {"type": "string", "description": "http MCP endpoint"},
                "env": {"type": "object"},
                "cwd": {"type": "string"},
            },
            "required": ["name", "transport_type"],
        }
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        transport_type = kwargs.get("transport_type")
        if not name:
            return ToolResult(
                tool_name=self.name,
                output={"error": "name 不能为空"},
                is_error=True,
            )
        try:
            config = McpServerConfig(
                name=name,
                transport_type=transport_type,  # type: ignore[arg-type]
                command=kwargs.get("command"),
                url=kwargs.get("url"),
                env=kwargs.get("env"),
                cwd=kwargs.get("cwd"),
            )
            registered, skipped = await self.mcp_registry.add(config)
        except Exception as e:
            return ToolResult(
                tool_name=self.name,
                output={"error": f"添加失败: {e}"},
                is_error=True,
            )
        return ToolResult(
            tool_name=self.name,
            output={
                "registered": registered,
                "skipped": [
                    {"tool": t, "errors": errs} for t, errs in skipped
                ],
            },
            metadata={"mcp_server": name},
        )


@dataclass
class McpRemoveTool:
    mcp_registry: McpServerRegistry
    name: str = "mcp_remove"
    description: str = "断开并卸载一个 MCP server 及其所有工具。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        }
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return ToolResult(
                tool_name=self.name,
                output={"error": "name 不能为空"},
                is_error=True,
            )
        await self.mcp_registry.remove(name)
        return ToolResult(
            tool_name=self.name,
            output={"removed": name},
            metadata={"mcp_server": name},
        )


@dataclass
class McpListTool:
    mcp_registry: McpServerRegistry
    name: str = "mcp_list"
    description: str = "列出当前已连接的 MCP server。"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        servers = self.mcp_registry.list_servers()
        return ToolResult(
            tool_name=self.name,
            output={
                "servers": [
                    {
                        "name": s.name,
                        "transport_type": s.transport_type,
                        "tools": sorted(
                            self.mcp_registry.tool_registry.get_names_by_source(s.name)
                        ),
                    }
                    for s in servers
                ]
            },
        )