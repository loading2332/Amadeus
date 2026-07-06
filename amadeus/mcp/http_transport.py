from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2025-06-18"
_DEFAULT_TIMEOUT = 30.0
_CONNECT_TIMEOUT = 8.0


@dataclass
class StreamableHttpMcpTransport:
    """Streamable HTTP transport（MCP 2025-06-18 规范）。

    单 MCP endpoint（POST + GET 同路径）。所有请求带
    MCP-Protocol-Version header；initialize 响应取 Mcp-Session-Id，
    后续请求带该 header。POST JSON-RPC request 时声明
    Accept: application/json, text/event-stream；按响应 Content-Type
    分发单 JSON 或 SSE 流（两者 MUST 都支持）。
    """

    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    _client: httpx.AsyncClient | None = None
    _session_id: str | None = None

    @property
    def is_alive(self) -> bool:
        return self._client is not None

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(_DEFAULT_TIMEOUT, connect=_CONNECT_TIMEOUT),
            headers={
                "MCP-Protocol-Version": _PROTOCOL_VERSION,
                **self.headers,
            },
        )

    async def send_jsonrpc(
        self, payload: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any] | None:
        if self._client is None:
            raise ConnectionError(f"MCP server {self.name!r} 未连接")
        req_headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id is not None:
            req_headers["Mcp-Session-Id"] = self._session_id

        body = json.dumps(payload, ensure_ascii=False)
        try:
            resp = await self._client.post(
                self.url,
                content=body,
                headers={**req_headers, "Content-Type": "application/json"},
                timeout=timeout if timeout is not None else _DEFAULT_TIMEOUT,
            )
        except httpx.HTTPError as e:
            raise ConnectionError(
                f"MCP server {self.name!r} HTTP 请求失败: {e}"
            ) from e

        # initialize 响应可能带 Mcp-Session-Id
        if self._session_id is None:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self._session_id = sid

        # 通知（无 id）：server 返回 202 Accepted 无 body
        if "id" not in payload:
            if resp.status_code not in (200, 202):
                logger.warning(
                    "[mcp:%s] 通知返回非 2xx: %s %s",
                    self.name,
                    resp.status_code,
                    resp.text[:200],
                )
            return None

        # 请求（含 id）：按 Content-Type 分发
        return await self._parse_response(resp, payload["id"], payload.get("method", "recv"))

    async def _parse_response(
        self, resp: httpx.Response, expected_id: int | str, stage: str
    ) -> dict[str, Any]:
        if resp.status_code >= 400:
            # 尝试解析响应体 MCP error JSON
            err_body = self._try_json(resp)
            if isinstance(err_body, dict) and "error" in err_body:
                err = err_body["error"]
                msg = err.get("message", err) if isinstance(err, dict) else str(err)
            else:
                msg = resp.text[:500] or f"HTTP {resp.status_code}"
            # 归一为 JSON-RPC error 响应，不抛
            return {
                "id": expected_id,
                "error": {
                    "code": resp.status_code,
                    "message": f"MCP error (HTTP {resp.status_code}): {msg}",
                },
            }

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            return await self._parse_sse_stream(resp, expected_id, stage)
        # 单 JSON 响应
        try:
            data = resp.json()
        except Exception as e:
            raise ConnectionError(
                f"MCP server {self.name!r} 阶段 {stage!r} 响应非合法 JSON: {e}; "
                f"body={resp.text[:200]}"
            ) from e
        return data

    async def _parse_sse_stream(
        self, resp: httpx.Response, expected_id: int | str, stage: str
    ) -> dict[str, Any]:
        """解析 SSE 流，从 data 行提取 JSON-RPC message，返回匹配 id 的响应。

        规范：server 在 SSE 流里发 JSON-RPC requests/notifications，
        最终发匹配 client request 的 response 后关闭流。
        """
        target: dict[str, Any] | None = None
        data_buf: list[str] = []
        async for raw_line in resp.aiter_lines():
            line = raw_line.rstrip("\r\n")
            if line == "":
                # 事件分隔
                if data_buf:
                    msg_text = "\n".join(data_buf)
                    data_buf = []
                    msg = self._decode_sse_message(msg_text)
                    if msg is not None:
                        if msg.get("id") == expected_id:
                            target = msg
                        # 其它 message（server 主动 notification/request）暂记日志
                        else:
                            logger.debug(
                                "[mcp:%s] SSE 非 target msg id=%r: %s",
                                self.name,
                                msg.get("id"),
                                str(msg)[:200],
                            )
                continue
            if line.startswith("data:"):
                data_buf.append(line[len("data:"):].lstrip())
            elif line.startswith("event:") or line.startswith("id:"):
                # 标准 SSE 字段，本轮不做 resumability，忽略 id: 字段
                continue
            else:
                # 未知行，累积为 data（兼容非标 server）
                data_buf.append(line)
        if target is not None:
            return target
        # 流关闭但没拿到匹配响应
        raise ConnectionError(
            f"MCP server {self.name!r} 阶段 {stage!r} SSE 流关闭未匹配到 id={expected_id}"
        )

    def _decode_sse_message(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.debug("[mcp:%s] SSE data 非 JSON: %s", self.name, text[:200])
            return None

    def _try_json(self, resp: httpx.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return None

    async def disconnect(self) -> None:
        if self._client is None:
            return
        if self._session_id is not None:
            try:
                await self._client.delete(
                    self.url,
                    headers={"Mcp-Session-Id": self._session_id},
                )
            except httpx.HTTPError:
                pass  # 规范允许 server 不支持 DELETE
        await self._client.aclose()
        self._client = None
        self._session_id = None