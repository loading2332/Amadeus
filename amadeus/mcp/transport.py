from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class McpToolInfo:
    """远端 MCP 工具的元信息（tools/list 返回的单条工具）。"""

    name: str
    description: str
    input_schema: dict[str, Any]


class McpTransport(Protocol):
    """MCP 传输层抽象：stdio / Streamable HTTP 各一个实现。

    协议层（McpClient）通过 send_jsonrpc 收发完整 JSON-RPC 报文，
    transport 负责字节通道（stdio 行式 / HTTP POST+SSE）。
    """

    @property
    def name(self) -> str:
        ...

    @property
    def is_alive(self) -> bool:
        ...

    async def connect(self) -> None:
        """建立连接/启动子进程。initialize 握手由 McpClient 在 connect 后调。"""
        ...

    async def send_jsonrpc(
        self, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        """发送一条 JSON-RPC 请求/通知/响应，返回匹配的响应。

        - 请求（含 id）：返回对应响应 dict；超时/错误抛
        - 通知（无 id）：返回 None（server 对通知无响应）
        """
        ...

    async def disconnect(self) -> None:
        """关闭连接/终止子进程。"""
        ...