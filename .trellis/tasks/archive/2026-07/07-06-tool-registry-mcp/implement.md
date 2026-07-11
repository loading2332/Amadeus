# 本地 MCP Host 实施计划

## 当前基线

- [x] ToolRegistry 三表结构、来源元数据和执行入口。
- [x] ToolExecutor invoker port、HookOutcome 与 preflight。
- [x] Provider/Runtime/历史纯业务参数契约。
- [x] tool_search、TurnVisibleSet 和 session discovery state。
- [x] 旧 transport abstraction、Streamable HTTP 和 PostgreSQL MCP 持久化已删除。

## P1：任务制品

- [x] 更新 PRD、design 和 implement，锁定 local stdio 最小切片。
- [x] 记录 MCP 官方规范、Akashic、官方 SDK 和 Amadeus 并发基线研究。

## P2：Direct stdio McpClient

- [x] 将 `McpToolInfo`、`McpCallResult` 和完整 stdio 生命周期收敛到 `amadeus/mcp/client.py`。
- [x] 实现安全 env、唯一 id、I/O lock、initialize/version/capability、分页 tools/list 和 ping response。
- [x] 实现 tools/call result 解析、timeout cancellation、迟到 response 跳过和规范 shutdown。
- [x] 删除 transport、stdio transport 和 HTTP transport。

验证：

```powershell
.venv\Scripts\python.exe -m pytest tests/mcp/test_mcp_client.py -q -W error::ResourceWarning
```

## P3：Wrapper 与 Registry

- [x] `McpToolWrapper` 消费 `McpCallResult`，实现 structured/text/非文本投影和真实 `is_error`。
- [x] 收敛 `McpServerConfig` 为 name/command/env/cwd。
- [x] 重写 `McpServerRegistry`：per-name lock、部分 schema、名称冲突预检、失败补偿、graceful remove、动态 status、并行 shutdown。
- [x] `mcp_add/remove/list` 使用 stdio-only schema、稳定错误码和结构化输出。

验证：

```powershell
.venv\Scripts\python.exe -m pytest tests/mcp/test_mcp_tool_wrapper.py tests/mcp/test_mcp_server_registry.py tests/mcp/test_manage_tools.py -q
```

## P4：装配与删除持久化

- [x] `RuntimeConfig` 新增 `mcp_mode`，默认/非法 disabled，仅 local_trusted 装配 MCP。
- [x] local_trusted 下注册三个 always-on 管理工具，wrapper 保持 deferred。
- [x] `PassiveApp.aclose()` 关闭 MCP；启动阶段不再后台恢复。
- [x] 删除 MCP DB store、0004 migration、DB tests 和 bootstrap store 引用。
- [x] 更新 package exports 与所有旧构造调用点，确认生产代码 HTTP/transport/persistence 零引用。

验证：

```powershell
.venv\Scripts\python.exe -m pytest tests/app/test_bootstrap_tool_runtime.py tests/app/test_bootstrap.py -q
rg -n "McpTransport|StreamableHttp|transport_type|load_all_from_db|mcp_servers" amadeus migrations
```

## P5：端到端与回归

- [x] fake stdio server 支持分页、ping、structured error、延迟响应、背压和 graceful/forced shutdown。
- [x] E2E 覆盖 add -> search/select -> call -> list -> remove。
- [x] 并发测试证明同 server 不会并发读取 stdout；不同 registry 生命周期无半成功泄漏。
- [x] 所有启动子进程的测试在 finally 中 shutdown。

验证：

```powershell
.venv\Scripts\python.exe -m pytest tests/mcp tests/integration/test_mcp_end_to_end.py -q -W error::ResourceWarning
.venv\Scripts\ruff.exe check amadeus/mcp amadeus/app/bootstrap.py tests/mcp tests/integration/test_mcp_end_to_end.py
.venv\Scripts\mypy.exe --follow-imports=skip amadeus/mcp amadeus/app/bootstrap.py
.venv\Scripts\python.exe -m pytest tests -q
```

## 完成标准

- 聚焦 MCP 与集成测试通过且无 Windows ResourceWarning。
- Ruff 与 Mypy 对修改范围通过。
- 全量测试无本任务引入的回归。
- HTTP transport、MCP 持久化和后台重连不再出现在生产代码或当前测试。

## 验证结果（2026-07-11）

- MCP + E2E 严格资源门禁：`71 passed`。
- 全量测试：`432 passed, 79 skipped`；skip 为当前环境未提供 PostgreSQL 等既有条件。
- 修改范围 Ruff：通过。
- `mypy --follow-imports=skip amadeus/mcp amadeus/app/bootstrap.py`：通过。
- 生产代码旧 MCP transport/HTTP/DB 恢复符号检索：零命中。
- 仓库级 Ruff 仍有 `.claude/.trellis` 既有 104 项；默认依赖跟随的 Mypy 仍有 evaluation 既有 15 项，均不在本任务修改范围。
