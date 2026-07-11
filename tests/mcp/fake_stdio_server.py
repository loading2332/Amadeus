"""用于 MCP Host 测试的本地 stdio server。

公开的 MCP 工具只有 ``echo`` 和 ``add``，因此它也可以被 Registry 和端到端
测试复用。以 ``__test_`` 开头的调用只用于暴露协议状态和故障场景，不出现在
``tools/list`` 中。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from typing import Any

_PROTOCOL_VERSION = "2025-06-18"
_SERVER_PING_ID = "fake-server-ping"

_stdout_lock = threading.Lock()
_state_lock = threading.Lock()
_initialized = False
_ping_acknowledged = False
_pending_list_request_id: object | None = None
_list_cursors: list[object] = []
_cancelled_request_ids: list[object] = []
_active_calls = 0
_max_active_calls = 0


def _write(payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    with _stdout_lock:
        try:
            sys.stdout.write(encoded + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError, ValueError):
            # Host 已关闭连接时，daemon worker 不应阻止 server 退出。
            return


def _result(request_id: object, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _first_tool_page() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "echo",
                "description": "Echo text",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }
        ],
        "nextCursor": "page-2",
    }


def _second_tool_page() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "add",
                "description": "Add two numbers",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "a": {"type": "number"},
                        "b": {"type": "number"},
                    },
                    "required": ["a", "b"],
                },
            }
        ]
    }


def _begin_call() -> None:
    global _active_calls, _max_active_calls
    with _state_lock:
        _active_calls += 1
        _max_active_calls = max(_max_active_calls, _active_calls)


def _finish_call() -> None:
    global _active_calls
    with _state_lock:
        _active_calls -= 1


def _state_snapshot() -> dict[str, Any]:
    with _state_lock:
        return {
            "initialized": _initialized,
            "pingAcknowledged": _ping_acknowledged,
            "listCursors": list(_list_cursors),
            "cancelledRequestIds": list(_cancelled_request_ids),
            "maxActiveCalls": _max_active_calls,
            "explicitEnv": os.environ.get("MCP_TEST_EXPLICIT"),
            "unsafeParentInherited": "MCP_TEST_UNSAFE" in os.environ,
        }


def _execute_tool_call(message: dict[str, Any]) -> None:
    request_id = message.get("id")
    params = message.get("params")
    if not isinstance(params, dict):
        _write(_error(request_id, -32602, "params must be an object"))
        return
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict):
        _write(_error(request_id, -32602, "arguments must be an object"))
        return

    _begin_call()
    response: dict[str, Any]
    if name == "__test_crash":
        os._exit(23)
    try:
        if name == "echo":
            text = arguments.get("text", "")
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": f"echo: {text}"}]},
            )
        elif name == "add":
            total = arguments.get("a", 0) + arguments.get("b", 0)
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": str(total)}]},
            )
        elif name == "__test_structured_error":
            response = _result(
                request_id,
                {
                    "content": [
                        {"type": "text", "text": "remote validation failed"}
                    ],
                    "structuredContent": {
                        "kind": "validation",
                        "field": "value",
                    },
                    "isError": True,
                },
            )
        elif name == "__test_missing_content":
            response = _result(request_id, {})
        elif name == "__test_large_stderr":
            sys.stderr.write("x" * (5 * 1024 * 1024))
            sys.stderr.flush()
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": "stderr drained"}]},
            )
        elif name == "__test_close_stdout":
            os.close(sys.stdout.fileno())
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": "unreachable"}]},
            )
        elif name == "__test_serial_probe":
            time.sleep(float(arguments.get("delay", 0.08)))
            label = str(arguments.get("label", "probe"))
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": label}]},
            )
        elif name == "__test_slow_late":
            time.sleep(float(arguments.get("delay", 0.12)))
            response = _result(
                request_id,
                {"content": [{"type": "text", "text": "late response"}]},
            )
        elif name == "__test_state":
            snapshot = _state_snapshot()
            response = _result(
                request_id,
                {
                    "content": [{"type": "text", "text": "state"}],
                    "structuredContent": snapshot,
                },
            )
        else:
            response = _error(request_id, -32601, f"unknown tool {name}")
    finally:
        # 在写响应前标记执行结束。这样只有真正重叠执行的调用才会把最大并发数
        # 推高，而不会把“前一响应已完成、后一请求刚到达”误算成重叠。
        _finish_call()
    _write(response)


def _start_tool_call(message: dict[str, Any]) -> None:
    threading.Thread(
        target=_execute_tool_call,
        args=(message,),
        daemon=True,
        name=f"fake-mcp-call-{message.get('id')}",
    ).start()


def _handle_initialize(message: dict[str, Any]) -> None:
    params = message.get("params")
    valid = (
        isinstance(params, dict)
        and params.get("protocolVersion") == _PROTOCOL_VERSION
        and isinstance(params.get("capabilities"), dict)
        and isinstance(params.get("clientInfo"), dict)
    )
    if not valid:
        _write(_error(message.get("id"), -32602, "invalid initialize params"))
        return
    _write(
        _result(
            message.get("id"),
            {
                "protocolVersion": os.environ.get(
                    "FAKE_MCP_PROTOCOL_VERSION",
                    _PROTOCOL_VERSION,
                ),
                "serverInfo": {"name": "fake-stdio-server", "version": "0.2"},
                "capabilities": (
                    {}
                    if os.environ.get("FAKE_MCP_NO_TOOLS") == "1"
                    else {"tools": {}}
                ),
            },
        )
    )


def _handle_tools_list(message: dict[str, Any]) -> None:
    global _pending_list_request_id
    params = message.get("params")
    cursor = params.get("cursor") if isinstance(params, dict) else None
    with _state_lock:
        _list_cursors.append(cursor)

    if not _initialized:
        _write(_error(message.get("id"), -32002, "client not initialized"))
    elif cursor is None:
        _pending_list_request_id = message.get("id")
        _write({"jsonrpc": "2.0", "id": _SERVER_PING_ID, "method": "ping"})
    elif cursor == "page-2":
        _write(_result(message.get("id"), _second_tool_page()))
    else:
        _write(_error(message.get("id"), -32602, "unknown cursor"))


def _handle_ping_response(message: dict[str, Any]) -> None:
    global _pending_list_request_id, _ping_acknowledged
    request_id = _pending_list_request_id
    if request_id is None:
        return
    _pending_list_request_id = None
    if message.get("result") != {}:
        _write(_error(request_id, -32003, "ping was not acknowledged"))
        return
    with _state_lock:
        _ping_acknowledged = True
    _write(_result(request_id, _first_tool_page()))


def main() -> None:
    global _initialized
    for raw_line in sys.stdin:
        try:
            message = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue

        method = message.get("method")
        if method == "initialize":
            _handle_initialize(message)
        elif method == "notifications/initialized":
            with _state_lock:
                _initialized = True
        elif method == "tools/list":
            _handle_tools_list(message)
        elif method == "tools/call":
            params = message.get("params")
            if isinstance(params, dict) and params.get("name") == "__test_pause_reads":
                _write(
                    _result(
                        message.get("id"),
                        {"content": [{"type": "text", "text": "paused"}]},
                    )
                )
                time.sleep(60)
            else:
                _start_tool_call(message)
        elif method == "notifications/cancelled":
            params = message.get("params")
            if isinstance(params, dict):
                with _state_lock:
                    _cancelled_request_ids.append(params.get("requestId"))
        elif method is None and message.get("id") == _SERVER_PING_ID:
            _handle_ping_response(message)


if __name__ == "__main__":
    main()
