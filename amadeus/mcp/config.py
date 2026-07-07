from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TransportType = Literal["stdio", "http"]


@dataclass
class McpServerConfig:
    """单个 MCP server 的连接配置（与 mcp_servers 表行对应）。

    放在独立模块以便 db.mcp_servers 不触发 amadeus.mcp 包全加载（避免
    与 amadeus.session/memory 的预存在循环 import）。
    """

    name: str
    transport_type: TransportType
    command: list[str] | None = None  # stdio
    url: str | None = None  # http
    env: dict[str, str] | None = None
    cwd: str | None = None
    headers: dict[str, str] | None = None  # http