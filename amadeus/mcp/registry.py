from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Literal
from weakref import WeakValueDictionary

from amadeus.mcp.client import McpClient
from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.schema_validator import validate_openai_function_schema
from amadeus.mcp.tool import McpToolWrapper, validate_server_name
from amadeus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

McpConnectionStatus = Literal["connected", "disconnected"]


class McpServerNotFoundError(LookupError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"MCP server {name!r} 不存在")


@dataclass(frozen=True)
class McpServerStatus:
    name: str
    status: McpConnectionStatus
    tools: tuple[str, ...]


@dataclass
class McpServerRegistry:
    """管理本进程内的 MCP client，并把 wrappers 原子注入 ToolRegistry。"""

    tool_registry: ToolRegistry
    _clients: dict[str, McpClient] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _cleanup_clients: dict[str, McpClient] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _tool_names: dict[str, tuple[str, ...]] = field(default_factory=dict, init=False)
    _removing: set[str] = field(default_factory=set, init=False, repr=False)
    _lifecycle_locks: WeakValueDictionary[str, asyncio.Lock] = field(
        default_factory=WeakValueDictionary,
        init=False,
        repr=False,
    )
    _mutation_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )
    _shutdown_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock,
        init=False,
        repr=False,
    )
    _shutting_down: bool = field(default=False, init=False)
    _active_adds: int = field(default=0, init=False, repr=False)
    _adds_drained: asyncio.Event = field(
        default_factory=asyncio.Event,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        self._adds_drained.set()

    async def add(
        self,
        config: McpServerConfig,
    ) -> tuple[list[str], list[tuple[str, list[str]]]]:
        """连接并注册合法工具；失败时不发布任何半成品状态。"""
        normalized = self._validate_config(config)
        if self._shutting_down:
            raise RuntimeError("MCP registry 正在关闭")
        self._active_adds += 1
        self._adds_drained.clear()
        try:
            return await self._add_tracked(normalized)
        finally:
            self._active_adds -= 1
            if self._active_adds == 0:
                self._adds_drained.set()

    async def _add_tracked(
        self,
        normalized: McpServerConfig,
    ) -> tuple[list[str], list[tuple[str, list[str]]]]:
        lock = self._lifecycle_locks.setdefault(normalized.name, asyncio.Lock())
        async with lock:
            if self._shutting_down:
                raise RuntimeError("MCP registry 正在关闭")
            if (
                normalized.name in self._clients
                or normalized.name in self._cleanup_clients
            ):
                raise ValueError(f"MCP server {normalized.name!r} 已存在")

            client = McpClient(
                name=normalized.name,
                command=normalized.command,
                env=normalized.env,
                cwd=normalized.cwd,
            )
            registered: list[str] = []
            try:
                tool_infos = await client.connect()
                candidates: list[McpToolWrapper] = []
                skipped: list[tuple[str, list[str]]] = []
                for info in tool_infos:
                    errors = validate_openai_function_schema(info.input_schema)
                    if not errors:
                        try:
                            candidates.append(
                                McpToolWrapper(
                                    client,
                                    info,
                                    server_name=normalized.name,
                                )
                            )
                        except ValueError as error:
                            errors = [str(error)]
                    if errors:
                        skipped.append((info.name, errors))
                        logger.warning(
                            "[mcp:%s] 跳过工具 %r：schema 或名称不兼容",
                            normalized.name,
                            info.name,
                        )

                if not candidates:
                    raise ValueError(
                        f"MCP server {normalized.name!r} 没有可注册的合法工具"
                    )

                candidate_names = [wrapper.name for wrapper in candidates]
                if len(candidate_names) != len(set(candidate_names)):
                    raise ValueError(
                        f"MCP server {normalized.name!r} 返回了重复工具名"
                    )

                async with self._mutation_lock:
                    if self._shutting_down:
                        raise RuntimeError("MCP registry 正在关闭")
                    conflicts = (
                        self.tool_registry.get_registered_names()
                        & set(candidate_names)
                    )
                    if conflicts:
                        names = ", ".join(sorted(conflicts))
                        raise ValueError(f"MCP wrapper 名称冲突：{names}")
                    try:
                        for wrapper in candidates:
                            self.tool_registry.register(
                                wrapper,
                                risk="external-side-effect",
                                always_on=False,
                                source_type="mcp",
                                source_name=normalized.name,
                            )
                            registered.append(wrapper.name)
                        # 发布必须和关闭状态复检处于同一个无 await 临界区。
                        self._clients[normalized.name] = client
                        self._tool_names[normalized.name] = tuple(registered)
                    except BaseException:
                        for tool_name in registered:
                            self.tool_registry.unregister(tool_name)
                        registered.clear()
                        self._clients.pop(normalized.name, None)
                        self._tool_names.pop(normalized.name, None)
                        raise

                logger.info(
                    "[mcp:%s] 注册 %d 个工具，跳过 %d 个",
                    normalized.name,
                    len(registered),
                    len(skipped),
                )
                return list(registered), skipped
            except BaseException:
                if registered:
                    async with self._mutation_lock:
                        for tool_name in registered:
                            self.tool_registry.unregister(tool_name)
                    self._clients.pop(normalized.name, None)
                    self._tool_names.pop(normalized.name, None)
                try:
                    await client.disconnect()
                except BaseException:
                    # 不丢失唯一 owner：remove/shutdown 可按 name 重试回收。
                    self._cleanup_clients[normalized.name] = client
                    logger.warning("[mcp:%s] add 回滚关闭失败", normalized.name)
                raise

    async def remove(self, name: str) -> list[str]:
        """先注销 wrappers，再等待当前调用结束并回收 client。"""
        if self._shutting_down:
            raise RuntimeError("MCP registry 正在关闭")
        return await self._remove(name, allow_during_shutdown=False)

    async def _remove(
        self,
        name: str,
        *,
        allow_during_shutdown: bool,
    ) -> list[str]:
        if not allow_during_shutdown and self._shutting_down:
            raise RuntimeError("MCP registry 正在关闭")
        lock = self._lifecycle_locks.setdefault(name, asyncio.Lock())
        async with lock:
            client = self._clients.get(name) or self._cleanup_clients.get(name)
            if client is None:
                raise McpServerNotFoundError(name)
            tool_names = self._tool_names.get(name, ())
            async with self._mutation_lock:
                self._removing.add(name)
                for tool_name in tool_names:
                    self.tool_registry.unregister(tool_name)
            await client.disconnect()
            self._clients.pop(name, None)
            self._cleanup_clients.pop(name, None)
            self._tool_names.pop(name, None)
            self._removing.discard(name)
            logger.info("[mcp:%s] 已断开并卸载 %d 个工具", name, len(tool_names))
            return list(tool_names)

    def list_servers(self) -> list[McpServerStatus]:
        return [
            McpServerStatus(
                name=name,
                status=(
                    "connected"
                    if client.is_alive and name not in self._removing
                    else "disconnected"
                ),
                tools=(
                    self._tool_names.get(name, ())
                    if name not in self._removing
                    else ()
                ),
            )
            for name, client in self._clients.items()
        ]

    async def shutdown(self) -> None:
        """阻止新操作，并行回收不同 server；单个失败不阻断其他 server。"""
        async with self._shutdown_lock:
            self._shutting_down = True
            await self._adds_drained.wait()
            names = list(dict.fromkeys([*self._clients, *self._cleanup_clients]))
            results = await asyncio.gather(
                *(
                    self._remove(name, allow_during_shutdown=True)
                    for name in names
                ),
                return_exceptions=True,
            )
            for name, result in zip(names, results, strict=True):
                if isinstance(result, BaseException):
                    logger.warning("[mcp:%s] shutdown 失败：%s", name, type(result).__name__)

    @staticmethod
    def _validate_config(config: McpServerConfig) -> McpServerConfig:
        if not isinstance(config, McpServerConfig):
            raise TypeError("config 必须是 McpServerConfig")
        validate_server_name(config.name)
        if not isinstance(config.command, list) or not config.command or any(
            not isinstance(part, str) or not part for part in config.command
        ):
            raise ValueError("MCP command 必须是非空字符串列表")
        if config.env is not None:
            if not isinstance(config.env, dict):
                raise ValueError("MCP env 必须是 object")
            if any(
                not isinstance(key, str)
                or not key
                or not isinstance(value, str)
                for key, value in config.env.items()
            ):
                raise ValueError("MCP env 的 key 和 value 必须是字符串")
        if config.cwd is not None and not isinstance(config.cwd, str):
            raise ValueError("MCP cwd 必须是字符串")
        return McpServerConfig(
            name=config.name,
            command=list(config.command),
            env=dict(config.env) if config.env is not None else None,
            cwd=config.cwd,
        )


__all__ = [
    "McpConnectionStatus",
    "McpServerNotFoundError",
    "McpServerRegistry",
    "McpServerStatus",
]
