# 统一工具注册与 MCP 接入链路

## Goal

把当前 OrderedDict 薄壳式的 ToolRegistry 重写为承载"工具发现 / 工具执行 / 工具来源"的统一注册中心，合并 MCP server 接入能力到同一条工具注册链路中，并修复当前工具调用链路的几个具体缺口：hook 协议表达能力弱、Executor 与 Registry 焊死、全量 schema dump 造成的上下文膨胀、缺少意图表达通道、缺少 MCP 适配层。

设计参考 akashic-agent 的工具子系统，并在本轮 grilling 中已对 16 项关键决策完成取舍。本 PRD 即基于这 16 项决策落地为需求与验收标准。

## Background

当前现状（来自对 `amadeus/` 的基线探索）：

- `ToolRegistry`（`amadeus/tools/registry.py:10`）是 `OrderedDict[name → Tool]` 薄壳，只有 `register / unregister / get / names / export_openai_tools` 五个方法。`export_openai_tools()` 全量 dump 所有工具 schema，每轮 `provider.chat` 都重传同一份——这是上下文膨胀的根源。
- `ToolExecutor`（`amadeus/tools/executor.py:16`）直接持有 `registry`，hook 协议是同步 `before_execute(request) -> request` / `after_execute(request, result) -> result`，靠抛 `ToolExecutionDenied` 中止。只能 deny、不能"改参不 deny"独立表达，deny 也没有结构化 reason。
- `ReadOnlyFilesystemHook`（`amadeus/tools/hooks.py:17`）已实现但在生产装配中未注入 executor（`amadeus/app/bootstrap.py:362` 构造时不传 hooks）。
- MCP 完全未接入。文档里 MCP 一直被标为"后置产品路径"。
- 模型工具调用链路收敛清晰：`PassiveRuntime.run_turn` → `Reasoner._run_tool_loop` → `ToolExecutor.execute_async`，但中间没有可见性闸门、没有工具级意图表达、没有按需解锁机制。
- 仓库是 Python 3.11 + FastAPI + postgres 后端，已有 alembic、pgvector、worker 多进程架构。MCP stdio 子进程在本后端可行。
- Amadeus 内 `intent` 字段已被 `recall_memory` 工具和 memory 检索体系占用（`amadeus/tools/recall_memory.py:65`、`amadeus/memory/engine.py:40`），注入的意图字段不能与之同名。

## Requirements

### R1 · 工具注册中心（ToolRegistry 三表结构）

- R1.1 Registry 内部维护三张并行 dict：`_tools: dict[str, Tool]`、`_metadata: dict[str, ToolMeta]`、`_documents: dict[str, ToolDocument]`，三者用工具名串起来。
- R1.2 `ToolMeta` 至少含字段：`risk`（`read-only` / `write` / `external-side-effect`）、`always_on: bool`、`search_hint: str | None`、`source_type`（`builtin` / `mcp` / `plugin`）、`source_name`。
- R1.3 `ToolDocument` 是检索索引态纯文本视图，至少含：`name / description / risk / always_on / search_hint / source_type / source_name`，由 Tool + ToolMeta 派生。
- R1.4 `register(tool, *, risk, always_on, search_hint, source_type, source_name)` 带元数据登记，三张表同步更新。
- R1.5 `unregister(name)` 三张表同步移除。
- R1.6 `get_schemas(names: set[str] | None)` 支持按名子集导出 OpenAI function schema；`names=None` 时导出全集。
- R1.7 提供 `get_documents()`、`get_always_on_names()`、按 `source_name` 反查工具名的能力（供 MCP 卸载使用）。
- R1.8 保留现有 `get(name)` / `names()` 兼容性（或提供等价 API 让旧调用点平滑迁移）。

### R2 · 工具执行器与 Hook 协议（ToolExecutor invoker port + HookOutcome）

- R2.1 `ToolExecutor` 不持有 `ToolRegistry`，构造为 `ToolExecutor(hooks, invoker: ToolInvoker)`，`ToolInvoker = Callable[[str, dict], Awaitable[Any]]`。
- R2.2 Hook 协议从"抛异常式"改为 `HookOutcome` 三段式 dataclass，字段 `decision: "pass" | "deny"`、`updated_input: dict | None`、`reason: str`。不保留 `extra_message` 字段。
- R2.3 pre hook 可改参（`updated_input` 整体替换）、可 deny（`decision="deny"` + `reason`），两者正交可同时表达。
- R2.4 post hook 只能观察、记 trace，不能改参、不能 deny。post hook 自身抛错时 `fail_open=True`，只记 trace 不影响主链路。
- R2.5 Hook 链执行按 hooks 注册顺序串行；每个 hook 有 `event` 字段（`pre_tool_use` / `post_tool_use` / `post_tool_error`），executor 按 event 分发。
- R2.6 `ToolExecutor.execute(request, invoker)` 返回结构化 `ToolExecutionResult`，含 `status`、`output`、`final_arguments`、`pre_hook_trace`、`post_hook_trace`。
- R2.7 `ToolExecutor.preflight(request)` API：只跑 pre hooks、不调 invoker；语义收紧"不执行真实工具"，给"工具未到执行条件时让 pre hook 看一眼"的场景使用（可见性闸门、未来的 loop guard）。
- R2.8 `ReadOnlyFilesystemHook` 适配新协议（返回 `HookOutcome` 而非抛异常），并在 `bootstrap.py` 装配时注入 executor。

### R3 · 按需解锁与工具检索（deferred loading + tool_search）

- R3.1 ToolMeta 的 `always_on` 字段标记常驻可见工具（如 `tool_search` 本身、最基础记忆工具）。
- R3.2 模型每轮看到的工具集 = `always_on ∪ visible_names`；其余工具属于 deferred 集合，schema 不进 prompt。
- R3.3 `tool_search` 作为一个 always_on 工具注册进 Registry，模型可调用以发现 deferred 工具。
- R3.4 检索后端使用关键词打分（`KeywordSearchBackend`），CJK bigram 加权打分，无外部依赖；按 name parts / `search_hint` / `description` 分字段加权，提供 `why_matched` 解释。
- R3.5 `tool_search` 接受 query 参数；`query="select:<工具名>"` 走精确匹配路径触发解锁；普通 query 走打分检索返回候选列表。
- R3.6 本轮可见集由独立的 `TurnVisibleSet` 对象管理，提供 `is_visible(name)` 与 `add_unlocked(name)` 接口。
- R3.7 跨轮缓存由独立的 `ToolDiscoveryState` 对象管理（session 级 LRU），新 turn 开始时用它给本轮集垫底。
- R3.8 reasoner 在工具分发前判断 `TurnVisibleSet.is_visible(name)`；未解锁的 tool_call 走 `ToolExecutor.preflight`（让 pre hook 链看一眼，给未来 loop guard 留插座位），未被 pre hook deny 则回填"请先调 tool_search(query='select:<name>') 解锁"引导文字。

### R4 · 意图字段（progress description 软约束）

- R4.1 在每个工具 schema 导出时注入一个 `purpose` 字段到 `parameters.properties`，并加入 `parameters.required`。
- R4.2 `purpose` 字段定义：`{"type": "string", "description": "用 5-12 个字说明这次工具调用的意图，只写给用户看的短语。不要复述工具名，不要粘贴长参数。例如：查看目录、读取配置、搜索健康数据。"}`，不设 `minLength` / `maxLength` 硬约束。
- R4.3 字段名固定为 `purpose`（不与 `recall_memory` 已占用的 `intent` 字段冲突）。
- R4.4 不做"工具自已在 parameters 声明 `purpose` 就不注入"的兼容分支，所有工具一律注入、execute 前 pop。
- R4.5 pop 操作在 invoker 装配层硬编码（`args.pop("purpose", None)` 后再调 `registry.execute`），不走 hook 链。
- R4.6 `purpose` 字段定位为 UI 显示工具执行进度 + tool_chain 回放辅助，**不作为防误调机制**——不做硬校验、不进 hook deny 决策。

### R5 · MCP 接入

- R5.1 抽象 `McpTransport` port，提供两个实现：stdio transport（直抄 akashic `client.py` 的子进程 + 行式 JSON-RPC + stderr drain + connect 8s 超时 + call 超时 + recent stdout/stderr 尾 8 行诊断）和 Streamable HTTP transport（按 MCP 规范自写，使用 `httpx`，处理 `Mcp-Session-Id` header、SSE 流超时、错误归一）。
- R5.2 `McpClient` 协议层封装 JSON-RPC 报文（initialize / notifications/initialized / tools/list / tools/call），transport 层负责字节通道。
- R5.3 `McpServerRegistry` 管理多个 MCP server 的连接生命周期：`add(name, transport_config)` 幂等、`remove(name)` 按 `source_name` 反查并 unregister 所有相关工具并断开、`load_and_connect_all()` 启动时并行重连、`start_connect_all_background()` 后台重连不阻塞主服务启动、`shutdown()` 并行断开。
- R5.4 `McpToolWrapper` 把单个远端工具包成本地 `Tool` 协议实现，命名规则 `mcp_{server}__{tool}`（双下划线，可逆解析），`description` 加前缀 `[MCP:{server}]`，`parameters` 直接透传远端 `input_schema`，`execute(**kwargs)` 通过 transport 发 `tools/call`。
- R5.5 MCP 工具注册进 Registry 时 `risk="external-side-effect"`、`source_type="mcp"`、`source_name=<server>`，三张表同步登记（含 `_documents`，使 tool_search 能搜到 MCP 工具）。
- R5.6 `mcp_add` / `mcp_remove` / `mcp_list` 作为注册进 Registry 的工具暴露给模型，模型可调用 `mcp_add(name, command|transport_config, env)` 动态加 server。
- R5.7 MCP server 配置持久化到 postgres，新增 `mcp_servers` 表（字段至少含 `name`、`transport_type`、`command`/`url`、`env`、`cwd`、`authorized`）并通过 alembic 迁移建表。重启时从表加载所有 server 并重连。
- R5.8 注册 MCP 工具时做轻校验：检查 `input_schema` 的 `type` 合法性、`properties` 完整性、是否使用 OpenAI 不支持的 keyword（`$ref` 等），校验失败返回错误列表，`mcp_add` 调用者能看到哪个工具因 schema 问题未注册。
- R5.9 `mcp_servers.authorized` 字段默认 `true`（加完即可解锁），为未来加白名单/二次确认档位留口子。本轮不做二次确认 UI，但字段必须存在。

## Acceptance Criteria

### A1 · Registry 三表结构

- [ ] `ToolRegistry` 内部为 `_tools / _metadata / _documents` 三张 dict，三者在 register / unregister 时同步更新。
- [ ] `get_schemas(names)` 支持 `names=None` 与 `names=set[...]` 两种入参，返回对应子集的 OpenAI function schema。
- [ ] `ToolMeta` 含 `risk / always_on / search_hint / source_type / source_name` 五个字段。
- [ ] 能按 `source_name` 反查某 MCP server 名下注册的所有工具名（用于卸载）。

### A2 · Executor 与 Hook 协议

- [ ] `ToolExecutor` 构造为 `ToolExecutor(hooks, invoker)`，不持有 Registry 引用。
- [ ] `HookOutcome` 含 `decision / updated_input / reason` 三字段，无 `extra_message`。
- [ ] pre hook 能通过 `updated_input` 表达"只改参不 deny"，通过 `decision="deny"` 表达"只 deny 不改参"，两者可同时表达。
- [ ] post hook 在 `fail_open=True` 下自身抛错不污染主链路，只记 trace。
- [ ] `ToolExecutionResult` 含 `pre_hook_trace / post_hook_trace`。
- [ ] `preflight(request)` API 存在且不调用 invoker（可由测试断言 invoker 不会被调用）。
- [ ] `ReadOnlyFilesystemHook` 适配新协议并在 `bootstrap.py` 装配时被注入 executor。

### A3 · 按需解锁与检索

- [ ] ToolMeta `always_on` 标记的工具在任何轮次都进入导出 schema 集。
- [ ] `tool_search` 注册为 always_on 工具，模型可调用。
- [ ] `KeywordSearchBackend` 对中文 query 走 CJK bigram 打分，对 name / `search_hint` / `description` 分字段加权，返回结果含 `why_matched`。
- [ ] `select:<工具名>` query 走精确匹配路径。
- [ ] `TurnVisibleSet` 独立对象提供 `is_visible` / `add_unlocked`，reasoner 不再直接维护 visible_names 集合。
- [ ] `ToolDiscoveryState` 提供 session 级 LRU 缓存，新 turn 用它给本轮集垫底。
- [ ] reasoner 对未解锁的 tool_call 调 `preflight`，未被 pre hook deny 则回填"请先调 tool_search(query='select:<name>') 解锁"引导文字。
- [ ] 解锁后下一轮 `get_schemas` 导出集包含该工具，模型可正常调用。

### A4 · 意图字段

- [ ] 所有工具导出的 schema `parameters.properties` 含 `purpose` 字段，且 `parameters.required` 列表含 `purpose`。
- [ ] `purpose` 字段无 `minLength` / `maxLength` 硬约束。
- [ ] 任何工具的 `parameters` 不出现 `intent` 字段被注入（避免与 `recall_memory` 冲突）。
- [ ] invoker 在调 `registry.execute` 前 pop 掉 `purpose` 字段，工具 `execute(**kwargs)` 不会被传 `purpose`。
- [ ] 不存在"工具自声明 purpose 则不注入"的兼容分支代码。

### A5 · MCP 接入

- [ ] `McpTransport` 是抽象 port，stdio 与 Streamable HTTP 各有一个实现。
- [ ] stdio transport 实现 stderr drain、connect 8s 超时、call 超时、recent stdout/stderr 诊断。
- [ ] Streamable HTTP transport 实现 `Mcp-Session-Id` header 管理、SSE 流读取、错误归一。
- [ ] `McpServerRegistry.add(name, ...)` 幂等，连接成功后把该 server 的工具注册进 Registry，`source_type="mcp"`、`source_name=name`。
- [ ] `McpServerRegistry.remove(name)` 按 `source_name` 反查并 unregister 所有相关工具，并断开 transport。
- [ ] `McpServerRegistry.start_connect_all_background()` 不阻塞主服务启动。
- [ ] `McpToolWrapper` 命名为 `mcp_{server}__{tool}`，可逆解析回 server / tool。
- [ ] `mcp_add / mcp_remove / mcp_list` 作为工具注册进 Registry，模型可调用 `mcp_add` 动态加 server。
- [ ] postgres `mcp_servers` 表通过 alembic 迁移建表，重启时从表中加载所有 server 并后台重连。
- [ ] 注册 MCP 工具时做轻 schema 校验，使用 `$ref` 等 OpenAI 不支持 keyword 的工具被挡下并出现在 `mcp_add` 返回的错误列表里。
- [ ] `mcp_servers.authorized` 字段存在，默认 `true`。

### A6 · 链路集成

- [ ] end-to-end：模型在 deferred 集合有某 MCP 工具时，能通过 `tool_search` 找到它、用 `select:` 解锁、下一轮正常调用并得到结果。
- [ ] reasoner 主循环 `tool_schemas` 导出集随 visible_names 动态扩张，不再全量 dump。
- [ ] 既有测试 `tests/tools/test_tool_registry.py` / `tests/tools/test_tool_executor.py` 在新 API 下通过或被合理更新。
- [ ] `ReadOnlyFilesystemHook` 在生产装配下生效（写工具的 path 越界被挡并带 reason）。

## Constraints

- 文档（PRD/design/implement）使用中文。
- 不引入新的 Python 运行时依赖：`httpx 0.28.1` 已在 `.venv`（fastapi/openai 传递依赖），MCP HTTP transport 直接使用，不改 `pyproject.toml`。stdio transport 用标准库 `asyncio`。
- 不破坏 memory 检索体系对 `intent` 字段的使用（`recall_memory` 工具的 `intent` 参数语义保持）。
- MCP 工具命名与内置工具不冲突（通过 `mcp_{server}__` 前缀隔离）。
- Hook 协议迁移期允许旧 `before_execute/after_execute` 调用点逐步改造，不要求 big-bang 重写。

## Out of Scope

- 不做 progress description 字段的硬校验（minLength/maxLength、语义匹配）。ID5 已确认这是软约束。
- 不做 MCP 工具首次解锁的二次确认 UI 流程（MD5 留 `authorized` 字段为后续档位铺路，本轮默认 true 即加完即解锁）。
- 不做 ToolLoopGuard / 其它具体业务 pre-hook 插件（preflight 为它们留座，但本轮不实现具体插件）。
- 不做 tool_search 的向量检索或 RRF 双路融合（TD5 选关键词方案，向量检索留作未来增量改进路径）。
- 不做 MCP 配置的文件持久化（MD3 选 postgres，文件方案不做）。
- 不做跨项目 akashic 工具复用的 translator（ID2 选 `purpose`，与 akashic `description` 不互通，但跨项目复用工具不在本轮范围）。

## Notes

- 16 项关键决策已在 grilling 中拍定（HD1~HD4 / TD1~TD5 / ID1~ID5 / MD1~MD7），决策记录见 `design.md` 的决策表。
- 后续 `design.md` 给出技术设计、数据结构契约、数据流；`implement.md` 给出有序执行 checklist、validation 命令、review gates 与 rollback points。
- 基线探索报告与 akashic 对照报告的关键 file:line 引用见 `design.md` 的"参考实现"一节。