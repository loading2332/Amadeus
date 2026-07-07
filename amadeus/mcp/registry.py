from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from amadeus.mcp.client import McpClient
from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.http_transport import StreamableHttpMcpTransport
from amadeus.mcp.schema_validator import validate_openai_function_schema
from amadeus.mcp.stdio_transport import StdioMcpTransport
from amadeus.mcp.tool import McpToolWrapper
from amadeus.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from amadeus.db.mcp_servers import McpServersStore

logger = logging.getLogger(__name__)


@dataclass
class McpServerRegistry:
    """管理多个 MCP server 的连接生命周期 + 工具注册。

    P7：可选注入 McpServersStore 做 postgres 持久化。add/remove 同步落库；
    load_all_from_db 从 db 加载所有 authorized server 并重连。
    """

    tool_registry: ToolRegistry
    store: McpServersStore | None = None
    _clients: dict[str, McpClient] = field(default_factory=dict)
    _configs: dict[str, McpServerConfig] = field(default_factory=dict)

    def _build_transport(self, config: McpServerConfig):
        if config.transport_type == "stdio":
            if not config.command:
                raise ValueError(f"stdio server {config.name!r} 缺少 command")
            return StdioMcpTransport(
                name=config.name,
                command=config.command,
                env=config.env or {},
                cwd=config.cwd,
            )
        if config.transport_type == "http":
            if not config.url:
                raise ValueError(f"http server {config.name!r} 缺少 url")
            return StreamableHttpMcpTransport(
                name=config.name,
                url=config.url,
                headers=config.headers or {},
            )
        raise ValueError(f"未知 transport_type: {config.transport_type!r}")

    async def add(self, config: McpServerConfig) -> tuple[list[str], list[tuple[str, list[str]]]]:
        """连接 server + 注册工具。返回 (已注册工具名列表, [(跳过工具名, 错误列表)])。

        幂等：同名 server 已存在则拒绝。
        """
        if config.name in self._clients:
            raise ValueError(f"MCP server {config.name!r} 已存在")
        transport = self._build_transport(config)
        client = McpClient(transport=transport)
        try:
            tool_infos = await client.connect()
        except Exception:
            await client.disconnect()
            raise

        registered: list[str] = []
        skipped: list[tuple[str, list[str]]] = []
        for info in tool_infos:
            errors = validate_openai_function_schema(info.input_schema)
            if errors:
                skipped.append((info.name, errors))
                logger.warning(
                    "[mcp:%s] 工具 %r schema 校验失败，跳过: %s",
                    config.name,
                    info.name,
                    errors,
                )
                continue
            wrapper = McpToolWrapper(client, info, server_name=config.name)
            self.tool_registry.register(
                wrapper,
                risk="external-side-effect",
                source_type="mcp",
                source_name=config.name,
            )
            registered.append(wrapper.name)

        self._clients[config.name] = client
        self._configs[config.name] = config
        if self.store is not None:
            self.store.upsert(config, authorized=True)
        logger.info(
            "[mcp:%s] 已连接，注册 %d 工具，跳过 %d",
            config.name,
            len(registered),
            len(skipped),
        )
        return registered, skipped

    async def remove(self, name: str) -> None:
        """按 source_name 反查 unregister 所有相关工具 + 断开 client。"""
        client = self._clients.pop(name, None)
        self._configs.pop(name, None)
        if self.store is not None:
            try:
                self.store.delete(name)
            except Exception as e:
                logger.warning("[mcp:%s] 从 db 删除失败: %s", name, e)
        if client is None:
            return
        # 反查该 server 名下所有工具，unregister
        for tool_name in self.tool_registry.get_names_by_source(name):
            self.tool_registry.unregister(tool_name)
        await client.disconnect()
        logger.info("[mcp:%s] 已断开并卸载工具", name)

    def list_servers(self) -> list[McpServerConfig]:
        return list(self._configs.values())

    async def load_and_connect_all(self, configs: list[McpServerConfig]) -> None:
        """并行重连所有 server（P7 从 db 加载后调）。失败的 server 记日志不阻断。"""
        async def _connect_one(cfg: McpServerConfig) -> None:
            try:
                await self.add(cfg)
            except Exception as e:
                logger.warning("[mcp:%s] 重连失败: %s", cfg.name, e)

        await asyncio.gather(*[_connect_one(c) for c in configs])

    async def load_all_from_db(self) -> None:
        """从 postgres 加载所有 authorized server 并重连。"""
        if self.store is None:
            return
        try:
            configs = self.store.list_authorized()
        except Exception as e:
            logger.warning("[mcp] 从 db 加载 mcp_servers 失败: %s", e)
            return
        await self.load_and_connect_all(configs)

    def start_connect_all_background(self, configs: list[McpServerConfig] | None = None) -> asyncio.Task:
        """后台重连，不阻塞主服务启动。

        configs 为 None 时从 db 加载（需注入 store）。
        """

        async def _bg() -> None:
            if configs is not None:
                await self.load_and_connect_all(configs)
            else:
                await self.load_all_from_db()

        return asyncio.create_task(_bg())

    async def shutdown(self) -> None:
        """并行断开所有 client。"""
        names = list(self._clients.keys())

        async def _disconnect_one(name: str) -> None:
            client = self._clients.pop(name, None)
            if client is not None:
                try:
                    await client.disconnect()
                except Exception as e:
                    logger.warning("[mcp:%s] shutdown 断开出错: %s", name, e)

        await asyncio.gather(*[_disconnect_one(n) for n in names])