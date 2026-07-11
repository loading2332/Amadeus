from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpServerConfig:
    """当前进程内的本地 stdio MCP server 配置。"""

    name: str
    command: list[str] = field(repr=False)
    env: dict[str, str] | None = field(default=None, repr=False)
    cwd: str | None = field(default=None, repr=False)


__all__ = ["McpServerConfig"]
