# 统一工具注册与本地 MCP Host 接入

## 目标

Amadeus 已完成统一 `ToolRegistry`、`ToolExecutor`、按需工具发现和纯业务参数链路。本轮剩余目标是增加一条可运行的本地 MCP Host 垂直切片：模型通过 `mcp_add` 启动本地 stdio MCP server，Host 获取远端工具列表，将每个工具包装为 `McpToolWrapper` 并注入现有 `ToolRegistry`，随后沿既有 `tool_search -> select -> execute` 链路调用。

核心链路：

```text
mcp_add(name, command, env?, cwd?)
-> McpServerRegistry.add
-> McpClient 启动 stdio 子进程
-> initialize / notifications/initialized / tools/list
-> McpToolWrapper
-> ToolRegistry.register(source_type="mcp")
-> tool_search 解锁
-> tools/call
```

## 已有能力

- `ToolRegistry` 已维护工具实现、元数据和检索文档，并支持按来源反查。
- `ToolExecutor` 已通过 invoker port 执行工具，并提供结构化 hook 结果。
- `tool_search`、`TurnVisibleSet` 和 session 级 discovery state 已支持 deferred 工具解锁。
- Provider、Runtime、事件和历史统一传播平铺业务参数。

这些能力保持现状，本轮不重新设计。

## 需求

### R1：stdio MCP Client

- `McpClient(name, command, env=None, cwd=None)` 直接拥有子进程和 JSON-RPC 通信，不再依赖 `McpTransport`。
- 只支持 MCP `2025-06-18` 和本地 stdio；每条 UTF-8 JSON-RPC 消息以换行分隔。
- `connect()` 完成 initialize、版本与 tools capability 校验、initialized 通知及分页 `tools/list`。
- `call()` 使用唯一递增 request id，返回保留 `content`、`structuredContent`、`isError` 的 `McpCallResult`。
- client 必须响应 server 发起的 `ping`；其他未协商的 server request 返回 JSON-RPC method-not-found。
- 单个 client 的 connect/call/disconnect 使用同一 I/O lock，同一 server 串行、不同 server 可并行。
- connect 总超时为 8 秒，tool call 默认超时为 30 秒；tool call 超时不重试，尽力发送 cancellation，并允许后续请求跳过迟到响应。
- shutdown 顺序为关闭 stdin、等待退出、terminate、kill；所有后台 stderr task 和 pipe 必须被回收。

### R2：MCP Tool Adapter

- `McpToolWrapper` 命名为 `mcp_{server}__{remote_tool}`，description 带 `[MCP:{server}]` 前缀，parameters 使用已校验的远端 input schema。
- server alias 只允许字母、数字、`_`、`-`，且不得包含 `__`；生成后的完整工具名必须符合 Provider function-name 约束。
- wrapper 将 `McpCallResult` 转为 `ToolResult`：优先使用 structured content；纯文本 block 按换行拼接；非文本 block 转为受控 JSON-safe 摘要，不把 image/audio base64 注入模型上下文。
- MCP `result.isError` 原样映射到 `ToolResult.is_error`；JSON-RPC、协议或连接错误抛给 `ToolExecutor` 归一，禁止依赖字符串前缀猜测。

### R3：Server Registry

- `McpServerRegistry` 只维护当前进程内的 client、server 工具名和清理状态，不做数据库持久化，也不长期保存 command、env 或 cwd。
- `add()` 对同名 server 使用生命周期锁；重复名称返回错误。
- schema 不兼容的工具进入 `skipped`，其余工具可注册；若没有任何合法工具则 add 失败并关闭子进程。
- 任一 wrapper 名称冲突时整体失败；注册过程异常必须注销本次已注册工具并关闭子进程。
- `remove()` 先从 `ToolRegistry` 注销 wrappers，再等待当前调用释放 I/O lock并关闭 client。
- server 崩溃后 wrappers 暂时保留，`mcp_list` 显示 `disconnected`；本轮通过 remove/add 显式恢复，不做健康监控或自动重连。
- `shutdown()` 并行关闭不同 server，并保证测试和应用退出时没有遗留子进程。

### R4：模型管理工具与装配

- `mcp_add`、`mcp_remove`、`mcp_list` 三者都作为 always-on 模型工具注册。
- `mcp_add` 参数固定为 `name`、`command`、可选 `env`、可选 `cwd`；不包含 transport type、URL 或 HTTP headers。
- 三个管理工具返回结构化 `ToolResult`，不得返回 command、cwd 或 env。
- 新增 `AMADEUS_MCP_MODE`：默认和非法值均视为 `disabled`；只有 `local_trusted` 时才创建 MCP Host 并注册管理工具。
- MCP wrappers 注册为 `always_on=False`、`risk="external-side-effect"`、`source_type="mcp"`、`source_name=<server>`。
- 子进程默认只继承运行必需环境变量白名单，再叠加 `mcp_add.env`；env 值不得进入日志或管理工具输出。

## 验收标准

- [x] `mcp_add` 可启动真实假 stdio server，并把其工具注入 `ToolRegistry`。
- [x] 注入工具能被 `tool_search` 找到，经 `select:` 解锁后完成真实 `tools/call`。
- [x] `McpClient.call()` 保留 structured content 和 `isError`，wrapper 正确映射 `ToolResult`。
- [x] 同一 client 并发调用不会触发并发读取 `StreamReader`，且响应不会串线。
- [x] 分页 tools/list、交错 ping、迟到响应、超时 cancellation 均有测试。
- [x] schema 部分失败可返回 registered/skipped；名称冲突和零合法工具会完整回滚。
- [x] `mcp_remove` 注销工具并关闭进程；`mcp_list` 返回结构化状态且不泄露配置。
- [x] `disabled` 模式不装配 MCP；`local_trusted` 模式成套注册三个管理工具。
- [x] Windows 聚焦测试在 `-W error::ResourceWarning` 下无子进程或 pipe 泄漏。

## 约束

- 使用 Python 3.11 标准库 `asyncio`，不引入 MCP SDK 或新运行时依赖。
- Akashic 只作为 Host 边界和生命周期参考，不复制静态字符串错误、结果扁平化或不完整并发语义。
- 保留现有 schema 轻校验器及 ToolRegistry/ToolExecutor/deferred 数据流。
- 文档和面向用户的错误信息使用中文；协议 method 和字段名保持 MCP 原文。

## 不在范围内

- Streamable HTTP、远程 MCP transport 或自定义 transport。
- PostgreSQL/file 配置持久化、启动恢复、后台重连或 CLI 管理面。
- Hosted 多租户策略、认证控制面、sandbox/container、网络出口策略和 Secret Provider。
- 同一 server 的多请求 dispatcher、自动健康检查、自动重连和动态 `tools/list_changed` 刷新。
- MCP resources、prompts、sampling、elicitation 和多模态 Provider 消息。
