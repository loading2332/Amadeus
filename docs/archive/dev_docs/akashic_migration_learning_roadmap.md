# Akashic → Amadeus 迁移与学习路线

## 0. 目标与边界

这份路线不是“把 Akashic 复制到 Amadeus”，而是把 Akashic 的完整实现拆成可学习、可判断、可迁移的能力层。

Amadeus 已经完成：

- Prompt block 与 runtime context 组装
- system prompt / context frame 分层
- SQLite session runtime
- `TurnCommitted` 事件
- OpenAI SDK provider
- Markdown memory store / maintenance / optimizer

后续迁移原则：

- Akashic 是参考实现，不是 base class。
- 优先迁移经过验证的设计模式，不迁移历史包袱。
- 每一阶段都必须有可运行闭环和测试，不做“半套抽象”。
- 涉及自动写记忆、工具执行、主动推送的阶段，要先收窄风险，再扩大能力。

## 1. Akashic 完整实现地图

Akashic 可以按 9 条能力链理解：

| 能力链 | Akashic 参考路径 | Amadeus 状态 |
|---|---|---|
| Prompt / Context | `agent/context.py`, `agent/core/prompt_block.py`, `agent/prompting/*` | 已迁核心模式 |
| Session / History | `session/manager.py`, `session/store.py` | 已迁第一版 |
| Provider | `agent/provider.py` | 已迁第一版 async chat |
| Markdown Memory | `agent/memory.py`, `core/memory/markdown.py`, `proactive_v2/memory_optimizer.py` | 已迁第一版 |
| Vector Memory | `memory2/*`, `plugins/default_memory/*` | 未迁 |
| Tool Runtime | `agent/tools/*`, `agent/tool_runtime.py`, `agent/tool_hooks/*` | 未迁 |
| Passive Agent Loop | `agent/core/passive_turn.py`, `agent/looping/*`, `agent/lifecycle/*` | 未迁 |
| Plugin System | `agent/plugins/*`, `_handbook/plugins-tutorial.md` | 未迁 |
| Proactive / Drift | `proactive_v2/*`, `agent/core/proactive_turn.py`, `agent/core/drift_turn.py` | 未迁 |

学习时不要从目录入手。更好的顺序是：

```text
输入如何进入模型
→ 回复如何提交
→ 记忆如何形成
→ 工具如何执行
→ loop 如何推进
→ 插件如何插入
→ 主动系统如何独立运行
```

## 2. 已完成阶段：Prompt 与 Markdown 记忆地基

### 2.1 Prompt / Context

参考 Akashic：

- `agent/prompting/assembler.py`
- `agent/core/prompt_block.py`
- `agent/context.py`

Amadeus 对应：

- `amadeus/prompt_block.py`
- `amadeus/prompting/assembler.py`
- `amadeus/context.py`

核心学习点：

- 不要过早把 prompt 拼成一个大字符串。
- 先保留 named section，后做 routing / disable / debug / trim。
- stable prompt 和 dynamic context 要分层，否则 retrieval 很容易污染 identity / policy。

验收标准：

- `retrieved_memory` 不进入 system prompt。
- context frame 在 history 之后、current user message 之前。
- `RECENT_CONTEXT.md` 的 `Recent Turns` 不注入 prompt。
- debug breakdown 能区分 system / context frame。

### 2.2 Session / Event / Provider / Markdown Memory

参考 Akashic：

- `session/manager.py`
- `session/store.py`
- `bus/event_bus.py`
- `bus/events_lifecycle.py`
- `core/memory/markdown.py`
- `proactive_v2/memory_optimizer.py`

Amadeus 对应：

- `amadeus/session.py`
- `amadeus/events.py`
- `amadeus/provider.py`
- `amadeus/memory.py`
- `amadeus/runtime.py`

核心学习点：

- 记忆必须绑定稳定 message id，否则无法回源、撤销或幂等。
- `PENDING.md` 是高频缓冲区，`MEMORY.md` 是低频稳定档案。
- optimizer 成功才 commit pending snapshot；失败必须 rollback。
- `SELF.md` 和 `MEMORY.md` 是不同主权来源，不能混写。

验收标准：

- turn commit 后自动刷新 recent turns。
- consolidation 到阈值后写 `HISTORY.md` / `PENDING.md` / `RECENT_CONTEXT.md`。
- optimizer 可把 `PENDING.md` 合并进 `MEMORY.md`。
- optimizer 不更新 `SELF.md`。
- `fetch_messages` 能按 source_ref 回源。

## 2.3 Runtime Bootstrap / 正式 CLI 入口

### 目标

把已迁好的 provider、session、event bus、Markdown memory 和 passive runtime 变成正式运行链路，而不是只通过 `dev_utils` 调试脚本验证 API。

### Akashic 参考

- `agent/config.py`
- `bootstrap/providers.py`
- `bootstrap/memory.py`
- `bootstrap/app.py`
- `main.py`

### Amadeus 对应

- `amadeus/bootstrap.py`
- `amadeus/cli.py`
- `amadeus/__main__.py`

### 核心链路

```text
.env
→ RuntimeConfig
→ 默认 workspace: `~/.amadeus/workspace`
→ LLMProvider
→ SessionManager
→ EventBus
→ MarkdownMemoryRuntime
→ PassiveRuntime.run_turn
→ TurnCommitted
→ RECENT_CONTEXT / HISTORY / PENDING
```

### 关键 tradeoff

- Akashic 使用 `config.toml` 管理主模型、轻量模型、视觉模型、channel、proactive 等完整应用配置。
- Amadeus 当前只需要把真实 API 接入最小 passive runtime，所以先保留 `.env`，避免过早引入完整配置系统。
- Akashic 默认把运行时数据放到 `~/.akashic/workspace`；Amadeus 对齐这个边界，默认写入 `~/.amadeus/workspace`，只有显式传 `--workspace-root` 才写入指定目录。
- 当后续出现多 provider、工具集、channel 或 proactive 配置时，再迁移 Akashic 的 `config.toml + bootstrap` 模式。

### 验收标准

- `python -m amadeus chat "..."` 能调用正式 runtime。
- user / assistant 消息写入 `sessions.db`。
- `TurnCommitted` 触发 memory maintenance。
- `RECENT_CONTEXT.md` 自动刷新。
- 多轮对话可通过同一个 session key 延续。
- `dev_utils` 只保留调试用途，不再是正式运行入口。

## 3. 下一阶段 A：Vector Memory 与检索证据链

### 目标

把 Akashic 的 `memory2` 设计迁成 Amadeus 的第二层记忆：Markdown 管人类可读全景，long-term memory 管可检索细节。

### Akashic 参考

- `memory2/store.py`
- `memory2/memorizer.py`
- `memory2/retriever.py`
- `memory2/query_rewriter.py`
- `memory2/injection_planner.py`
- `memory2/sufficiency_checker.py`
- `plugins/default_memory/engine.py`
- `agent/tools/recall_memory.py`
- `agent/tools/forget_memory.py`

### 建议迁移顺序

1. 定义 `MemoryEngine` 协议。
2. 新增 SQLite vector-memory store，但先用 fake embedding。
3. 订阅 consolidation committed event，把 `HISTORY.md` entries 写入 vector store。
4. 实现 `retrieve(request) -> RetrievalResult(block, evidence, trace)`。
5. 把 retrieval block 接回 `RuntimeContext.retrieved_memory`。
6. 实现 `recall_memory` 的 Python API，暂不暴露给 LLM tool loop。
7. 实现 `forget_memory` / undo 之前，先保证 source_ref 回源稳定。

### 关键 tradeoff

- 快速交付：先 fake embedding，可测试语义少。
- 长期能力：真实 embedding + query rewrite + injection planner，复杂度明显增加。
- 建议：先做 store / event / source_ref / fake retrieval，再接真实 embedding。

### 学习重点

- 为什么 `HISTORY.md` 不直接注入 prompt。
- 为什么 retrieval 结果必须带 evidence / source_ref。
- 为什么 “summary 看起来像事实” 仍然不能替代原始消息。

### 验收标准

- consolidation 后 vector store 有 event item。
- retrieval 能返回 text block 和 evidence。
- retrieval block 进入 context frame，不进入 system prompt。
- `fetch_messages(evidence=...)` 能回看原始消息。
- duplicate source_ref 不重复写入。

## 4. 下一阶段 B：Tool Runtime 与安全执行

### 目标

迁移 Akashic 的工具执行模型，但先不实现完整 agent loop。先让工具成为可注册、可 schema 化、可 hook 拦截的 runtime 能力。

### Akashic 参考

- `agent/tools/base.py`
- `agent/tools/registry.py`
- `agent/tool_runtime.py`
- `agent/tool_hooks/base.py`
- `agent/tool_hooks/types.py`
- `agent/tool_hooks/executor.py`
- `agent/tools/message_lookup.py`
- `agent/tools/shell.py`
- `agent/tools/filesystem.py`

### 建议迁移顺序

1. 新增 `Tool` 协议：`name`, `description`, `parameters`, `execute(**kwargs)`.
2. 新增 `ToolRegistry`：register / unregister / schema export / execute。
3. 新增 `ToolExecutor`：pre hooks → invoker → post hooks。
4. 先注册只读工具：`fetch_messages`, `search_messages`, `read_file`。
5. 再注册写操作工具，并加安全 hook。
6. shell / filesystem 写工具必须最后迁。

### 关键 tradeoff

- 只做 registry 很快，但无法控制风险。
- hook 体系增加复杂度，但能把安全策略从工具本体剥离。
- 建议：registry 和 executor 同阶段做，但工具集合从只读开始。

### 学习重点

- tool schema 是给模型看的接口契约，不是内部函数签名。
- pre hook 适合拒绝或改参，post hook 适合记录和补充信息。
- 安全策略不要散落在每个工具里。

### 验收标准

- registry 能导出 OpenAI tools schema。
- executor 能记录 pre/post hook trace。
- pre hook 能 deny 高风险调用。
- fetch/search message tool 能作为普通 tool 执行。
- 工具异常不会破坏 session history。

## 5. 下一阶段 C：Passive Agent Loop

### 目标

从 single-shot passive runtime 升级为可多步工具调用的被动 agent loop。

### Akashic 参考

- `agent/core/passive_turn.py`
- `agent/looping/core.py`
- `agent/looping/handlers.py`
- `agent/tool_runtime.py`
- `agent/core/response_parser.py`
- `agent/core/types.py`

### 建议迁移顺序

1. 定义 `Reasoner`：接收 messages + tools，返回 assistant text 或 tool calls。
2. 实现 OpenAI tool call 解析。
3. 实现 loop step：
   - call provider
   - 如果有 tool calls，执行工具
   - append assistant tool call message
   - append tool result message
4. 设置 max steps。
5. 无 tool calls 时提交最终 assistant reply。
6. context length error 后接入 trim plan。
7. 工具链持久化进 assistant message extra。

### 关键 tradeoff

- loop 能力会显著提高，但上下文和错误恢复复杂度会增加。
- 第一版不要同时做 streaming、parallel tool calls、proactive。
- 建议：只做非 streaming、串行或批量 tool calls、固定 max steps。

### 学习重点

- tool result 是模型下一步推理的输入，不是直接给用户看的最终答案。
- assistant tool call message 与 tool message 的 OpenAI 格式必须匹配。
- reaching max steps 时要生成阶段性回复，而不是直接沉默。

### 验收标准

- 模型请求工具时，executor 被调用。
- tool result 被加入下一轮 messages。
- 最终 reply 被持久化。
- max steps 到达时返回安全阶段性回复。
- context frame 不作为用户真实消息持久化。

## 6. 下一阶段 D：Lifecycle 与 Plugin System

### 目标

迁移 Akashic 插件系统的核心思想：插件不直接改主 loop，而是挂在 lifecycle phase 和 slots 上。

### Akashic 参考

- `agent/lifecycle/phase.py`
- `agent/lifecycle/types.py`
- `agent/lifecycle/phases/*`
- `agent/plugins/base.py`
- `agent/plugins/manager.py`
- `agent/plugins/decorators.py`
- `_handbook/plugins-tutorial.md`

### 建议迁移顺序

1. 先定义 phase frame + slots。
2. 只实现 3 个阶段：
   - before_turn
   - prompt_render
   - after_turn
3. 插件只能注入 prompt section / extra hint / telemetry。
4. 再开放 before_step / after_step。
5. 最后开放 tool hooks 与 plugin tools。

### 关键 tradeoff

- 直接 event bus 简单，但插件难以精确排序。
- phase slots 更重，但能让插件声明依赖和产出。
- 建议：Amadeus 先做小型 phase system，不直接迁 Akashic 7 阶段完整图。

### 学习重点

- 插件系统最难的不是加载文件，而是控制插入点和数据所有权。
- slot 是跨模块数据总线，能避免插件 import 内部实现。
- requires / produces 是可维护插件系统的关键。

### 验收标准

- plugin module 可向 prompt_render 注入 section。
- phase 排序可测试。
- 缺失 requires 时给出明确错误。
- 插件失败不会破坏主回复。
- plugin prompt section 能进入 system 或 context frame。

## 7. 下一阶段 E：Proactive / Drift / Scheduler

### 目标

迁移 Akashic 的主动系统，但不要让它污染被动回复主链。Proactive 和 drift 应该是独立 runtime，共享 memory / tools / provider。

### Akashic 参考

- `_handbook/proactive-guide.md`
- `_handbook/drift-guide.md`
- `proactive_v2/*`
- `agent/core/proactive_turn.py`
- `agent/core/drift_turn.py`
- `agent/scheduler.py`
- `agent/tools/schedule.py`

### 建议迁移顺序

1. 先实现 scheduler store 和 fire-at parser。
2. 实现 proactive source 协议，但先用 fake source。
3. 实现 proactive gateway：alert / content / context 三路预取。
4. 实现 proactive decision loop，但只允许 skip / draft，不直接发送。
5. 接入 outbound port 后再允许 message_push。
6. drift 最后做，因为它需要工具、workspace、状态文件和 finish 协议。

### 关键 tradeoff

- Proactive 价值高，但容易引入打扰用户和误推送风险。
- Drift 更像用户可编程后台 agent，需要 tool safety 先成熟。
- 建议：scheduler → gateway → dry-run proactive → outbound → drift。

### 学习重点

- 主动系统不是“被动回复加定时器”，而是独立 agent。
- alert / content / context 的优先级不同。
- 推送系统必须有 gate、quota、dedupe、ack。

### 验收标准

- scheduler 能稳定触发 fake task。
- proactive dry-run 能分类 content。
- 无 alert/content 时不乱推。
- outbound 发送前经过 gate / quota。
- drift skill 必须显式 finish。

## 8. 下一阶段 F：Dashboard / Observability / Eval

### 目标

把 runtime 变成可观察、可调试、可回滚的系统。

### Akashic 参考

- `bootstrap/dashboard_api.py`
- `plugins/observe/*`
- `plugins/default_memory/dashboard*`
- `eval/personamem/*`
- `eval/longmemeval/*`
- `core/common/strategy_trace.py`

### 建议迁移顺序

1. 先做 CLI/debug inspect，不急着做前端 dashboard。
2. 暴露 session / memory / prompt / tool trace 查询 API。
3. 加 memory optimizer manual trigger。
4. 加 recall/debug trace。
5. 最后做 eval harness。

### 学习重点

- agent 系统失败常发生在链路中间，不是最终回复。
- 可观测性要记录“为什么这样路由/检索/裁剪/拒绝”。
- eval 不是只测最终答案，也测记忆是否该写、是否该忘、是否该回源。

### 验收标准

- 能查看某次 turn 的 prompt sections。
- 能查看 retrieval trace。
- 能查看 consolidation source_ref。
- 能手动触发 optimizer。
- eval 能跑一组 memory cases。

## 9. 推荐总顺序

```text
已完成：
1. Prompt / Context
2. Session / Event / Provider
3. Markdown Memory + Optimizer
4. Runtime Bootstrap / 正式 CLI 入口

下一步：
5. Vector Memory + Retrieval Evidence
6. Tool Runtime + Hooks
7. Passive Agent Loop
8. Lifecycle + Plugin System
9. Scheduler
10. Proactive
11. Drift
12. Dashboard / Observability
13. Eval
```

为什么这样排：

- 记忆检索必须依赖 session source_ref。
- tool loop 必须依赖 provider、tool registry、session history。
- plugin lifecycle 必须依赖稳定 loop，否则插入点会反复变。
- proactive / drift 必须依赖 tools、memory、scheduler、outbound safety。
- dashboard / eval 应贯穿后半程，但不应在核心协议未稳时过早固化。

## 10. 如果你自己做，前三步

1. 先画当前阶段的数据流，不看代码细节：

```text
input → context → provider → commit → memory/event/tool
```

2. 再找 Akashic 对应的最小参考文件，不要打开整个目录。

3. 最后写验收测试，再迁实现。

新手常见错误：

- 看到 Akashic 有完整目录，就想整体搬。
- 把 prompt、memory、tool、plugin 同时改，最后不知道失败点在哪。
- 把 LLM summary 当事实，不保留 source_ref。
- 把用户事实写进 SELF.md。
- 把 context frame 当作真实用户消息持久化。

资深工程师会优先观察：

- source of truth 在哪里。
- 哪些内容会自动写入。
- 写入失败如何回滚。
- 模型输入和持久化历史是不是同一个东西。
- 每个阶段有没有独立验收测试。
