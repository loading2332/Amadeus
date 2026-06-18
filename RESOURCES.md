# Amadeus / Akashic 学习资源

## Knowledge

### Local: Akashic Reference Sources

- Local source: `../akashic-agent/agent/provider.py`
  Akashic provider 边界。用于：理解模型响应如何被归一成文本回复、tool call 请求和错误。
- Local source: `../akashic-agent/agent/core/types.py`
  Akashic 核心运行时类型。用于：理解 `ToolCall`、`LLMResponse`、`ReasonerResult`、trace metadata 等公共语言。
- Local source: `../akashic-agent/agent/core/passive_turn.py`
  Passive Reasoner 主循环。用于：理解多步 `LLM -> tool -> LLM` loop、步数上限、阶段性回复和失败边界。
- Local source: `../akashic-agent/agent/tool_runtime.py`
  Tool message 回灌辅助函数。用于：理解 `assistant(tool_calls)` 和 `tool(result)` 的协议顺序。
- Local source: `../akashic-agent/agent/tool_hooks/types.py`
  Tool hook 请求/结果结构。用于：理解 hook 为什么要和具体 tool 实现解耦。
- Local source: `../akashic-agent/agent/tool_hooks/executor.py`
  Tool hook 执行器。用于：理解 Akashic 的工具执行 trace、前后处理、deny 和异常收口路径。
- Local source: `../akashic-agent/agent/prompting/assembler.py`
  Prompt section 组装边界。用于：理解 system prompt、context frame、动态 section 的分层。
- Local source: `../akashic-agent/agent/prompting/budget.py`
  Context trim plan 定义。用于：理解超长上下文时为什么按计划逐级降载，而不是临时删消息。
- Local source: `../akashic-agent/agent/context.py`
  Akashic context 构建入口。用于：理解 memory、retrieval、prompt block 如何进入当前 turn 的上下文。
- Local source: `../akashic-agent/agent/retrieval/protocol.py`
  Retrieval pipeline 协议。用于：理解记忆检索为什么要输出 block、trace 和 metadata。
- Local source: `../akashic-agent/agent/retrieval/default_pipeline.py`
  默认检索流程。用于：理解 retrieval request 如何变成 prompt 可消费的 retrieved memory。
- Local source: `../akashic-agent/agent/tools/recall_memory.py`
  记忆召回工具。用于：Lesson 14-18 对照把 retrieval 暴露成正式 tool。
- Local source: `../akashic-agent/agent/tools/forget_memory.py`
  记忆遗忘工具。用于：理解删除、撤销和 source_ref 稳定性边界。
- Local source: `../akashic-agent/agent/tools/message_lookup.py`
  消息回源工具。用于：理解 evidence/source_ref 如何回到原始 session message。
- Local source: `../akashic-agent/agent/tools/schedule.py`
  schedule tool。用于：理解定时任务如何从 tool 层进入 scheduler。
- Local source: `../akashic-agent/agent/scheduler.py`
  scheduler 时间解析与触发计算。用于：Lesson 24-27 对照实现计划任务存储、fire-at 和重复触发边界。
- Local source: `../akashic-agent/agent/turns/outbound.py`
  outbound turn 结果边界。用于：理解主动发送链路为什么要和 passive reply 分离。
- Local source: `../akashic-agent/agent/turns/orchestrator.py`
  turn orchestration 入口。用于：理解 passive/proactive/outbound 结果如何统一提交和派发。
- Local source: `../akashic-agent/agent/core/proactive_turn.py`
  proactive 顶层链路。用于：Lesson 28-32 理解 source contract、pregate、judge、draft 和发送边界。
- Local source: `../akashic-agent/agent/core/drift_turn.py`
  drift 顶层链路。用于：Lesson 33-35 理解后台空闲任务的 scan、prepare、execute、finish 主链。
- Local source: `../akashic-agent/agent/lifecycle/facade.py`
  生命周期 facade。用于：理解 phase 执行如何成为 plugin 的稳定入口。
- Local source: `../akashic-agent/agent/lifecycle/types.py`
  生命周期上下文类型。用于：理解 phase 间传递哪些数据，不靠直接 import 主链内部对象。
- Local source: `../akashic-agent/agent/lifecycle/phases/`
  before/after/prompt render 等 phase 实现。用于：Lesson 19-23 对照拆解 lifecycle mini-core。
- Local source: `../akashic-agent/agent/plugins/manager.py`
  plugin manager。用于：理解插件加载、初始化和 hook 汇聚边界。
- Local source: `../akashic-agent/agent/plugins/registry.py`
  plugin registry。用于：理解插件发现与注册为什么要和 runtime 主链解耦。
- Local source: `../akashic-agent/agent/mcp/`
  MCP 相关实现。用于：后续理解外部 tool/resource 接入与本地 tool runtime 的关系。
- Local tests: `../akashic-agent/tests/test_tool_executor.py`
  Tool hook/executor 行为测试。用于：验证 deny、参数改写、hook 异常和 post hook 不污染成功结果。
- Local tests: `../akashic-agent/tests/test_loop_tool_visibility.py`
  Tool 可见性与 loop 行为测试。用于：理解 deferred tool、tool_search 和 loop 中工具暴露边界。
- Local tests: `../akashic-agent/tests/test_tool_loop_guard.py`
  Tool loop guard 测试。用于：理解工具循环失控时的安全边界。
- Local tests: `../akashic-agent/tests/test_safety_retry_service.py`
  Context-length retry 测试。用于：Lesson 12 对照实现超长上下文后的 trim/retry。
- Local tests: `../akashic-agent/tests/test_recall_memory_tool.py`
  recall memory tool 测试。用于：验证 memory tool 的输入、输出、证据链和失败路径。
- Local tests: `../akashic-agent/tests/test_forget_memory_tool.py`
  forget memory tool 测试。用于：验证遗忘语义、撤销边界和删除安全。
- Local tests: `../akashic-agent/tests/test_message_lookup_tool.py`
  message lookup tool 测试。用于：验证 evidence/source_ref 回源链。
- Local tests: `../akashic-agent/tests/test_schedule_tool.py`
  schedule tool 测试。用于：验证计划任务 tool 的参数、错误和 scheduler 接入。
- Local tests: `../akashic-agent/tests/test_scheduler_service.py`
  scheduler service 测试。用于：验证定时触发、状态推进和重复触发边界。
- Local tests: `../akashic-agent/tests/test_time_parsing.py`
  时间解析测试。用于：Lesson 24 的 fire-at parser 对照。
- Local tests: `../akashic-agent/tests/test_turn_pipelines.py`
  turn pipeline 测试。用于：理解 lifecycle、retrieval、runner 和 turn processing 如何组合。
- Local tests: `../akashic-agent/tests/turns/test_orchestrator.py`
  turn orchestrator 测试。用于：理解 proactive/outbound 提交、派发和成功副作用。
- Local tests: `../akashic-agent/tests/proactive_v2/`
  proactive v2 测试集合。用于：Lesson 28-32 对照 pregate、post guard、ack、message quality 和 integration。
- Local tests: `../akashic-agent/tests/proactive_v2/test_drift.py`
  drift 行为测试。用于：Lesson 33-35 对照后台任务协议和 finish 边界。
- Local tests: `../akashic-agent/tests/test_agent_core_p2_reasoner.py`
  早期 reasoner 行为测试。用于：回看被动 reasoner 的工具生命周期和 loop 主线。
- Local tests: `../akashic-agent/tests/test_agent_core_p3_context_store.py`
  context store 测试。用于：理解 retrieval/context prepare 的输入输出。
- Local tests: `../akashic-agent/tests/test_agent_core_p4_prompt_block.py`
  prompt block 测试。用于：理解 prompt section 顺序、禁用和渲染边界。
- Local tests: `../akashic-agent/tests/test_agent_core_p6_runner.py`
  runner 测试。用于：理解 scheduler job 等非用户入口如何复用 turn runner。
- Local tests: `../akashic-agent/tests/test_agent_core_p7_commit.py`
  commit/lifecycle 测试。用于：理解 reasoning 结果如何经过 lifecycle 写回 session。

### Local: Amadeus Implementation Sources

- Local source: `amadeus/context.py`
  Amadeus prompt/context 构建主入口。用于：对照 Akashic context builder、history window、context frame 和 disabled sections。
- Local source: `amadeus/prompting/assembler.py`
  Amadeus prompt assembly。用于：理解 system prompt 与 context frame 的当前复现边界。
- Local source: `amadeus/prompting/budget.py`
  Amadeus context trim attempts。用于：Lesson 12 对照接入 passive runtime 的 retry 主链。
- Local source: `amadeus/provider.py`
  Amadeus provider 响应结构。用于：Lesson 8-13 对照文本回复、tool call、context-length error 的边界。
- Local source: `amadeus/runtime.py`
  Amadeus passive runtime。用于：理解当前主链、tool loop、iteration limit、session 写入和后续扩展点。
- Local source: `amadeus/tool_runtime.py`
  Amadeus tool message 回灌工具。用于：对照 Akashic `tool_runtime.py` 的协议顺序。
- Local source: `amadeus/tools/base.py`
  Tool 基础 contract。用于：理解 Amadeus 当前 tool 输入、schema、风险等级和执行结果形状。
- Local source: `amadeus/tools/registry.py`
  Tool registry。用于：理解“有哪些工具”和“怎么执行工具”的职责拆分。
- Local source: `amadeus/tools/executor.py`
  Tool executor。用于：理解 hook、deny、error trace 和执行边界的当前实现。
- Local source: `amadeus/tools/defaults.py`
  默认只读工具集合。用于：Lesson 5 对照低风险工具如何进入 runtime。
- Local source: `amadeus/session.py`
  Session 与 history 边界。用于：理解哪些消息属于用户真实历史，哪些只是 runtime 中间态。
- Local source: `amadeus/memory.py`
  Markdown memory。用于：理解可读记忆源如何进入 context。
- Local source: `amadeus/vector_memory.py`
  Vector memory。用于：Lesson 14-18 对照 retrieval、evidence 和 fallback。
- Local source: `amadeus/memory_engine.py`
  Memory engine API。用于：理解 memory/retrieval 如何被 runtime 注入而不是硬编码。
- Local source: `amadeus/bootstrap.py`
  App composition 入口。用于：理解 provider、runtime、tool registry、memory engine 如何装配。
- Local source: `amadeus/events.py`
  当前事件类型。用于：后续 observability、trace 和 dashboard 前先看已有观测面。
- Local source: `dev_utils/inspect_context.py`
  context inspection helper。用于：手动验证 prompt/context/frame 渲染结果。
- Local source: `dev_utils/run_context_llm.py`
  context LLM debug helper。用于：验证真实 provider 入口前的上下文构造。
- Local tests: `tests/test_context_builders.py`
  Context builder 测试。用于：验证 prompt section、history slicing、context frame 和 disabled sections。
- Local tests: `tests/test_prompt_assembler.py`
  Prompt assembler 测试。用于：验证 system/context frame 分流规则。
- Local tests: `tests/test_prompt_budget.py`
  Prompt budget 测试。用于：验证 trim plan 和 history window 组合。
- Local tests: `tests/test_provider.py`
  Provider 基础测试。用于：验证 fake provider、tool call response 和错误边界。
- Local tests: `tests/test_openai_provider.py`
  OpenAI provider adapter 测试。用于：验证真实 API 形状适配与 context-length error 识别。
- Local tests: `tests/test_runtime.py`
  Passive runtime 测试。用于：验证无工具、多工具、工具失败、iteration limit 和 tool chain 持久化。
- Local tests: `tests/test_session_tool_chain_history.py`
  Tool chain history 测试。用于：验证 tool trace 如何在历史中重建给后续 turn 使用。
- Local tests: `tests/test_tool_registry.py`
  Tool registry 测试。用于：验证工具注册、查找和 schema 导出。
- Local tests: `tests/test_tool_executor.py`
  Tool executor 测试。用于：验证 hook pipeline、deny、error 和 trace。
- Local tests: `tests/test_readonly_tools.py`
  只读工具测试。用于：验证默认工具的低风险 contract。
- Local tests: `tests/test_bootstrap_tool_runtime.py`
  Bootstrap tool runtime 测试。用于：验证 composition 层已经暴露 tool runtime 能力。
- Local tests: `tests/test_runtime_vector_memory.py`
  Runtime vector memory 测试。用于：验证 retrieval injection 与 runtime failure fallback。
- Local tests: `tests/test_session_memory_runtime.py`
  Session memory runtime 测试。用于：验证 session/history/memory 组合路径。
- Local tests: `tests/test_vector_memory.py`
  Vector memory 底层测试。用于：验证 ingest、dedupe、retrieval 和 evidence。
- Local tests: `tests/test_debug_context_llm.py`
  Context debug helper 测试。用于：保证教学和手动验证工具不漂移。

### External: Agent Architecture

- [Article: "Building Effective AI Agents" - Anthropic](https://www.anthropic.com/research/building-effective-agents)
  权威 agent 架构文章。用于：判断什么时候用 workflow，什么时候需要 agent loop，以及为什么保持简单可组合。
- [Article: "Effective Context Engineering for AI Agents" - Anthropic](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
  上下文工程参考。用于：理解 just-in-time context、外部索引、动态加载和 context pressure。

### External: Tool Calling / Tool Design

- [Guide: "Function Calling" - OpenAI API](https://developers.openai.com/api/docs/guides/function-calling)
  Tool calling 协议主链。用于：对照 Lesson 8-13 的 tool call、应用侧执行和 tool result 回灌。
- [Guide: "Using Tools" - OpenAI API](https://developers.openai.com/api/docs/guides/tools)
  OpenAI tools 总览。用于：理解内置工具、function tools、remote MCP 和工具能力边界。
- [Article: "Writing Effective Tools for Agents" - Anthropic](https://www.anthropic.com/engineering/writing-tools-for-agents)
  工具设计工程文章。用于：Lesson 2-18 之后优化工具描述、工具边界和工具 eval。

### External: MCP / Plugin Boundaries

- [Specification: "Model Context Protocol" - MCP](https://modelcontextprotocol.io/specification/2025-06-18)
  MCP 官方规范。用于：理解 tools、resources、prompts 的协议分工，以及 host/client/server 边界。
- [Specification: "Tools" - MCP](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
  MCP tool 规范。用于：Lesson 19-23 对照工具发现、工具 schema 和 model-controlled invocation。

### External: Observability / Evals

- [Guide: "Agents SDK" - OpenAI API](https://developers.openai.com/api/docs/guides/agents)
  OpenAI agent runtime 参考。用于：理解 orchestration、tool execution、approvals 和 state ownership。
- [Guide: "Tracing" - OpenAI Agents SDK](https://openai.github.io/openai-agents-python/tracing/)
  Agent tracing 参考。用于：Lesson 36-38 设计 LLM、tool call、handoff、guardrail 和 custom event 的观测面。
- [Guide: "Evaluation best practices" - OpenAI API](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
  Eval 设计参考。用于：Lesson 39-40 思考行为级测试、样本集、grader 和回归防护；具体平台/API 状态进入该阶段前再以官方文档复核。
- [Article: "Demystifying evals for AI agents" - Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
  Agent eval 工程文章。用于：把 smoke case 升级成可复跑、可解释、能暴露行为漂移的 eval。

## Wisdom (Communities)

- 当前阶段先以本地源码、测试和官方文档为主
  用途：降低学习噪音，先把 Akashic 与 Amadeus 主链讲清。社区型资源等到后续需要扩展 transport、生态插件或对外发布时再补。
- Future option: OpenAI Developer Community
  用途：后续遇到 OpenAI provider/tool/eval 平台行为不明确时，可用于查官方讨论和已知问题；当前不作为课程主线资源。
- Future option: MCP GitHub / specification discussions
  用途：后续实现 MCP 或 plugin 生态边界时，可用于确认规范变更；当前只以官方 specification 页面为准。

## Gaps

- 还没有一份稳定的 Akashic glossary / 调用链速查文档。
- 还没有按 Lesson 1-40 建立“Lesson -> Akashic 文件 -> Amadeus 文件 -> 验证命令 -> 外部资源”的完整矩阵。
- 还没有行为级 eval/smoke case 索引页，后续要随着每节课把 smoke seed 沉淀出来。
- 还没有 observability / trace 本地实现后的资源回链；进入 Lesson 36-38 后需要补 Amadeus trace 文件与检查入口。
- Scheduler / proactive / drift 阶段虽然已经有 Akashic 顶层入口，但具体调用链和关键测试还需要进入对应 Lesson 前再做细粒度源码定位。
