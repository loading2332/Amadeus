from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2025-06-18"
_CLIENT_INFO = {"name": "amadeus", "version": "0.1.0"}
_CONNECT_TIMEOUT_SECONDS = 8.0
_CALL_TIMEOUT_SECONDS = 30.0
_SHUTDOWN_WAIT_SECONDS = 2.0
_PIPE_CLOSE_WAIT_SECONDS = 0.25
_CANCELLATION_SEND_TIMEOUT_SECONDS = 0.2
_STREAM_LIMIT_BYTES = 4 * 1024 * 1024

# MCP server 是不受信任的子进程。默认只传递启动命令所需的常见环境变量；
# server 专用凭据必须由调用方通过 env 显式提供。
_SAFE_ENV_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOME",
        "HOMEDRIVE",
        "HOMEPATH",
        "LOCALAPPDATA",
        "LOGNAME",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "PROGRAMDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMW6432",
        "SHELL",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TERM",
        "TMP",
        "USER",
        "USERPROFILE",
        "WINDIR",
    }
)


@dataclass(frozen=True)
class McpToolInfo:
    """`tools/list` 返回的单个远端工具。"""

    name: str
    description: str
    # 保留 object，让 Registry 能把格式错误的 schema 作为单工具错误跳过，
    # 而不是让一个坏工具拖垮整个 server 的接入。
    input_schema: object


@dataclass(frozen=True)
class McpCallResult:
    """MCP 工具结果，区分协议错误与工具自身报告的执行错误。"""

    content: list[dict[str, Any]]
    structured_content: dict[str, Any] | None
    is_error: bool


class McpProtocolError(ConnectionError):
    """远端输出不符合当前支持的 MCP/JSON-RPC 契约。"""


class McpJsonRpcError(RuntimeError):
    """远端返回 JSON-RPC error response。"""

    def __init__(self, *, code: object, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"MCP JSON-RPC error {code}: {message}")


def _build_child_environment(overrides: Mapping[str, str] | None) -> dict[str, str]:
    inherited = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _SAFE_ENV_KEYS
    }
    if overrides is None:
        return inherited
    for key, value in overrides.items():
        if not isinstance(key, str) or not key:
            raise ValueError("MCP env key 必须是非空字符串")
        if not isinstance(value, str):
            raise ValueError(f"MCP env {key!r} 的值必须是字符串")
        inherited[key] = value
    return inherited


class McpClient:
    """本地 stdio MCP Host client。

    一个 client 只有一个 stdout reader。`_io_lock` 覆盖完整请求/响应往返，
    因而同一 server 串行、不同 client 仍可并行。
    """

    def __init__(
        self,
        name: str,
        command: list[str],
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        if not name:
            raise ValueError("MCP server name 不能为空")
        if not command or any(not isinstance(part, str) or not part for part in command):
            raise ValueError("MCP command 必须是非空字符串列表")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("MCP cwd 必须是字符串")

        self.name = name
        self._command = list(command)
        self._env = _build_child_environment(env)
        self._cwd = cwd
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._tool_infos: list[McpToolInfo] = []
        self._next_id = 1
        self._io_lock = asyncio.Lock()
        self._closing = False
        self._connected = False

    @property
    def tool_infos(self) -> list[McpToolInfo]:
        return list(self._tool_infos)

    @property
    def is_alive(self) -> bool:
        return (
            self._connected
            and not self._closing
            and self._process is not None
            and self._process.returncode is None
        )

    async def connect(self) -> list[McpToolInfo]:
        """启动子进程并完成 initialize、initialized 与分页 tools/list。"""
        async with self._io_lock:
            if self._closing:
                raise ConnectionError(f"MCP server {self.name!r} 正在关闭")
            if self._process is not None:
                raise RuntimeError(f"MCP server {self.name!r} 已连接")
            try:
                return await asyncio.wait_for(
                    self._connect_locked(),
                    timeout=_CONNECT_TIMEOUT_SECONDS,
                )
            except TimeoutError as error:
                await self._cleanup_after_failure()
                raise TimeoutError(
                    f"MCP server {self.name!r} 连接超时"
                ) from error
            except BaseException:
                await self._cleanup_after_failure()
                raise

    async def _connect_locked(self) -> list[McpToolInfo]:
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
                cwd=self._cwd,
                limit=_STREAM_LIMIT_BYTES,
            )
        except FileNotFoundError as error:
            raise ConnectionError(
                f"MCP server {self.name!r} 启动失败：命令不存在"
            ) from error
        except OSError as error:
            raise ConnectionError(
                f"MCP server {self.name!r} 启动失败：{error.strerror or type(error).__name__}"
            ) from error

        self._stderr_task = asyncio.create_task(
            self._drain_stderr(),
            name=f"mcp-stderr:{self.name}",
        )

        init_result = await self._request_locked(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
            timeout=None,
        )
        self._validate_initialize_result(init_result)
        await self._send_locked(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}
        )

        tool_infos = await self._list_tools_locked()
        self._tool_infos = tool_infos
        self._connected = True
        logger.info("[mcp:%s] 已连接，发现 %d 个工具", self.name, len(tool_infos))
        return list(tool_infos)

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        """调用远端工具；超时或取消时尽力发送 MCP cancellation。"""
        if not tool_name:
            raise ValueError("MCP tool name 不能为空")
        if not isinstance(arguments, dict):
            raise TypeError("MCP tool arguments 必须是 dict")
        call_timeout = _CALL_TIMEOUT_SECONDS if timeout is None else timeout
        if call_timeout <= 0:
            raise ValueError("MCP call timeout 必须大于 0")
        if self._closing:
            raise ConnectionError(f"MCP server {self.name!r} 正在关闭")
        try:
            return await asyncio.wait_for(
                self._call_serialized(tool_name, arguments),
                timeout=call_timeout,
            )
        except TimeoutError as error:
            raise TimeoutError(
                f"MCP server {self.name!r} 调用工具 {tool_name!r} 超时"
            ) from error

    async def _call_serialized(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> McpCallResult:
        async with self._io_lock:
            if self._closing:
                raise ConnectionError(f"MCP server {self.name!r} 正在关闭")
            self._require_live_process()
            request_id = self._new_id()
            try:
                await self._send_locked(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": tool_name, "arguments": arguments},
                    }
                )
                response = await self._receive_response_locked(
                    expected_id=request_id,
                    timeout=None,
                )
                result = self._extract_result(response)
                return self._parse_call_result(result)
            except asyncio.CancelledError:
                await self._send_cancellation_locked(
                    request_id,
                    "Amadeus tool call was cancelled or timed out",
                )
                raise
            except ConnectionError:
                self._connected = False
                raise

    async def disconnect(self) -> None:
        """停止新调用，等待当前调用结束，然后按 EOF -> TERM -> KILL 回收。"""
        self._closing = True
        self._connected = False

        async def _disconnect() -> None:
            async with self._io_lock:
                await self._cleanup_process()
                self._tool_infos = []

        disconnect_task = asyncio.create_task(_disconnect())
        try:
            await asyncio.shield(disconnect_task)
        except asyncio.CancelledError:
            # shutdown 的调用方被取消也不能遗留子进程；回收完成后再传播取消。
            await _finish_task_shielded(disconnect_task)
            raise

    async def _list_tools_locked(self) -> list[McpToolInfo]:
        tool_infos: list[McpToolInfo] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        while True:
            params = {} if cursor is None else {"cursor": cursor}
            response = await self._request_locked(
                "tools/list",
                params,
                timeout=None,
            )
            raw_tools = response.get("tools")
            if not isinstance(raw_tools, list):
                raise McpProtocolError(
                    f"MCP server {self.name!r} tools/list 缺少 tools array"
                )
            for raw_tool in raw_tools:
                info = self._parse_tool_info(raw_tool)
                if info is not None:
                    tool_infos.append(info)

            raw_cursor = response.get("nextCursor")
            if raw_cursor is None:
                return tool_infos
            if not isinstance(raw_cursor, str):
                raise McpProtocolError(
                    f"MCP server {self.name!r} tools/list nextCursor 必须是字符串"
                )
            if raw_cursor in seen_cursors:
                raise McpProtocolError(
                    f"MCP server {self.name!r} tools/list 返回了重复 cursor"
                )
            seen_cursors.add(raw_cursor)
            cursor = raw_cursor

    def _parse_tool_info(self, raw_tool: object) -> McpToolInfo | None:
        if not isinstance(raw_tool, dict):
            logger.warning("[mcp:%s] 跳过非 object 工具描述", self.name)
            return None
        raw_name = raw_tool.get("name")
        if not isinstance(raw_name, str) or not raw_name:
            logger.warning("[mcp:%s] 跳过缺少合法 name 的工具描述", self.name)
            return None
        raw_description = raw_tool.get("description", "")
        description = raw_description if isinstance(raw_description, str) else ""
        return McpToolInfo(
            name=raw_name,
            description=description,
            input_schema=raw_tool.get("inputSchema"),
        )

    async def _request_locked(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None,
    ) -> dict[str, Any]:
        request_id = self._new_id()
        await self._send_locked(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        response = await self._receive_response_locked(
            expected_id=request_id,
            timeout=timeout,
        )
        return self._extract_result(response)

    async def _receive_response_locked(
        self,
        *,
        expected_id: int,
        timeout: float | None,
    ) -> dict[str, Any]:
        process = self._require_live_process()
        assert process.stdout is not None
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        while True:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                raise TimeoutError
            try:
                if remaining is None:
                    line = await process.stdout.readline()
                else:
                    line = await asyncio.wait_for(
                        process.stdout.readline(),
                        timeout=remaining,
                    )
            except (ValueError, asyncio.LimitOverrunError) as error:
                raise McpProtocolError(
                    f"MCP server {self.name!r} 返回了过大的 JSON-RPC 消息"
                ) from error
            if not line:
                raise ConnectionError(
                    f"MCP server {self.name!r} 意外关闭了 stdout"
                )

            try:
                text = line.decode("utf-8").strip()
            except UnicodeDecodeError as error:
                raise McpProtocolError(
                    f"MCP server {self.name!r} stdout 不是合法 UTF-8"
                ) from error
            if not text:
                continue
            try:
                message = json.loads(text)
            except json.JSONDecodeError as error:
                raise McpProtocolError(
                    f"MCP server {self.name!r} stdout 包含非 JSON-RPC 内容"
                ) from error
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise McpProtocolError(
                    f"MCP server {self.name!r} 返回了非法 JSON-RPC 消息"
                )

            if "method" in message:
                await self._handle_server_message_locked(message)
                continue
            if message.get("id") != expected_id:
                logger.debug(
                    "[mcp:%s] 跳过非当前响应 id=%r，当前 id=%r",
                    self.name,
                    message.get("id"),
                    expected_id,
                )
                continue
            return cast("dict[str, Any]", message)

    async def _handle_server_message_locked(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        if request_id is None:
            logger.debug(
                "[mcp:%s] 收到 notification method=%r",
                self.name,
                message.get("method"),
            )
            return
        if message.get("method") == "ping":
            await self._send_locked(
                {"jsonrpc": "2.0", "id": request_id, "result": {}}
            )
            return
        await self._send_locked(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": "Method not found"},
            }
        )

    async def _send_cancellation_locked(self, request_id: int, reason: str) -> None:
        try:
            await asyncio.wait_for(
                self._send_locked(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/cancelled",
                        "params": {"requestId": request_id, "reason": reason},
                    }
                ),
                timeout=_CANCELLATION_SEND_TIMEOUT_SECONDS,
            )
        except (ConnectionError, BrokenPipeError, TimeoutError):
            logger.debug("[mcp:%s] cancellation 发送失败", self.name)

    async def _send_locked(self, payload: dict[str, Any]) -> None:
        process = self._require_live_process()
        if process.stdin is None:
            raise ConnectionError(f"MCP server {self.name!r} stdin 不可用")
        try:
            encoded = (
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            process.stdin.write(encoded)
            await process.stdin.drain()
        except OSError as error:
            raise ConnectionError(
                f"MCP server {self.name!r} stdin 已关闭"
            ) from error

    def _require_live_process(self) -> asyncio.subprocess.Process:
        process = self._process
        if process is None or process.returncode is not None:
            self._connected = False
            raise ConnectionError(f"MCP server {self.name!r} 未连接")
        return process

    def _new_id(self) -> int:
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _extract_result(self, response: dict[str, Any]) -> dict[str, Any]:
        if "error" in response:
            error = response["error"]
            if isinstance(error, dict):
                code = error.get("code")
                raw_message = error.get("message", "Unknown error")
            else:
                code = None
                raw_message = error
            raise McpJsonRpcError(code=code, message=str(raw_message))
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError(
                f"MCP server {self.name!r} JSON-RPC response 缺少 object result"
            )
        return cast("dict[str, Any]", result)

    def _validate_initialize_result(self, result: dict[str, Any]) -> None:
        if result.get("protocolVersion") != _PROTOCOL_VERSION:
            raise McpProtocolError(
                f"MCP server {self.name!r} 不支持协议 {_PROTOCOL_VERSION}"
            )
        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict) or "tools" not in capabilities:
            raise McpProtocolError(
                f"MCP server {self.name!r} 未声明 tools capability"
            )

    def _parse_call_result(self, result: dict[str, Any]) -> McpCallResult:
        if "content" not in result:
            raise McpProtocolError(
                f"MCP server {self.name!r} tools/call 缺少 content"
            )
        raw_content = result["content"]
        if not isinstance(raw_content, list) or any(
            not isinstance(block, dict) for block in raw_content
        ):
            raise McpProtocolError(
                f"MCP server {self.name!r} tools/call content 必须是 object array"
            )
        raw_structured = result.get("structuredContent")
        if raw_structured is not None and not isinstance(raw_structured, dict):
            raise McpProtocolError(
                f"MCP server {self.name!r} structuredContent 必须是 object"
            )
        raw_is_error = result.get("isError", False)
        if not isinstance(raw_is_error, bool):
            raise McpProtocolError(
                f"MCP server {self.name!r} isError 必须是 boolean"
            )
        return McpCallResult(
            content=cast("list[dict[str, Any]]", raw_content),
            structured_content=cast("dict[str, Any] | None", raw_structured),
            is_error=raw_is_error,
        )

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        try:
            while await process.stderr.read(64 * 1024):
                # 不记录内容：第三方 server 可能把凭据写到 stderr。
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("[mcp:%s] stderr drain 异常结束", self.name)

    async def _cleanup_after_failure(self) -> None:
        cleanup_task = asyncio.create_task(self._cleanup_process())
        # connect 本身被取消时，仍需等子进程完成回收，再传播原始失败。
        await _finish_task_shielded(cleanup_task)

    async def _cleanup_process(self) -> None:
        process = self._process
        stderr_task = self._stderr_task
        if process is None:
            if stderr_task is not None:
                stderr_task.cancel()
                await asyncio.gather(stderr_task, return_exceptions=True)
                self._stderr_task = None
            return

        stdin_closed_task: asyncio.Task[None] | None = None
        if process.stdin is not None:
            try:
                process.stdin.close()
                stdin_closed_task = asyncio.create_task(
                    process.stdin.wait_closed()
                )
                stdin_closed_task.add_done_callback(_consume_task_result)
                await asyncio.wait_for(
                    asyncio.shield(stdin_closed_task),
                    timeout=_PIPE_CLOSE_WAIT_SECONDS,
                )
            except (
                BrokenPipeError,
                ConnectionResetError,
                OSError,
                RuntimeError,
                TimeoutError,
            ):
                pass

        if process.returncode is None:
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=_SHUTDOWN_WAIT_SECONDS,
                )
            except (OSError, TimeoutError):
                try:
                    process.terminate()
                except (OSError, ProcessLookupError):
                    pass

        if process.returncode is None:
            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=_SHUTDOWN_WAIT_SECONDS,
                )
            except (OSError, TimeoutError):
                try:
                    process.kill()
                except (OSError, ProcessLookupError):
                    pass
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=_SHUTDOWN_WAIT_SECONDS,
                    )
                except (OSError, TimeoutError):
                    pass

        if process.returncode is None:
            raise ConnectionError(f"MCP server {self.name!r} 子进程无法回收")

        if stdin_closed_task is not None and not stdin_closed_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(stdin_closed_task),
                    timeout=_PIPE_CLOSE_WAIT_SECONDS,
                )
            except (
                BrokenPipeError,
                ConnectionResetError,
                OSError,
                RuntimeError,
                TimeoutError,
            ):
                pass
        if stdin_closed_task is not None and stdin_closed_task.done():
            _consume_task_result(stdin_closed_task)

        if stderr_task is not None:
            if not stderr_task.done():
                stderr_task.cancel()
            await asyncio.gather(stderr_task, return_exceptions=True)

        self._stderr_task = None
        self._process = None


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass


async def _finish_task_shielded(task: asyncio.Task[None]) -> None:
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    task.result()


__all__ = [
    "McpCallResult",
    "McpClient",
    "McpJsonRpcError",
    "McpProtocolError",
    "McpToolInfo",
]
