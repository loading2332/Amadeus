# 本地 MCP Host 技术设计

> 配套 `prd.md`。本设计只描述当前剩余的 MCP 垂直切片；已经完成的 ToolRegistry、ToolExecutor、deferred loading 和纯业务参数链路保持不变。

## 1. 第一性原理与边界

MCP 的 server 是协议角色，不要求位于远程机器。本轮 server 是由 Amadeus 启动的本地子进程；Host 内的 `McpClient` 通过 stdin/stdout 发送 JSON-RPC，`McpToolWrapper` 再把协议工具适配成 Amadeus `Tool`。

```text
Model
  -> mcp_add
  -> McpServerRegistry
       -> McpClient ---- newline JSON-RPC ----> local MCP process
       -> McpToolWrapper
       -> ToolRegistry
  -> tool_search/select
  -> ToolExecutor
  -> McpToolWrapper.execute
  -> McpClient.call
```

边界职责：

- `McpClient`：子进程、JSON-RPC、握手、分页、超时和关闭。
- `McpToolWrapper`：MCP result 到 `ToolResult` 的适配。
- `McpServerRegistry`：server 生命周期、批量注册和失败补偿。
- `manage_tools`：模型可调用的参数与结构化输出。
- `ToolRegistry`：统一工具来源、检索、可见性和执行入口。

## 2. 公共契约

```python
@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: object  # 保留坏 schema，供 Registry 按单工具跳过

@dataclass(frozen=True)
class McpCallResult:
    content: list[dict[str, Any]]
    structured_content: dict[str, Any] | None
    is_error: bool

@dataclass(frozen=True)
class McpServerConfig:
    name: str
    command: list[str]
    env: dict[str, str] | None = None
    cwd: str | None = None
```

`McpClient`：

```python
class McpClient:
    name: str
    tool_infos: list[McpToolInfo]
    is_alive: bool

    async def connect(self) -> list[McpToolInfo]: ...
    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> McpCallResult: ...
    async def disconnect(self) -> None: ...
```

`McpServerRegistry`：

```python
async def add(config: McpServerConfig) -> tuple[list[str], list[tuple[str, list[str]]]]
async def remove(name: str) -> list[str]
def list_servers() -> list[McpServerStatus]
async def shutdown() -> None
```

## 3. Client 数据流

### 3.1 Connect

1. 取得 client I/O lock，并拒绝重复 connect。
2. 使用安全环境白名单加显式 env，通过 `create_subprocess_exec(*command)` 启动进程。
3. 启动持有强引用的 stderr drain task。
4. 发送 initialize，校验 JSON-RPC result、协议版本 `2025-06-18` 和 server `tools` capability。
5. 发送 `notifications/initialized`。
6. 循环发送 `tools/list`，把 `nextCursor` 作为不透明字符串传回，直到缺失 cursor。
7. 只有完整成功后才发布 `tool_infos`；任一失败或 cancellation 都运行内部 cleanup。

### 3.2 Request/Response

- 所有请求使用单调递增整数 id。
- 一个 client 只有一个 stdout reader；I/O lock 覆盖完整 send/receive round trip。
- tool call timeout 从进入锁队列前开始，覆盖排队、send/drain 和 response；notification 或迟到响应不能重置期限。
- `_receive_response(expected_id)` 处理：
  - 匹配 response：返回。
  - 旧 response：记录并跳过。
  - notification：记录并继续；progress 不重置最大 timeout。
  - `ping` request：立即回复空 result 后继续等待。
  - 其他 server request：回复 `-32601 Method not found`。
  - 非法 JSON 或非法 JSON-RPC：协议错误，不把 server 的 stdout 日志伪装成成功。
- tool call 超时后在同一 lock 内尽力写 `notifications/cancelled`，然后抛 timeout；不重试、不关闭进程。

### 3.3 Disconnect

`disconnect()` 与 call 共用 I/O lock，因此 remove 会等待正在执行的调用。取得 lock 后：

1. 标记 closing。
2. 关闭 stdin，并在不取消 asyncio protocol close waiter 的前提下有限等待 writer closed。
3. 在宽限时间内等待 server 自行退出。
4. 未退出则 terminate，继续等待。
5. 仍未退出则 kill 并回收。
6. 取消并等待 stderr task，释放进程引用。

cleanup 对 cancellation 使用受保护的内部路径，避免 connect/shutdown 被取消后泄漏进程。

## 4. Adapter 与结果投影

命名为 `mcp_{server}__{tool}`。server alias 不得为空、包含 `__` 或 Provider 不允许的字符；生成后的 wrapper name 必须再次校验。远端名称不做自动替换或截断。

投影顺序：

1. 存在 `structuredContent`：`ToolResult.output` 使用该对象。
2. content 全为 text：按原顺序用换行拼接。
3. 混合 content：保留 text、resource link 和文本 resource；image/audio 只保留 type、mimeType 和 omitted 标记。
4. JSON-RPC、协议或连接错误转成本地执行异常；MCP `isError` 原样成为 `ToolResult.is_error`。

## 5. Registry 事务边界

### Add

```text
per-name lifecycle lock
-> 校验 config 与 alias
-> 拒绝已存在 server
-> client.connect
-> schema 校验并构造候选 wrappers
-> 预检查所有 wrapper 名称冲突
-> 注册合法 wrappers
-> 发布 client/tool_names
```

schema 错误只跳过单个工具。零合法工具、名称冲突或注册异常会注销本次已注册工具并断开 client。`_clients` 只保存完成 add 的实例，避免半成功状态被 `mcp_list` 观察到；若回滚关闭本身失败，Registry 仍保留内部清理句柄供 remove/shutdown 重试，但不把它发布到 list。

### Remove

```text
per-name lifecycle lock
-> 反查并注销 wrappers
-> client.disconnect（等待 I/O lock）
-> 删除内存 entry
```

未知 server 返回领域错误。server 自行退出或协议通道断开时 entry 保留，status 由 `client.is_alive` 动态投影为 `disconnected`。remove 关闭失败时 tools 已不可调用，client owner 继续保留供重试。

### Shutdown

先阻止新 add/remove，等待已经进入 connect 的 add 完成回滚，再对不同 server 并行执行内部 remove。关闭异常记录日志但继续清理其他 server；失败 client 的 owner 句柄保留到后续 shutdown 重试。

## 6. 管理工具

`mcp_add` schema：

```json
{
  "type": "object",
  "properties": {
    "name": {"type": "string"},
    "command": {"type": "array", "items": {"type": "string"}},
    "env": {"type": "object", "additionalProperties": {"type": "string"}},
    "cwd": {"type": "string"}
  },
  "required": ["name", "command"]
}
```

输出契约：

- add：`server/status/registered/skipped`。
- remove：`server/status/removed_tools`。
- list：`servers[{name,status,tools}]`。

失败输出使用 `invalid_request/connection_failed/protocol_error/timeout/not_found/internal_error` 等稳定错误码，不返回原始异常。输出、日志和 timeout 错误不包含 env；管理工具也不返回 command 或 cwd。

## 7. 装配与安全默认值

`RuntimeConfig.mcp_mode` 从 `AMADEUS_MCP_MODE` 读取。只有精确值 `local_trusted` 才启用，其余值统一为 `disabled`。

`disabled` 不创建 Registry，也不注册管理工具。`local_trusted` 创建进程内 `McpServerRegistry`，并把 add/remove/list 注册为 always-on；wrappers 以 deferred MCP 工具注册。`PassiveApp.aclose()` 在关闭数据库与 provider 前调用 registry shutdown。

子进程环境白名单参考官方 Python SDK：Windows 保留 PATH、PATHEXT、SYSTEMROOT、TEMP、USERPROFILE 等；POSIX 保留 HOME、LOGNAME、PATH、SHELL、TERM、USER。显式 env 覆盖白名单值。

## 8. 删除与兼容

删除 `transport.py`、`stdio_transport.py`、`http_transport.py`、`amadeus/db/mcp_servers.py`、未发布的 `20260707_0004_mcp_servers.py` 及对应测试。`McpToolInfo` 迁入 client module；`McpServerConfig` 收敛为 stdio-only。

不保留旧构造器、transport type、HTTP 参数、store 参数或后台重连接口。当前 migration 尚未进入 main，因此不新增补偿 migration。

## 9. 验证

- Client 单测：握手、版本拒绝、分页、ping、structured/isError、并发串行、timeout cancellation、迟到响应、graceful/forced shutdown。
- Registry 单测：部分 schema、零合法工具、冲突回滚、并发同名 add、remove 等待调用、crash 状态、并行 shutdown。
- Bootstrap 单测：disabled/local_trusted 两种装配。
- E2E：mcp_add -> tool_search/select -> wrapper call -> mcp_list -> mcp_remove。
- Windows 聚焦测试启用 `-W error::ResourceWarning`。
