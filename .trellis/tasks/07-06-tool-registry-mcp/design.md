# 技术设计：统一工具注册与 MCP 接入链路

> 配套 `prd.md`。本文件聚焦技术设计：模块边界、数据契约、数据流、数据结构、与现状的接缝。执行 checklist 见 `implement.md`。

## 0 · 决策表（grilling 16 项确认）

| 层 | 项 | 选择 |
|---|---|---|
| 基础设施 | HD1 hook 协议 | `HookOutcome(decision, updated_input, reason)` 三段式，去掉 `extra_message` |
| 基础设施 | HD2 Executor 与 Registry | `ToolExecutor(hooks, invoker)` invoker port 注入，Executor 不持有 Registry |
| 基础设施 | HD3 post hook | 不对称 + `fail_open=True`（post 只观察） |
| 基础设施 | HD4 preflight | 做，语义收紧"不调 invoker" |
| 应用 | TD1+TD5 检索 | `_documents` 第三表 + `KeywordSearchBackend`（CJK bigram） |
| 应用 | TD2 分组 | ToolMeta 加 `always_on` + `get_schemas(names)` 子集导出 |
| 应用 | TD3a 本轮集 | 抽出 `TurnVisibleSet` |
| 应用 | TD3b 跨轮缓存 | 抽出 `ToolDiscoveryState`（session LRU） |
| 应用 | TD4 闸门 | 未解锁也走 preflight |
| 意图 | ID1 | 做，定位 UI/trace，不防误调 |
| 意图 | ID2 字段名 | `purpose`（不撞已有 `intent`） |
| 意图 | ID3 pop 落点 | invoker 装配层硬编码 |
| 意图 | ID4 兼容分支 | 不做 |
| 意图 | ID5 长度 | 5-12 写 description 文本，无硬约束 |
| MCP | MD1 transport | stdio + Streamable HTTP 两种都做 |
| MCP | MD2 mcp_add | 模型可调 + 必做权限闸门 |
| MCP | MD3 持久化 | postgres 建表 + alembic |
| MCP | MD4 schema 校验 | 注册时轻校验 |
| MCP | MD5 权限闸门 | `authorized` 字段默认 true，留口子 |
| MCP | MD6 命名空间 | `mcp_{server}__{tool}` |
| MCP | MD7 进程生命周期 | stdio 抄 akashic 全细节，HTTP 用 httpx 自带 |

## 1 · 参考实现（file:line 实证）

现状基线（Amadeus）：
- `amadeus/tools/registry.py:10` `ToolRegistry` OrderedDict 薄壳
- `amadeus/tools/executor.py:16` `ToolExecutor` 持有 registry；hook 同步式；`:11` `ToolExecutionDenied`
- `amadeus/tools/hooks.py:17` `ReadOnlyFilesystemHook`（生产未装配）
- `amadeus/tools/base.py:8` `ToolExecutionRequest`、`:17` `ToolResult`、`:33` `Tool` Protocol、`:42` `ToolHook` Protocol
- `amadeus/runtime/passive.py:426-428` 全量 dump schema 入口；`:470-474` 透传给 reasoner
- `amadeus/runtime/reasoner.py:110` `_run_tool_loop`；`:171` batch snapshot；`:185` 逐个执行入口；`:297` 下一轮复用同一份 schemas
- `amadeus/runtime/tool_runtime.py:10` `tool_call_batch_snapshot`；`:21` `append_assistant_tool_calls`；`:46` `append_tool_result`
- `amadeus/runtime/lifecycle.py:47` `BeforeStepContext`；`:145` `before_step` emit；step gate 是 `early_stop_reply`
- `amadeus/runtime/step_phases.py:71` emit 后 ctx 回写 slot
- `amadeus/app/bootstrap.py:332-339` 现状装配：registry 静态注册 6 工具 + `ToolExecutor(registry=tool_registry)`（不传 hooks）；`:398-403` 追加注册 4 个 memory 工具
- `amadeus/tools/recall_memory.py:65` `intent` 字段已占用（约束 ID2 选项）
- `amadeus/memory/engine.py:40` memory 检索的 intent 语义
- `amadeus/events.py:24` `ToolCallStarted`、`:34` `ToolCallCompleted`、`:57` `EventBus`
- `tests/tools/test_tool_registry.py` 现有 happy-path 测试

akashic 可移植参考（`D:\coding\front-end_proj\akashic-agent`）：
- `agent/tools/registry.py:115` 三表 Registry；`:39` `_with_progress_description`；`:14-21` `_PROGRESS_DESCRIPTION_SCHEMA`
- `agent/tools/base.py:26` `Tool` ABC；`:8` `ToolResult`
- `agent/tools/search_backend.py:56` `KeywordSearchBackend`（CJK bigram）
- `agent/tool_hooks/executor.py:25` `ToolExecutor` 三段式
- `agent/tool_hooks/types.py:12` `ToolExecutionRequest`；`:36` `HookOutcome`；`:65` `ToolExecutionResult`
- `agent/mcp/client.py:35` `McpClient` stdio 实现
- `agent/mcp/registry.py:16` `McpServerRegistry`
- `agent/mcp/tool.py:9` `McpToolWrapper`
- `agent/mcp/manage_tools.py:9` `McpAddTool`

第三方对照（`D:\coding\front-end_proj\` 同级）：
- redrumY 分支（`telegram-bot codex/web-agent-architecture`）：精简两表 Registry + 只做 pre hook + 无 MCP + 无 deferred —— 仅作"edge case 简化形态"对照，不直接抄。

`httpx 0.28.1` 已在 `.venv` 里（fastapi/openai 传递依赖），MCP HTTP transport 直接用，不加 `pyproject.toml` 依赖。

## 2 · 模块边界与目录

新增/修改文件（全部 `amadeus/tools/` 与新增 `amadeus/mcp/`、`amadeus/tools/discovery/` 下）：

```
amadeus/tools/
  registry.py            改：三表结构 + get_schemas(names) + always_on/source_type/source_name
  base.py                改：HookOutcome / ToolHook 新协议 / ToolExecutionRequest(扩 source/session)
  executor.py            改：invoker port + 三段式 + preflight + fail_open post
  hooks.py               改：ReadOnlyFilesystemHook 适配 HookOutcome
  search/                新：
    __init__.py
    backend.py           KeywordSearchBackend（CJK bigram 加权 + why_matched）
    document.py          ToolDocument dataclass
  discovery/             新：
    __init__.py
    visible_set.py       TurnVisibleSet
    state.py             ToolDiscoveryState（session LRU）
    tool_search.py       ToolSearch 工具（always_on、select: 精确匹配）
amadeus/mcp/             新：
  __init__.py
  transport.py           McpTransport port
  stdio_transport.py     stdio 实现（抄 akashic client.py）
  http_transport.py      Streamable HTTP 实现（httpx）
  client.py              McpClient 协议层（initialize/tools/list/tools/call）
  registry.py            McpServerRegistry（add/remove/load_and_connect_all/shutdown）
  tool.py                McpToolWrapper
  manage_tools.py        McpAddTool / McpRemoveTool / McpListTool
  schema_validator.py    轻校验 OpenAI function schema 兼容性
amadeus/db/
  mcp_servers.py         新：mcp_servers 表 CRUD
  migrations/             新增 alembic migration：建 mcp_servers 表
amadeus/app/
  bootstrap.py           改：装配 ToolExecutor(hooks, invoker) + 注入 ReadOnlyFilesystemHook + 装配 McpServerRegistry + 后台 connect_all
amadeus/runtime/
  reasoner.py            改：① 取导出集改 always_on ∪ visible；③ 未解锁走 preflight + 引导回填；visible 状态从 TurnVisibleSet 取
```

## 3 · 数据契约

### 3.1 ToolMeta

```python
@dataclass(frozen=True)
class ToolMeta:
    risk: Literal["read-only", "write", "external-side-effect"] = "read-only"
    always_on: bool = False
    search_hint: str | None = None
    source_type: Literal["builtin", "mcp", "plugin"] = "builtin"
    source_name: str = ""
```

### 3.2 ToolDocument

```python
@dataclass(frozen=True)
class ToolDocument:
    name: str
    description: str
    risk: str
    always_on: bool
    search_hint: str | None
    source_type: str
    source_name: str
```

### 3.3 ToolRegistry（Rev 2）

内部三表：

```python
self._tools: dict[str, Tool] = {}
self._metadata: dict[str, ToolMeta] = {}
self._documents: dict[str, ToolDocument] = {}
self._backend: KeywordSearchBackend = KeywordSearchBackend()
```

签名：

```python
def register(self, tool: Tool, *, risk="read-only", always_on=False,
             search_hint=None, source_type="builtin", source_name="") -> None
def unregister(self, name: str) -> None   # 三表 + backend 同步移除
def get(self, name: str) -> Tool | None
def get_metadata(self, name: str) -> ToolMeta | None
def get_document(self, name: str) -> ToolDocument | None
def names(self) -> Iterable[str]
def get_registered_names() -> set[str]
def get_schemas(self, names: set[str] | None = None) -> list[dict]   # 每条经 _inject_purpose
def get_always_on_names() -> set[str]
def get_names_by_source(source_name: str) -> set[str]                # MCP 卸载反查
def get_documents() -> list[ToolDocument]
def search(self, query, *, top_k=5, allowed_risk=None, excluded_names=None) -> list[dict]
def execute(self, name, arguments) -> Awaitable[Any]                  # 注册的执行入口，invoker 的默认 provider
```

### 3.4 HookOutcome / ToolHook（Rev 2）

```python
@dataclass(frozen=True)
class HookOutcome:
    decision: Literal["pass", "deny"] = "pass"
    updated_input: dict[str, Any] | None = None
    reason: str = ""

class ToolHook(Protocol):
    name: str
    event: Literal["pre_tool_use", "post_tool_use", "post_tool_error"]
    def matches(self, ctx: HookContext) -> bool: ...
    async def run(self, ctx: HookContext) -> HookOutcome: ...

@dataclass(frozen=True)
class HookContext:
    event: HookEvent
    request: ToolExecutionRequest
    current_arguments: dict[str, Any]
    result: Any = ""     # post 时填
    error: str = ""      # post_tool_error 时填

@dataclass(frozen=True)
class HookTraceItem:
    hook_name: str
    event: HookEvent
    matched: bool
    decision: Literal["pass", "deny"] = "pass"
    reason: str = ""
```

`ToolExecutionRequest` 扩展（与 akashic 对齐）：

```python
@dataclass(frozen=True)
class ToolExecutionRequest:
    tool_name: str
    arguments: dict[str, Any]
    call_id: str = ""
    source: Literal["passive", "proactive", "subagent"] = "passive"
    session_key: str = ""
    tool_batch: tuple[dict, ...] = ()
    tool_batch_index: int = 0
```

### 3.5 ToolExecutionResult

```python
@dataclass(frozen=True)
class ToolExecutionResult:
    status: Literal["success", "denied", "error"]
    output: Any
    final_arguments: dict[str, Any]
    pre_hook_trace: list[HookTraceItem] = ()
    post_hook_trace: list[HookTraceItem] = ()
```

### 3.6 ToolExecutor（Rev 2）

```python
ToolInvoker = Callable[[str, dict[str, Any]], Awaitable[Any]]

@dataclass
class ToolExecutor:
    hooks: list[ToolHook]
    invoker: ToolInvoker

    async def execute(self, request: ToolExecutionRequest) -> ToolExecutionResult
    async def preflight(self, request: ToolExecutionRequest) -> ToolExecutionResult   # 不调 invoker
```

装配层：

```python
async def _invoker(name: str, args: dict) -> Any:
    args.pop("purpose", None)              # ID3：硬编码 pop
    return await tool_registry.execute(name, args)

tool_executor = ToolExecutor(
    hooks=[ReadOnlyFilesystemHook(workspace_root=config.workspace_root)],
    invoker=_invoker,
)
```

注意 Executor 不持有 Registry（HD2）；invoker 闭包持有，pop 在此。

### 3.7 TurnVisibleSet / ToolDiscoveryState

```python
class TurnVisibleSet:
    def __init__(self, always_on: set[str], discovery_state: ToolDiscoveryState) -> None
    def is_visible(self, name: str) -> bool
    def add_unlocked(self, name: str) -> None
    def visible_names(self) -> set[str]                    # = always_on ∪ 本轮已解锁
    def consume_unlock_targets(self, tool_search_result_text: str) -> list[str]
    # 内部解析 select: 前缀的工具名

class ToolDiscoveryState:                                   # session 级 LRU
    def __init__(self, capacity: int = 64) -> None
    def warm_up(self, visible_set: TurnVisibleSet) -> None # 新 turn 垫底
    def remember(self, name: str) -> None
    def __contains__(self, name: str) -> bool
```

LRU 容量 64 是 design 默认值，implement 阶段可调（akashic 实战用值待查，写代码时复用其默认即可；这是 ID5 之外另一个 design 留待 implement 微调的参数）。

### 3.8 意图字段注入

```python
_PURPOSE_FIELD = "purpose"
_PURPOSE_SCHEMA: dict[str, str] = {
    "type": "string",
    "description": (
        "用 5-12 个字说明这次工具调用的意图，只写给用户看的短语。"
        "不要复述工具名，不要粘贴长参数。例如：查看目录、读取配置、搜索健康数据。"
    ),
}
# 不设 minLength / maxLength。无兼容分支（ID4）。每个工具一律注入 + required。

def _inject_purpose(schema: dict) -> dict
def _pop_purpose(args: dict) -> dict     # 在 invoker 装配处调用，见 3.6
```

### 3.9 MCP Transport port

```python
class McpTransport(Protocol):
    async def connect(self) -> list[McpToolInfo]    # 返回远端工具元信息列表
    async def call(self, tool_name: str, arguments: dict, *, timeout: float) -> str
    async def disconnect(self) -> None
    @property
    def is_alive(self) -> bool

@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict
```

### 3.10 McpToolWrapper

```python
class McpToolWrapper:    # 实现 Tool 协议
    def __init__(self, client: McpClient, info: McpToolInfo, server_name: str) -> None
    @property
    def name(self) -> str:           # f"mcp_{server}__{info.name}"
    @property
    def description(self) -> str:    # f"[MCP:{server}] {info.description}"
    @property
    def parameters(self) -> dict:    # info.input_schema（轻校验通过后透传）
    async def execute(self, **kwargs) -> Any
```

### 3.11 McpServerRegistry

```python
class McpServerRegistry:
    def __init__(self, db: McpServersStore, tool_registry: ToolRegistry) -> None
    async def add(self, name: str, *, transport_type: Literal["stdio","http"],
                  command: list[str] | None = None, url: str | None = None,
                  env: dict | None = None, cwd: str | None = None) -> list[str]   # 返回注册的工具名
    async def remove(self, name: str) -> None
    async def load_and_connect_all(self) -> None
    def start_connect_all_background(self) -> asyncio.Task
    async def shutdown(self) -> None
```

### 3.12 mcp_servers 表

```sql
CREATE TABLE mcp_servers (
    name            TEXT PRIMARY KEY,
    transport_type  TEXT NOT NULL,        -- 'stdio' | 'http'
    command         JSONB,                 -- stdio: ["npx","-y","mcp-server-xxx"]
    url             TEXT,                  -- http
    env             JSONB,
    cwd             TEXT,
    authorized      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 4 · 数据流

### 4.1 一轮工具调用全链路（改造后）

```
PassiveRuntime.run_turn
 ▷ Reasoner.reason(tool_schemas=<later>)
   ▷ _run_tool_loop:
     iteration loop:
       ① 导出工具集
         visible_names = turn_visible_set.visible_names()
         schemas = registry.get_schemas(names=visible_names ∪ always_on)
         # 注意：上轮解锁的工具这轮已进 visible set，自动可见
         provider.chat(messages, tools=schemas)
       ② response.tool_calls
       ③ for tool_call in tool_calls:
            if not turn_visible_set.is_visible(tool_call.name):
                # 未解锁 → preflight + 引导回填
                pre = await tool_executor.preflight(
                        ToolExecutionRequest(tool_name=..., arguments=..., source="passive",
                                             tool_batch=..., tool_batch_index=i))
                if pre.status == "denied":
                    append_tool_result(messages, tool_call.id, pre.output)   # hook 给的 reason
                else:
                    append_tool_result(messages, tool_call.id,
                        f"工具 '{tool_call.name}' 当前未加载（schema 不可见）。请先调用 "
                        f"tool_search(query=\"select:{tool_call.name}\") 加载，然后再调用该工具。")
                continue
            # 已解锁 → 正常执行
            emit ToolCallStarted
            exec_result = await tool_executor.execute(
                            ToolExecutionRequest(tool_name=..., arguments=...,
                                                 source="passive", tool_batch=..., tool_batch_index=i))
            # exec_result.final_arguments 已 pop purpose；invoker 内部已完成
            emit ToolCallCompleted
            append_tool_result(messages, tool_call.id, exec_result.output)
            tool_chain.append({...final_arguments, pre_hook_trace, post_hook_trace, status...})
            if tool_call.name == "tool_search":
                unlocked = turn_visible_set.consume_unlock_targets(exec_result.output_as_text)
                for n in unlocked: discovery_state.remember(n)
       ④ provider.chat(messages, tools=schemas)  # 下一轮，visible 可能扩张
```

### 4.2 ToolExecutor.execute 内部三段式

```
execute(request):
  current_args = dict(request.arguments)
  pre_trace, post_trace = [], []
  extra_messages = []   # 不暴露给调用方，仅 trace

  # 4a pre hooks
  for hook in hooks if hook.event == "pre_tool_use":
    if not hook.matches(ctx): pre_trace.append(matched=False); continue
    outcome = await hook.run(ctx)
    if outcome.updated_input is not None: current_args = dict(outcome.updated_input)
    pre_trace.append(matched=True, decision=outcome.decision, reason=outcome.reason)
    if outcome.decision == "deny":
      return ToolExecutionResult(status="denied", output=outcome.reason,
                                 final_arguments=current_args, pre_hook_trace=pre_trace)

  # 4b invoker（pop purpose 在这一层之前由 invoker 内部完成）
  try:
    output = await invoker(request.tool_name, current_args)
  except Exception as e:
    # 4c-err post_tool_error（不 fail_open）
    await _run_post_hooks("post_tool_error", ctx_with_error=e, trace=post_trace, fail_open=False)
    return ToolExecutionResult(status="error", output=f"工具执行出错: {e}",
                               final_arguments=current_args, traces...)

  # 4c-ok post_tool_use（fail_open=True）
  await _run_post_hooks("post_tool_use", ctx_with_result=output, trace=post_trace, fail_open=True)
  return ToolExecutionResult(status="success", output=output, final_arguments=current_args, traces=...)

preflight(request):
  # 同 4a，不进 4b/4c
  return deny or pass only trace
```

### 4.3 MCP server 加载与工具注入

```
McpServerRegistry.add(name="github", transport_type="stdio", command=[...], env=...):
  1. db.upsert(name, transport_type, command, env, cwd, authorized=True)
  2. transport = stdio if stdio else http
  3. client = McpClient(name, transport)
     tool_infos = await client.connect(timeout=8s)
     # stdio: create_subprocess_exec → initialize → notifications/initialized → tools/list
     # http:   POST initialize → 拿 Mcp-Session-Id → POST tools/list
  4. for info in tool_infos:
       errors = validate_openai_function_schema(info.input_schema)
       if errors: skipped.append((info.name, errors)); continue
       wrapper = McpToolWrapper(client, info, server_name=name)
       tool_registry.register(wrapper, risk="external-side-effect",
                              source_type="mcp", source_name=name)
       # 三表 + backend 同步登记 → tool_search 能搜到
  5. return [registered names] + skipped info
```

```
服务启动（bootstrap）:
  mcp_db = McpServersStore(postgres_db)
  mcp_registry = McpServerRegistry(db=mcp_db, tool_registry=tool_registry)
  mcp_registry.start_connect_all_background()   # 不阻塞主服务启动
  # 失败的 server 后台记日志，不阻断启动
```

### 4.4 意图字段流

```
schema 导出 (R4.1, R4.2):
  registry.get_schemas(names) → for each tool: _inject_purpose(to_schema(tool))
    → properties["purpose"] = _PURPOSE_SCHEMA copy
    → required.append("purpose")

模型调用：arguments 含 "purpose": "替换硬编码值", ...

invoker 执行 (R4.5):
  args.pop("purpose", None)   # 硬编码
  await registry.execute(name, args)
    → tool.execute(**clean kwargs)

trace 记录：final_arguments 已不含 purpose（已 pop）
  如需 trace 看到原始 purpose，在 reasoner 处补一份 raw_arguments 记录
```

## 5 · 与现状的接缝与迁移

### 5.1不动**：`amadeus/runtime/tool_runtime.py` 的三个纯函数（`tool_call_batch_snapshot` / `append_assistant_tool_calls` / `append_tool_result`）—— 不依赖 hook 协议，继续用。
2. **不动**：`amadeus/runtime/lifecycle.py` 的 phase gate（`BeforeStep/AfterStep` 的 `early_stop_reply`）—— 与 hook 协议正交，不做改动。
3. **不动**：`events.py` 的 `ToolCallStarted/Completed` 和 EventBus。
4. **改**：`amadeus/runtime/reasoner.py` 的 `_run_tool_loop`：导出集改用 `TurnVisibleSet`；插入"未解锁 → preflight + 引导回填"；保留 `repeat_history` 重复签名守卫和 `max_tool_iterations`。
5. **改**：`amadeus/app/bootstrap.py:332-339` 装配：从 `ToolExecutor(registry=...)` 改为 `ToolExecutor(hooks=[ReadOnlyFilesystemHook(...)], invoker=_invoker)`；注册工具改为带元数据（`source_type="builtin"`、按工具语义标的 `risk`、`always_on` for `tool_search`）。
6. **改**：`amadeus/tools/hooks.py` `ReadOnlyFilesystemHook` 适配新 `ToolHook` Protocol（`name`/`event`/`matches`/`run`），返回 `HookOutcome`。
7. **改**：`amadeus/tools/base.py` 的 `ToolHook` Protocol 与 `ToolExecutionRequest`/`ToolResult`/`ToolTrace` 调整。
8. **改**：`tests/tools/test_tool_registry.py` / `tests/tools/test_tool_executor.py` 适配新 API。

### 5.2 Hook 调用点迁移

旧调用点（`executor.py:20` 同步 `execute`、`:78` 异步 `execute_async`）签名都变。调用者：

- `reasoner.py:197` `execute_async` 调用点改 `execute(request)`（传 `ToolExecutionRequest`）。
- 任何插件直接调 executor 的（grep 确认）。

不在本轮做"big-bang 重写所有调用点"——`execute_async` 保留为薄壳转发到新 `execute(request)`，给插件/测试一个迁移过渡。验收 A6 既有测试通过这条约束兜底。

### 5.3 PluginContext / Plugin 注册工具的能力

`amadeus/plugin/context.py:20` 的 `PluginContext.tool_registry` 已存在，但 `Plugin` 基类未约定工具贡献接口。本轮**不扩展 plugin 注册工具能力**——MCP 才是本轮的外部工具来源，plugin 暂不补工具贡献。PRD 没列这条为需求，design 也不展开。

## 6 · MCP 实现细节

### 6.1 stdio transport（抄 akashic `client.py`）

- `asyncio.create_subprocess_exec(command[0], *command[1:], env=env, cwd=cwd, stdin=PIPE, stdout=PIPE, stderr=PIPE)`
- `_STREAM_LIMIT = 4 * 1024 * 1024` 防 StreamReader 行限
- `connect()`：`asyncio.wait_for(_connect_impl, timeout=8)`；`_connect_impl`：发 `initialize`（`protocolVersion: "2025-06-18"`，`capabilities: {}`）→ 等 init 响应 → 发 `notifications/initialized`（无响应）→ 发 `tools/list` → 解析 `McpToolInfo[]`
- `call(tool_name, arguments, timeout)`：`tools/call` JSON-RPC；error 返回 `"MCP error (...)"` 字符串不抛
- `_recv(expected_id, stage, timeout)`：按 `id` 匹配响应；跳过 notification；超时构造 `recent_stdout`/`recent_stderr` 尾 8 行诊断
- `_drain_stderr()`：后台 task 持续读 stderr
- `disconnect()`：`terminate()` → 5s 等 → `kill()`

### 6.2 Streamable HTTP transport（按 MCP 2025-06-18 规范自写，httpx）

> 规范来源：`https://modelcontextprotocol.io/specification/2025-06-18/basic/transports`。
> 现规范只有两种 transport：`stdio` 与 `Streamable HTTP`；旧 HTTP+SSE（2024-11-05）已 deprecated，**本轮不做兼容**（决策已拍）。

- 用 `httpx.AsyncClient`，每 server 持有独立 client（连接池 size=1，长复用）
- 统一单 MCP endpoint URL（POST + GET 同路径，如 `https://example.com/mcp`）
- **协议版本 header**：所有后续请求带 `MCP-Protocol-Version: 2025-06-18`（决策已拍）
- **initialize**：POST server endpoint，body 为 initialize JSON-RPC 请求
  - 请求带 `Accept: application/json, text/event-stream`
  - 响应若是单 JSON：解析 `InitializeResult`；响应若是 SSE：开流等响应事件解析 `InitializeResult`
  - 响应 header 含 `Mcp-Session-Id` 时记录该值（规范：server **MAY** 分配，**MUST** 含可见 ASCII 0x21-0x7E）
- **后续请求**：所有 POST / GET / DELETE 都带 `Mcp-Session-Id: <id>` header（若 server 分配了）
- **notifications/initialized**：POST notification，server 返回 202 Accepted 无 body
- **tools/list**：POST JSON-RPC request，带 `Accept: application/json, text/event-stream`
  - 规范要求**客户端 MUST 同时支持两种响应**：`Content-Type: application/json`（单 JSON 响应）与 `Content-Type: text/event-stream`（SSE 流响应）。**两种都必须解析**，按响应 content-type 分发，不是"先试 JSON 再 fallback SSE"的顺序逻辑。
  - SSE 流响应解析：标准 SSE 帧（`event:` 行 / `data:` 行 / 空行分隔），从 data 行提取 JSON-RPC message；server **SHOULD** 在发的 response 之后关闭流，客户端读到关闭即结束
- **tools/call**：POST JSON-RPC request，同样 MUST 支持两种响应 content-type；error 归一为 `"MCP error (HTTP <code>): <message>"` 字符串不抛
- **GET endpoint**（可选，本轮不做）：规范允许 GET 开 SSE 流接收 server 主动 message。本轮 Amadeus 不发 GET（不需要 server 主动通知），遇 server 405 Method Not Allowed 直接忽略
- **Resumability**（可选，本轮不做）：SSE event 的 `id` 字段 + `Last-Event-ID` header 续传。本轮不实现 resumability，遇断流直接当错误
- **DELETE**（关 session）：`disconnect()` 时发 DELETE 带本session id；server 返回 405 Method Not Allowed 则忽略（规范允许 server 不支持关 session）
- 超时：`httpx` 自带 connect/read timeout + 全局 `asyncio.wait_for`（默认 30s，可配）
- 错误模型：
  - HTTP 4xx/5xx → 解析响应体 MCP error JSON → 返回 `"MCP error (HTTP <code>): <message>"` 字符串
  - HTTP 404 + 含 `Mcp-Session-Id` 请求 → 规范要求客户端发起新 initialize（本轮记日志不自动重连，下次 call 抛错给 ToolExecutor 当 `post_tool_error` 处理）
- 不做心跳 / 自动重连（与 stdio 一致）

### 6.3 schema 轻校验（`mcp/schema_validator.py`）

```python
def validate_openai_function_schema(input_schema: dict) -> list[str]:
    errors = []
    if input_schema.get("type") not in {"object", None, ""}:
        # OpenAI function 期望 object；空也容忍（参数为空）
        errors.append(f"type 应为 object，实际 {input_schema.get('type')!r}")
    if "$ref" in input_schema:
        errors.append("OpenAI function calling 不支持 $ref，请内联")
    if "$schema" in input_schema and "/" not in str(input_schema["$schema"]):
        # 允许 $schema meta 关键字，不做 URI 形态校验
        pass
    props = input_schema.get("properties")
    if props is not None and not isinstance(props, dict):
        errors.append("properties 应为 object")
    # 不做完整 JSON Schema 校验，挡大错放过边缘
    return errors
```

### 6.4 mcp_add / mcp_remove / mcp_list 工具

```python
class McpAddTool:    # 实现 Tool 协议，注册进 Registry，模型可调
    name = "mcp_add"
    parameters = {"type":"object",
                  "properties":{"name":{"type":"string"},
                                "transport_type":{"type":"string","enum":["stdio","http"]},
                                "command":{"type":"array","items":{"type":"string"}},
                                "url":{"type":"string"},
                                "env":{"type":"object"}},
                  "required":["name","transport_type"]}
    async def execute(self, **kwargs) -> str:
        # 转调 mcp_server_registry.add(...)
        # 返回"已注册工具：...；跳过：..."字符串

class McpRemoveTool: ...
class McpListTool: ...
```

这些工具注册时 `source_type="builtin"`、`always_on=True`（让模型总能管理 server）。

### 6.5 McpToolWrapper 的 risk 与可见性

MCP 工具注册时 `risk="external-side-effect"`、`source_type="mcp"`、`always_on=False` → 进 deferred 集，必须经 `tool_search` 解锁才能调。`authorized=True`（MD5 默认）下不加额外闸门——解锁即授权。`authorized=False`（未来档位）下，`tool_search` 解锁时检查并 deny，回填"此 MCP server 需要用户授权"——本轮 `authorized` 默认 true，该路径不触发但字段在位。

## 7 · 测试设计

### 7.1 单元

- `tests/tools/test_registry_rev2.py`：三表同步、`get_schemas(names)` 子集、`get_names_by_source` 反查、`search` 关键词命中 + `why_matched`、`always_on` 过滤。
- `tests/tools/test_executor_rev2.py`：pre hook 改参不 deny / deny 不改参 / 两者同时；post hook fail_open；preflight 不调 invoker；invoker port 注入可单测。
- `tests/tools/test_purpose_inject.py`：所有工具 schema 含 purpose + required；purpose 无 maxLength；invoker pop 后工具不被传 purpose；recall_memory 的 intent 字段不被注入。
- `tests/tools/test_hook_adapt.py`：`ReadOnlyFilesystemHook` 走新协议、写工具 path 越界 deny 带 reason。
- `tests/tools/discovery/test_visible_set.py` / `test_discovery_state.py`：LRU、warm_up、consume_unlock_targets。
- `tests/mcp/test_schema_validator.py`：`$ref` 被挡、`type` 不合法被挡。
- `tests/mcp/test_mcp_tool_wrapper.py`：命名 `mcp_{server}__{tool}`、可逆解析。
- `tests/mcp/test_transports.py`：stdio transport 用 mock 子进程（提供假 server 脚本）；http transport 用 `httpx.MockTransport` 或本地 ASGI 假 server。

### 7.2 集成

- `tests/integration/test_tool_loop_deferred.py`：模型先调 tool_search → 解锁 → 调用 → 结果回写，完整 4 步链路。
- `tests/integration/test_mcp_end_to_end.py`：启动一个假的 MCP server 子进程，mcp_add 加进来 → tool_search 找到工具 → 解锁 → 调用 → 拿到远端返回。

## 8 · 兼容与回退

- 旧 `ToolExecutor.execute(tool_name, arguments, ...)` 与 `execute_async(...)` 保留为薄壳转发到新 `execute(request: ToolExecutionRequest)`，过渡期允许插件不改。
- 旧 `ToolHook` Protocol（`before_execute/after_execute`）若在插件中存在调用，给一个适配器包成新 `ToolHook`——grep 确认范围后决定是否做适配器 or 直接改调用点。
- alembic migration 提供 down migration（drop `mcp_servers` 表）。
- MCP 接入失败（连接超时、schema 全部不合法）不应阻断主服务启动——`start_connect_all_background` 内部 catch，记日志，继续。

## 9 · 风险与待查

| 风险 | 说明 | 处理 |
|---|---|---|
| Streamable HTTP 实现复杂度 | MCP 规范要求客户端 **MUST** 同时支持 `application/json` 与 `text/event-stream` 两种响应；SSE 帧解析不是可选 | 按 MCP 2025-06-18 规范，HTTP transport 本轮必须实现 SSE 帧解析；用标准 SSE 帧格式（`event:` / `data:` / 空行）；GET 与 Resumability 这两个可选能力本轮不做 |
| httpx 长连接稳定性 | httpx AsyncClient 在长会话下的连接复用、超时行为 | 每 server 持有独立 `httpx.AsyncClient`，连接池 size=1；超时 30s 可配 |
| MCP server schema 与 OpenAI 不兼容 | `$ref` 等被挡 | MD4 轻校验直接拒绝注册 + 错误列表回 `mcp_add` 模型可见 |
| 模型误用 mcp_add 加危险 server | MD2 模型可调权限闸门 | 本轮 `authorized` 默认 true 无闸门；生产部署若需限制，未来通过把 `authorized` 默认改 false + 加确认路径实施 |
| reasoner 改动面 | `_run_tool_loop` 是核心循环，改动有回归风险 | 保留重复签名守卫 + max_iterations；新逻辑（visible 判断、preflight）增量加，不动旧逻辑语句；A6 验收既有测试通过 |
| ToolDiscoveryState LRU 容量 | 64 是默认猜测 | implement 阶段实测调整 |

## 10 · 文档与命名总结

- 字段名 `purpose`（与 akashic `description` 不一致，ID2 决策的代价）。
- Tool 名 `mcp_add` / `mcp_remove` / `mcp_list` / `tool_search`（always_on 工具）。
- MCP 工具命名 `mcp_{server}__{tool}`。
- 文档全部中文（PRD/design/implement）。