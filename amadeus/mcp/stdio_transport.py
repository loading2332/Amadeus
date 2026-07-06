from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RECV_TIMEOUT = 30.0
_CONNECT_TIMEOUT = 8.0
_STREAM_LIMIT = 4 * 1024 * 1024  # 4 MB，防大响应触发 StreamReader 行限
_DISCONNECT_WAIT = 5.0


def _infer_cwd(command: list[str]) -> str | None:
    """从 command 中找第一个绝对路径文件，返回其父目录作为 cwd。"""
    for arg in command:
        p = Path(arg)
        if p.is_absolute() and p.is_file():
            return str(p.parent)
    return None


@dataclass
class StdioMcpTransport:
    """stdio transport：启动 MCP server 子进程，行式 JSON-RPC。

    直抄 akashic client.py 的进程生命周期管理（stderr drain / 超时诊断 /
    terminate→kill），但把 JSON-RPC 收发收敛到 send_jsonrpc。
    """

    name: str
    command: list[str]
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    _process: asyncio.subprocess.Process | None = None
    _next_id: int = 1
    _recent_stdout: deque[str] = field(default_factory=lambda: deque(maxlen=8))
    _recent_stderr: deque[str] = field(default_factory=lambda: deque(maxlen=8))

    def __post_init__(self) -> None:
        if not self.cwd:
            self.cwd = _infer_cwd(self.command)

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def connect(self) -> None:
        proc_env = {**os.environ, **self.env}
        logger.debug(
            "[mcp:%s] 启动 stdio: %s cwd=%s", self.name, self.command, self.cwd
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=proc_env,
                cwd=self.cwd,
                limit=_STREAM_LIMIT,
            )
        except FileNotFoundError as e:
            raise ConnectionError(
                f"MCP server {self.name!r} 启动失败（命令不存在）: {self.command[0]}"
            ) from e
        _ = asyncio.create_task(self._drain_stderr())

    async def send_jsonrpc(
        self, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        if self._process is None or self._process.stdin is None:
            raise ConnectionError(f"MCP server {self.name!r} 未连接")
        await self._send(payload)
        # 通知（无 id）不期望响应
        if "id" not in payload:
            return None
        return await self._recv(
            expected_id=payload["id"],
            stage=payload.get("method", "recv"),
            timeout=timeout,
        )

    async def disconnect(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            _ = await asyncio.wait_for(self._process.wait(), timeout=_DISCONNECT_WAIT)
        except TimeoutError:
            self._process.kill()
            _ = await self._process.wait()
        except Exception as e:
            logger.warning("[mcp:%s] 断开时出错: %s", self.name, e)
        finally:
            self._process = None

    def _new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    async def _send(self, payload: dict[str, Any]) -> None:
        assert self._process and self._process.stdin
        logger.debug(
            "[mcp:%s] -> %s", self.name, json.dumps(payload, ensure_ascii=False)[:400]
        )
        self._process.stdin.write(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        )
        await self._process.stdin.drain()

    async def _recv(
        self,
        *,
        expected_id: int | None,
        stage: str,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        assert self._process and self._process.stdout
        recv_timeout = _RECV_TIMEOUT if timeout is None else timeout
        while True:
            try:
                line = await asyncio.wait_for(
                    self._process.stdout.readline(), timeout=recv_timeout
                )
            except TimeoutError as e:
                raise TimeoutError(
                    self._build_timeout_message(stage, expected_id, recv_timeout)
                ) from e
            if not line:
                raise ConnectionError(
                    f"MCP server {self.name!r} 意外关闭了 stdout"
                )
            text = line.decode().strip()
            if not text:
                continue
            self._recent_stdout.append(text[:500])
            try:
                msg = json.loads(text)
            except json.JSONDecodeError:
                logger.debug("[mcp:%s] 非 JSON 输出: %s", self.name, text[:200])
                continue
            # 跳过通知（有 method 无 id）
            if "method" in msg and "id" not in msg:
                logger.debug("[mcp:%s] <- notification: %s", self.name, text[:400])
                continue
            if expected_id is not None and msg.get("id") != expected_id:
                logger.debug(
                    "[mcp:%s] <- skip id=%r expect=%r",
                    self.name,
                    msg.get("id"),
                    expected_id,
                )
                continue
            logger.debug("[mcp:%s] <- %s", self.name, text[:400])
            return msg

    async def _drain_stderr(self) -> None:
        assert self._process and self._process.stderr
        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                text = line.decode().rstrip()
                self._recent_stderr.append(text[:500])
                logger.debug("[mcp:%s] stderr: %s", self.name, text)
        except Exception:
            pass

    def _build_timeout_message(
        self, stage: str, expected_id: int | None, timeout: float
    ) -> str:
        details = [
            f"MCP server {self.name!r} 在阶段 {stage!r} 等待响应超时（{timeout:.0f}s）",
        ]
        if expected_id is not None:
            details.append(f"expected_id={expected_id}")
        if self.command:
            details.append(f"command={self.command!r}")
        if self.cwd:
            details.append(f"cwd={self.cwd}")
        if self._recent_stdout:
            details.append("recent_stdout=" + " | ".join(self._recent_stdout))
        if self._recent_stderr:
            details.append("recent_stderr=" + " | ".join(self._recent_stderr))
        return "; ".join(details)