# 执行计划：统一工具注册与 MCP 接入链路

> 配套 `prd.md`（需求/验收）与 `design.md`（技术设计/数据契约/数据流）。本文件是有序执行 checklist、validation 命令、review gates、rollback points。文档全部中文。

## 执行顺序原则

按依赖链自底向上：**基础设施（HD）→ 应用层（TD）→ 意图（ID）→ MCP（MD）→ 集成与验收** 每个阶段后跑 validation，过 review gate 再进下一阶段。

---

## P0 · 准备

- [ ] P0.1 `git status` 确认工作树干净（当前分支 `codex/delivery-runtime`）；为本任务新建工作分支或沿用按团队惯例（`codex/tool-registry-mcp`）。**注意：仅切分支，不提前 commit。**
- [ ] P0.2 `python ./.trellis/scripts/task.py current` 确认当前任务指向 `07-06-tool-registry-mcp`。
- [ ] P0.3 确认 `httpx 0.28.1` 在 `.venv` 可用（已查证：fastapi/openai 传递依赖，无需改 `pyproject.toml`）。
- [ ] P0.4 确认 `alembic` 已配置（`amadeus/db/` 有 migrations 目录或 alembic.ini；如缺，先看 `amadeus/db/postgres.py` 起 alembic）。

**Gate P0**：上面四项全勾选。任何一项 block 不前进。

---

## P1 · Registry 三表 + 元数据（HD2 准备 + R1）

### P1.1 新数据结构
- [ ] `amadeus/tools/registry.py`：替换 OrderedDict 为三表 `_tools / _metadata / _documents`
- [ ] 新增 `amadeus/tools/search/document.py`：`ToolDocument` dataclass（design 3.2）
- [ ] `amadeus/tools/registry.py`：`register` 签名扩展为 `(tool, *, risk, always_on, search_hint, source_type, source_name)`
- [ ] `unregister` / `get` / `get_metadata` / `get_document` / `get_registered_names` / `get_names_by_source` 实现
- [ ] `get_schemas(names: set | None)`，先**不**注入 purpose（purpose 在 P3 实现）
- [ ] `get_always_on_names` / `get_documents`

### P1.2 兼容
- [ ] 保留 `names()` 返回 `KeysView` 或 `Iterable`（旧调用点继续用）
- [ ] 保留旧 `export_openai_tools()` 作为 `get_schemas(names=None)` 薄壳，避免外部调用点立刻炸

### P1.3 装配点改写
- [ ] `amadeus/app/bootstrap.py:332-339`：现有 `tool_registry.register(X())` 改为带元数据 register（`source_type="builtin"`，`risk` 按工具语义标：read 工具 `read-only`、write/edit `write`、memory 工具 `read-only`/`write`）
- [ ] memory 工具（`recall_memory` / `memorize` / `forget_memory` / `undo_memory_by_source`）的 `risk` 分别标注

### P1.4 Validation
- [ ] `python -m pytest tests/tools/test_tool_registry.py -v` 既有 happy-path 通过（适配新 register 签名）
- [ ] 新增 `tests/tools/test_registry_rev2.py`：三表同步、`get_schemas(names)` 子集、`get_names_by_source` 反查、`get_always_on_names`

**Gate P1**：上述测试通过；`bootstrap.py` 用新装配能起 service（手动 `amadeus` CLI 起一次，确认无 import / register 错）。

---

## P2 · ToolExecutor invoker port + HookOutcome 三段式（HD1/HD2/HD3/HD4 + R2）

### P2.1 协议数据结构
- [ ] `amadeus/tools/base.py`：新增 `HookOutcome`（decision/updated_input/reason，无 extra_message）
- [ ] `HookContext` / `HookTraceItem` / `ToolExecutionResult` dataclass（design 3.4/3.5）
- [ ] `ToolExecutionRequest` 扩展 `source` / `session_key` / `tool_batch` tuple / `tool_batch_index`
- [ ] `ToolHook` Protocol 改为 `name` / `event` / `matches(ctx)` / `run(ctx) -> HookOutcome`

### P2.2 Executor 重写
- [ ] `amadeus/tools/executor.py`：`ToolExecutor(hooks: list[ToolHook], invoker: ToolInvoker)`
- [ ] `execute(request: ToolExecutionRequest) -> ToolExecutionResult` 三段式（design 4.2）
- [ ] `_run_pre_hooks` / `_run_post_hooks` 内部方法
- [ ] post hook `fail_open=True` 实现：post hook 自身抛错 catch、记 trace、不抛
- [ ] `preflight(request)`：只跑 pre hooks，不调 invoker（assert invoker 不被调）
- [ ] 旧 `execute` / `execute_async` 同步签名保留为薄壳，转发新 `execute(request)`

### P2.3 Hook 适配
- [ ] `amadeus/tools/hooks.py`：`ReadOnlyFilesystemHook` 改为符合新 `ToolHook` Protocol（`name="readonly_filesystem"`、`event="pre_tool_use"`、`matches` 按 `_FILE_TOOLS` 过滤、`run` 返回 `HookOutcome`）
  - 改参放行：`HookOutcome(updated_input={**args, "path": resolved}, decision="pass")`
  - 越界 deny：`HookOutcome(decision="deny", reason="path escapes allowed directory: ...")`
- [ ] 删除旧 `ToolExecutionDenied` 仍可保留作为兼容异常（旧测试可能 import），但 executor 不再依赖它

### P2.4 装配
- [ ] `amadeus/app/bootstrap.py`：`tool_executor = ToolExecutor(hooks=[ReadOnlyFilesystemHook(workspace_root=config.workspace_root)], invoker=_invoker)`
- [ ] 定义 `_invoker(name, args)`：`args.pop("purpose", None); return await tool_registry.execute(name, args)`（purpose pop 在此，P3 注入后这条才生效，本轮 P2 先 pop 一个不存在的 key 不影响）
- [ ] `tool_registry.execute(name, args)` 实现（委托给 `tool.execute(**args)`）

### P2.5 Validation
- [ ] `tests/tools/test_executor_rev2.py`：
  - pre hook 改参不 deny（assert final_arguments 含改后参、status=success）
  - pre hook deny 不改参（assert status=denied、output=reason）
  - pre hook 改参 + deny 同时（assert final_arguments 是改后参、status=denied）
  - post hook 抛错 fail_open（assert status=success、post_trace 记 error）
  - preflight 不调 invoker（用 mock invoker 侧 assert call_count=0）
- [ ] `tests/tools/test_hook_adapt.py`：`ReadOnlyFilesystemHook` 写工具 path 越界 deny 带 reason；read 工具相对路径改参放行
- [ ] 既有 `tests/tools/test_tool_executor.py` 适配通过

**Gate P2**：所有测试通过，executor 不持有 Registry（grep `self.registry` 在 `executor.py` 应零匹配）。

---

## P3 · 意图字段注入（ID1~ID5 + R4）

### P3.1 注入逻辑
- [ ] `amadeus/tools/registry.py`：`_PURPOSE_FIELD = "purpose"`、`_PURPOSE_SCHEMA`（design 3.8），5-12 写 description 文本，**不**设 minLength/maxLength
- [ ] `_inject_purpose(schema, tool)`：deepcopy schema → properties 加 `purpose` → required 加 `purpose`。无兼容分支（ID4），所有工具一律注入

### P3.2 export 路径加注入
- [ ] `get_schemas(names)` 每条 schema 经 `_inject_purpose` 后返回

### P3.3 pop 在 invoker（已在 P2.4 写好）
- [ ] 验证 `_invoker` 的 `args.pop("purpose", None)` 在 registry.execute 前生效
- [ ] 确认 `recall_memory` 的 `intent` 字段**不**被注入逻辑碰（grep `_PURPOSE_FIELD` 与 `intent` 无交集）

### P3.4 Validation
- [ ] `tests/tools/test_purpose_inject.py`：
  - 所有工具 schema `parameters.properties` 含 `purpose` 且 `required` 含 `purpose`
  - `purpose` 无 `minLength` / `maxLength` 键
  - `recall_memory` schema 的 `intent` 字段保留（不被覆盖）
  - invoker pop 后工具 `execute(**kwargs)` 不被传 `purpose`（用 fake tool 记录 kwargs）

**Gate P3**：测试通过；手动起一遍 `amadeus` 看导出 schema 含 `purpose`。

---

## P4 · 按需解锁（TD1~TD5 + R3）

### P4.1 KeywordSearchBackend
- [ ] `amadeus/tools/search/backend.py`：`KeywordSearchBackend`（CJK bigram 加权打分，design TD1+TD5）
  - `add(doc: ToolDocument)` / `remove(name)` / `search(query, top_k, allowed_risk, excluded_names) -> list[{name, summary, why_matched, risk, always_on}]`
  - 分字段打分：name parts 精确 10 / 部分 5 / 全名 3；`search_hint` +4；description +2
  - 精确名匹配 fast path
  - `_explain` 独立生成 `why_matched`
- [ ] `ToolRegistry` 内部 `register`/`unregister` 调 `self._backend.add/remove`
- [ ] `ToolRegistry.search(query, ...)` 委托 backend

### P4.2 tool_search 工具
- [ ] `amadeus/tools/discovery/tool_search.py`：`ToolSearchTool` 实现 Tool 协议
  - `name="tool_search"`、`always_on=True`、注册到 Registry（`source_type="builtin"`）
  - `parameters`：`{"type":"object","properties":{"query":{"type":"string"},"top_k":{"type":"integer","default":5}},"required":["query"]}`
  - `execute(query, top_k=5)`：若 `query.startswith("select:")` → `registry.get_schemas_as_doc_results([name])`（精确解锁路径）；否则走 `registry.search(query, top_k=top_k)`，返回 JSON 字符串

### P4.3 TurnVisibleSet / ToolDiscoveryState
- [ ] `amadeus/tools/discovery/visible_set.py`：`TurnVisibleSet`（design 3.7）
  - `__init__(always_on: set, discovery_state: ToolDiscoveryState)`
  - `is_visible(name) -> bool`、`add_unlocked(name)`、`visible_names() -> set`
  - `consume_unlock_targets(tool_search_result_text) -> list[str]`：解析 tool_search 返回的 JSON 里的工具名（select: 即解锁单个）
- [ ] `amadeus/tools/discovery/state.py`：`ToolDiscoveryState`（session 级 LRU，capacity=64）
  - `warm_up(visible_set)` / `remember(name)` / `__contains__`

### P4.4 reasoner 接入
- [ ] `amadeus/runtime/reasoner.py` `_run_tool_loop` 改：
  - 构造 `TurnVisibleSet` 与 `ToolDiscoveryState`（lifetime = 单次 `_run_tool_loop`）
  - ① 导出：`schemas = registry.get_schemas(names=turn_visible_set.visible_names())`
  - ③ 分发：先 `turn_visible_set.is_visible(tool_call.name)` 判断；未解锁走 preflight + 引导回填（design 4.1）
  - `tool_search` 调用后：`turn_visible_set.consume_unlock_targets(exec_result.output)` + `discovery_state.remember(...)`
- [ ] 保留 `repeat_history` 重复签名守卫与 `max_tool_iterations`
- [ ] `amadeus/runtime/passive.py:426-428` 不再全量 dump——改为传 visible_names 给 reasoner，让 reasoner 自己取 schemas（或保留入口但参数改成 names）

### P4.5 装配
- [ ] `bootstrap.py`：`ToolSearchTool` 注册成 `always_on=True`、`source_type="builtin"`
- [ ] `RecallMemoryTool` 等保持 `always_on=True` 还是 `False`——按 akashic 默认，基础记忆工具 `always_on=True`，其余 deferred

### P4.6 Validation
- [ ] `tests/tools/discovery/test_visible_set.py` / `test_discovery_state.py`
- [ ] `tests/tools/search/test_backend.py`：CJK query 命中、`why_matched` 字段、`search_hint` 加权
- [ ] `tests/tools/discovery/test_tool_search.py`：`select:某工具` 走精确路径；普通 query 走打分
- [ ] `tests/integration/test_tool_loop_deferred.py`：模型先 tool_search → 解锁 → 下一轮 schema 含目标工具 → 调用 → 结果回写

**Gate P4**：上面所有测试通过；e2e deferred 链路跑通。

---

## P5 · MCP Transport 层（MD1/MD7 + R5.1~5.5）

### P5.1 McpTransport port
- [ ] `amadeus/mcp/transport.py`：`McpTransport` Protocol（design 3.9）、`McpToolInfo` dataclass

### P5.2 stdio transport
- [ ] `amadeus/mcp/stdio_transport.py`：`StdioMcpTransport`（design 6.1）
  - `connect` / `call` / `disconnect` / `is_alive`
  - `_recv(expected_id, stage, timeout)` 按线 JSON-RPC、跳过 notification、超时诊断
  - `_drain_stderr` 后台 task
  - `_STREAM_LIMIT = 4MB`
  - connect 8s 超时、call timeout 可配置

### P5.3 HTTP transport
- [ ] `amadeus/mcp/http_transport.py`：`StreamableHttpMcpTransport`（design 6.2，按 MCP 2025-06-18 规范）
  - `httpx.AsyncClient` 长 client（每 server 独立，连接池 size=1）
  - 单 MCP endpoint URL（POST + GET 同路径）
  - 所有请求带 `MCP-Protocol-Version: 2025-06-18` header
  - initialize POST：带 `Accept: application/json, text/event-stream`，响应 header 取 `Mcp-Session-Id`
  - 后续所有请求带 `Mcp-Session-Id: <id>` header
  - **响应解析 MUST 同时支持两种**：按 `Content-Type` 分发——`application/json` 解析单 JSON；`text/event-stream` 解析 SSE 帧（`event:` / `data:` / 空行），从 data 行提取 JSON-RPC message 直到流关闭
  - notifications/initialized / tools/list / tools/call 走 POST
  - 超时归一为 `"MCP error (HTTP <code>): <message>"` 字符串不抛
  - `disconnect()`：发 DELETE（带 session id）；遇 405 忽略；`await client.aclose()`
  - 不做旧 HTTP+SSE 兼容 fallback（决策已拍）
  - 不做 GET 主动流、Resumability（可选能力，本轮不做）

### P5.4 McpClient 协议层
- [ ] `amadeus/mcp/client.py`：`McpClient(name, transport)`，封装 JSON-RPC 报文构造与解析
  - `connect() -> list[McpToolInfo]`：发 initialize → 通知 initialized → tools/list
  - `call(tool_name, arguments, timeout) -> str`
  - `disconnect()`

### P5.5 Validation
- [ ] `tests/mcp/test_stdio_transport.py`：用 mock 假 server 脚本（Python subprocess 提供 initialize/tools/list/tools/call 响应）
- [ ] `tests/mcp/test_http_transport.py`：用 `httpx.MockTransport` 或本地 ASGI mock，断言：
  - `MCP-Protocol-Version: 2025-06-18` header 在所有请求上
  - initialize 响应取 `Mcp-Session-Id` 后续请求带
  - **两种响应 content-type 都解析**：单 JSON 响应 + SSE 流响应（用 `text/event-stream` mock 验 SSE 帧解析）
  - 超时归一字符串不抛
- [ ] `tests/mcp/test_mcp_client.py`：协议层报文构造正确

**Gate P5**：transport 单测通过；真实假 server 能 connect/list/call 跑通。

---

## P6 · MCP 工具包装与注册（R5.4~R5.6, MD4, MD6）

### P6.1 schema 轻校验
- [ ] `amadeus/mcp/schema_validator.py`：`validate_openai_function_schema(input_schema) -> list[str]`（design 6.3）

### P6.2 McpToolWrapper
- [ ] `amadeus/mcp/tool.py`：`McpToolWrapper(client, info, server_name)`
  - `name = f"mcp_{server_name}__{info.name}"`、`description = f"[MCP:{server_name}] {info.description}"`
  - `parameters = info.input_schema`（透传，已校验）
  - `execute(**kwargs) -> str`：转 `client.call(info.name, kwargs, timeout=...)`

### P6.3 命名可逆性
- [ ] 单测 `test_mcp_tool_wrapper.py`：round trip `mcp_{server}__{tool}` 解析回 `(server, tool)`

### P6.4 McpServerRegistry
- [ ] `amadeus/mcp/registry.py`：`McpServerRegistry(db, tool_registry)`（design 3.11）
  - `add(name, transport_type, command, url, env, cwd)`：建 transport + McpClient → connect → 校验各 tool schema → 包装 register 进 tool_registry → db 持久化
  - `remove(name)`：`tool_registry.get_names_by_source(name)` 反查 → 全 unregister → client.disconnect → db 删
  - `load_and_connect_all()`：从 db 加载 → 并行 add
  - `start_connect_all_background()`：`asyncio.create_task`，不阻塞
  - `shutdown()`：并行 disconnect

### P6.5 Validation
- [ ] `tests/mcp/test_schema_validator.py`：`$ref` 被挡、`type` 不合法被挡
- [ ] `tests/mcp/test_mcp_server_registry.py`：add/remove/反查 unregister；start_connect_all_background 不阻塞（assert 立即返回）；shutdown 串行断开

**Gate P6**：MCP 工具能注册进 Registry（`source_type="mcp"`），`get_names_by_source` 反查可用。

---

## P7 · mcp_add 工具 + DB 表 + 装配（MD2/MD3/MD5 + R5.6~R5.9）

### P7.1 DB 表
- [ ] `amadeus/db/mcp_servers.py`：`McpServersStore` CRUD（design 3.12）
- [ ] alembic migration up：`CREATE TABLE mcp_servers (...)`；down：`DROP TABLE mcp_servers`
- [ ] 跑 `alembic upgrade head` 在本地 postgres 验证

### P7.2 mcp_add / mcp_remove / mcp_list 工具
- [ ] `amadeus/mcp/manage_tools.py`：`McpAddTool` / `McpRemoveTool` / `McpListTool`（design 6.4）
- [ ] 这三个工具注册进 Registry 时 `source_type="builtin"`、`always_on=True`

### P7.3 装配
- [ ] `amadeus/app/bootstrap.py`：
  - `mcp_db = McpServersStore(postgres_db)`（如果 postgres 启用）
  - `mcp_server_registry = McpServerRegistry(db=mcp_db, tool_registry=tool_registry)`
  - `mcp_server_registry.start_connect_all_background()`
  - 注册 `McpAddTool(mcp_server_registry)` / `McpRemoveTool` / `McpListTool` 进 Registry

### P7.4 Validation
- [ ] `tests/mcp/test_manage_tools.py`：mcp_add 调用 → 注册成功 → mcp_list 能看到 → mcp_remove → 工具被 unregister
- [ ] `tests/integration/test_mcp_end_to_end.py`：完整链路 mcp_add → tool_search → select 解锁 → 调用 → 结果

**Gate P7**：MCP 集成测试通过；服务重启能从 db 加载 mcp servers 重连。

---

## P8 · 集成与既有测试更新（A6）

- [ ] `tests/tools/test_tool_registry.py` 适配新 API（register 多了 kwargs）
- [ ] `tests/tools/test_tool_executor.py` 适配新 `execute(request)` 签名
- [ ] grep `export_openai_tools` / `tool_executor.execute_async` / `ToolExecutionDenied` 找所有旧调用点，确认改齐或薄壳转发
- [ ] `python -m pytest tests/ -v` 全量绿
- [ ] `ruff check amadeus/ tests/` 无新增违规
- [ ] `mypy amadeus/` 无新增类型错误（注意 `mypy.ini` / `pyproject.toml` 已有的 per-module 放宽）

**Gate P8（最终）**：全量测试绿；lint/类型检查通过；e2e 链路手动验过。

---

## Validation 命令汇总

```bash
# 全量测试
python -m pytest tests/ -v

# 单阶段
python -m pytest tests/tools/ -v            # P1~P4
python -m pytest tests/mcp/ -v              # P5~P7
python -m pytest tests/integration/ -v      # 集成

# Lint / 类型
ruff check amadeus/ tests/
mypy amadeus/

# 手动 e2e
amadeus                                      # 起 service
# 在 web UI 触发一个 turn，看是否：
# 1) tool_search 在 schema 里
# 2) 模型 tool_search 后工具被解锁（下一轮 schema 含目标工具）
# 3) mcp_add 工具可见，调一次能加 server
```

## Rollback Points

| 阶段 | 失败 symptoms | 回退动作 |
|---|---|---|
| P1 | bootstrap 起不来、tool_registry 测试红 | 单独 commit 在 P1 末，`git reset` 回 P0；不影响主分支 |
| P2 | executor 测试红 | P2 末单独 commit；可回退 P1 保留新 Registry，executor 旧版继续用 |
| P3 | purpose 注入导致工具不可用 | disable `_inject_purpose`（注释掉一行 `get_schemas` 里的调用），回归 P2 状态 |
| P4 | reasoner 循环改动回归 | 保留旧 `_run_tool_loop` 副本，加 feature flag 切换；P4 改动可灰度 |
| P5 | MCP transport 实现不达预期 | MCP 模块整体不装配到 bootstrap（注释 `mcp_server_registry` 装配行），主路径退回 P4 状态 |
| P6/P7 | MCP 注册/MCP DB 阻断主服务启动 | `start_connect_all_background` 内部 try/except 兜底；alembic down migration drop 表 |
| P8 | 既有测试不兼容 | 薄壳 `execute_async` / `export_openai_tools` 转发更长期保留，逐步迁移 |

## Review Gates 总结

- **Gate P0**：准备就绪
- **Gate P1**：Registry 三表，旧测试通过
- **Gate P2**：Executor + Hook 协议，新测试通过，Executor 不持 Registry
- **Gate P3**：purpose 注入，recall_memory intent 不被碰
- **Gate P4**：deferred + tool_search，e2e deferred 链路通
- **Gate P5**：MCP transport，假 server connect/list/call 通
- **Gate P6**：MCP 工具能注册、反查卸载
- **Gate P7**：mcp_add 模型可调、DB 持久化、重启重连
- **Gate P8（最终）**：全量测试绿、lint/类型通过、手动 e2e 验过

## 备注

- 任何阶段发现 PRD/design 假设错误（如 Streamable HTTP 规范细节、akashic LRU 容量、httpx 行为不一致），返回 Phase 1 修 `design.md` 对应章节，再回 Phase 2 实施。
- 每个阶段结束记录到 `.trellis/workspace/Zn/journal-1.md`（按 Trellis 习惯）。
- 复杂阶段（P2/P4/P5）若需要分派 sub-agent 实现，curate `implement.jsonl` 与 `check.jsonl` 作为 spec/research manifest。