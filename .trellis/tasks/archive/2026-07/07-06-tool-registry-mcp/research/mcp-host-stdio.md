# 本地 stdio MCP Host 调研结论

## 结论

Amadeus 应迁移 Akashic 的 Host 边界，而不是原样复制其实现：`McpClient` 直接管理 stdio 子进程和 JSON-RPC，`McpToolWrapper` 把远端 MCP 工具适配为本地 Tool，`McpServerRegistry` 将 wrappers 注入统一 Registry。

本轮只实现 local stdio 和当前进程生命周期，不实现 HTTP、持久化、Hosted policy 或同 server dispatcher。

## 规范证据

- MCP 2025-06-18 transport：stdio 使用子进程 stdin/stdout，消息为 UTF-8 换行分隔 JSON-RPC。
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- Lifecycle：initialize 必须是首个交互，客户端随后发送 initialized；stdio 关闭顺序为 stdin EOF、等待、TERM、KILL。
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- Tools：tools/list 支持 cursor，tools/call 的 `isError` 与 JSON-RPC error 是不同错误层。
  - https://modelcontextprotocol.io/specification/2025-06-18/server/tools
- Pagination：client 应同时支持有 cursor 和无 cursor 的 list flow。
  - https://modelcontextprotocol.io/specification/2025-06-18/server/utilities/pagination
- Ping：任一方可发 ping，接收方必须返回空 result。
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/ping
- Cancellation：超时后发送方应发送 cancelled notification，但 initialize 不可取消。
  - https://modelcontextprotocol.io/specification/2025-06-18/basic/utilities/cancellation

## 参考实现

- Akashic `agent/mcp/client.py`：最小 stdio Host、握手、tools/list/call、stderr drain 和超时诊断。
- Akashic `agent/mcp/registry.py`：server 生命周期与 wrapper 注册。
- Akashic `proactive_v2/mcp_sources.py`：per-server lock，避免多个协程并发读取共享 stdout。
- MCP Python SDK v1.10.1：单 reader + response id map 支持真正并发，并使用安全环境白名单。本轮不引入其 dispatcher 复杂度。
  - https://github.com/modelcontextprotocol/python-sdk/blob/v1.10.1/src/mcp/client/stdio/__init__.py
  - https://github.com/modelcontextprotocol/python-sdk/blob/v1.10.1/src/mcp/shared/session.py

## Amadeus 实测

当前 transport 实现对同一 client 执行两个并发 call 时，一个调用成功，另一个抛出：

```text
RuntimeError: readuntil() called while another coroutine is already waiting for incoming data
```

因此 v1 使用覆盖完整 request/response 的 per-client lock。同一 server 串行，不同 server 可并行。当前 TurnWorker 和 Reasoner 原本逐 turn、逐 tool call await，因此该策略不会降低当前公开链路的吞吐。

聚焦基线为 47 tests passed；Windows warnings 中两个存活进程来自 registry 并行加载测试缺少 shutdown。所有子进程测试必须在 finally 中关闭，并用 `-W error::ResourceWarning` 验证。
