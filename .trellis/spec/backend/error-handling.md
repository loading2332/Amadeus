# Error Handling

> Error handling conventions observed in Amadeus backend code.

---

## Overview

Amadeus separates hard runtime failures from observable tool/eval failures.
Configuration and lifecycle failures raise exceptions. Tool execution catches
tool failures and returns structured `ToolResult` plus `ToolTrace`. Evaluation
runners should surface failed cases in reports instead of hiding judge or target
failures as passes.

Primary examples:

- App lifecycle cleanup: `amadeus/app/bootstrap.py`.
- CLI cleanup behavior: `tests/app/test_cli.py`.
- Tool execution: `amadeus/tools/executor.py`.
- Evaluation summarization: `amadeus/evaluation/evaluators.py`.
- Plugin load failure reporting: `amadeus/plugin/manager.py`.

## Error Types

- Use `ValueError` for invalid config, malformed case files, missing required fields, and unsupported modes.
- Use `RuntimeError` for lifecycle state violations, closed app usage, duplicate phase slots, or impossible runtime states.
- Use narrow domain exceptions where they improve caller behavior, e.g. `ToolExecutionDenied` and `MemoryOptimizerBusy`.
- Tool failures should usually return `ToolResult(..., is_error=True)` and a `ToolTrace.status` of `denied` or `error`.

## Error Handling Patterns

- Preserve the original operational failure when cleanup also fails. Add cleanup context as a note instead of replacing the root error.
- Catch plugin load failures at the plugin boundary and report sanitized stage/type information in `PluginLoadRecord`.
- Let configuration validation fail early. `load_runtime_config()` and eval config validation should stop before running partial behavior.
- In eval summary logic, infrastructure skips are failures unless a case explicitly models optional behavior.
- Use typed traces for expected non-fatal outcomes, such as memory retrieval fallbacks, skipped writes, denied tools, and failed eval rows.

## API / CLI Error Responses

- CLI commands print user-facing result summaries for successful runs.
- Trace output should expose stable fields such as session key, message ids, tool chain, memory trace, provider model/usage, and artifact paths.
- Do not print secrets, API keys, or raw plugin exception messages in logs or public reports.

## Common Mistakes

- Do not swallow failed judge or tool behavior as a passing evaluation.
- Do not convert async tool results to sync by awaiting implicitly in `execute()`; use `execute_async()`.
- Do not leak sensitive exception text from plugin import/initialize/terminate failures.

## 工具执行边界补充

- pre hook 属于执行决策边界：`matches()` 或 `run()` 失败时必须阻止真实工具执行，但由 `ToolExecutor` 归一为结构化 `status="error"`，不能让异常击穿 Reasoner。
- post hook 属于观察边界：`matches()` 与 `run()` 都必须遵守 fail-open；成功工具不能因 post hook 失败变成 error，原始工具错误也不能被 post hook 错误覆盖。
- Registry 未知工具名必须抛窄领域异常（当前为 `ToolNotFoundError`），由 Executor 统一记录为 error；禁止返回普通错误字符串造成 `status="success"`。

## 场景：模型可见的本地子进程工具

### 1. 范围 / 触发

- 触发：模型工具可以启动、调用或关闭本地子进程，例如 local-trusted stdio MCP。
- 这类代码同时跨越模型输出、凭据、asyncio pipe 和进程 owner，必须把公开错误与内部清理分开设计。

### 2. 签名

- `McpClient.call(tool_name, arguments, *, timeout=None) -> McpCallResult`
- `McpClient.disconnect() -> None`
- `McpServerRegistry.add(config) -> tuple[registered, skipped]`
- `McpServerRegistry.remove(name) -> list[str]`
- `McpServerRegistry.shutdown() -> None`

### 3. 契约

- tool call timeout 是端到端期限，覆盖 I/O lock 排队、stdin send/drain 和 stdout response，不只覆盖读响应。
- timeout/cancellation 只尽力发送 cancellation，不自动重试可能产生外部副作用的调用。
- shutdown 按 stdin EOF、有限等待、terminate、kill 执行；`wait_closed()` 必须 shield asyncio protocol 拥有的 waiter，不能用 timeout 直接取消它。
- Registry 在确认子进程回收前必须保留 client owner；disconnect 失败后允许 remove/shutdown 重试，不能丢失唯一清理句柄。
- 管理工具只返回稳定错误码，例如 `invalid_request`、`connection_failed`、`protocol_error`、`timeout`；不得把原始异常或 env 值放进模型结果或日志。
- Registry shutdown 先阻止新 add，并等待已经进入 connect 的 add 完成回滚，避免 shutdown 后迟到发布。

### 4. 验证与错误矩阵

- 子进程不读 stdin -> call 在调用方 timeout 内失败，disconnect 仍在有限时间内回收。
- stdout EOF 但进程仍活着 -> connection status 为 `disconnected`，wrapper 调用抛连接错误。
- initialize 返回 JSON-RPC error 或非法协议 -> add 失败，公开结果只含稳定错误码，不含远端 message/env。
- disconnect 第一次失败 -> wrappers 已不可调用，client owner 保留；后续 remove/shutdown 可重试。
- shutdown 与 add 并发 -> add 回滚且 shutdown 等待完成；不得留下 wrapper 或活子进程。

### 5. Good / Base / Bad Cases

- Good：32 MiB 写入遇到 stdin 背压时按总 deadline 取消，关闭 waiter 不被取消，最终进程被 terminate/kill。
- Base：正常 server 收到 stdin EOF 后自行退出，stderr drain task 和 pipe 全部被等待。
- Bad：只给 `stdout.readline()` 加 timeout；`stdin.drain()` 或 `wait_closed()` 可永久挂住。
- Bad：`ToolResult(output={"error": str(exc)})` 把 server 回显的 token 交给模型。

### 6. 必需测试

- Client：背压 timeout 覆盖 send，关闭后 loop exception handler 为空，并在 `-W error::ResourceWarning` 下通过。
- Client：版本/capability、分页、ping、迟到 response、stdout EOF 和超长 stderr。
- Registry：shutdown/add 竞态、disconnect 失败重试、名称冲突与零合法工具回滚。
- 管理工具：成功与失败输出序列化后均不含 command、cwd、env value 或原始异常文本。

### 7. Wrong vs Correct

#### Wrong

```python
await writer.drain()  # timeout 尚未开始
response = await asyncio.wait_for(reader.readline(), timeout=timeout)
await asyncio.wait_for(writer.wait_closed(), timeout=0.2)  # 取消内部 waiter
return ToolResult(output={"error": str(exc)}, is_error=True)
```

#### Correct

```python
result = await asyncio.wait_for(call_under_io_lock(), timeout=timeout)
close_task = asyncio.create_task(writer.wait_closed())
await asyncio.wait_for(asyncio.shield(close_task), timeout=0.2)
# 公开边界只返回稳定分类；原始异常不进入模型或日志。
return ToolResult(output={"error": "添加 MCP server 失败", "code": code}, is_error=True)
```
