Status: ready-for-agent
Label: ready-for-agent

# PRD：Phase 1 Akashic-Style Passive Agent Runtime

## Problem Statement

Amadeus 的目标是成为可以写进简历、可以演示、可以在面试里被追问的 AI agent 项目。当前 Phase 1 如果只证明一次 chat completion 能跑，证据强度不够。用户需要的是一个能对齐 Akashic 设计、能真实运行、能解释失败边界的被动 agent runtime。

当前仓库已经有重要基础：`PassiveRuntime`、lifecycle phases、SQLite session persistence、tool registry/executor、session read-only tools、prompt/context assembly，以及后续 Phase 2 会用到的 memory 代码。问题是 Phase 1 不能停留在“调用一次 provider”，而应该交付“后续 memory、eval、outbound、proactive、drift 都能依赖的被动 AgentCore 基座”。

## Solution

Phase 1 实现 Amadeus 的 Akashic-style passive agent runtime slice。它默认关闭 memory retrieval，聚焦被动运行基座：真实 OpenAI-compatible chat provider、普通对话、独立 Reasoner、多步 tool loop、文件工具、filesystem policy hooks、loop guard、SQLite session commit、可展示 trace。

实现时必须参考 Akashic 的 passive runtime、reasoner/tool loop、filesystem tools、hook model、loop guard 行为。迁移的是契约、数据流和失败边界，不是照搬 Akashic 的目录结构或历史包袱。

Phase 1 完成时，Amadeus 应能通过真实 LLM 跑一个被动 turn：模型执行多步文件工具链，写入 `runtime-artifacts/` 下的文件，读回验证内容，返回最终总结，把 user/assistant turn 持久化到 SQLite session，并输出 tool-chain trace。

## User Stories

1. As a project owner, I want Phase 1 to implement an Akashic-style passive runtime, so that my resume claim is backed by real code rather than a thin chat wrapper.
2. As a project owner, I want Amadeus to run a real OpenAI-compatible LLM turn, so that I can demonstrate the runtime with a real provider.
3. As a project owner, I want ordinary chat to work without tools, so that the passive runtime has a baseline conversation path.
4. As a project owner, I want the LLM/tool loop to support tool calls, so that Amadeus behaves like an agent rather than a single reply bot.
5. As a project owner, I want the Reasoner extracted from the passive runtime, so that lifecycle orchestration and reasoning/tool execution have separate responsibilities.
6. As an interviewer, I want to see where context preparation ends and reasoning begins, so that the architecture has defensible module boundaries.
7. As an interviewer, I want to see that Amadeus references Akashic's passive turn design, so that the migration claim is concrete.
8. As an interviewer, I want the runtime to support multi-step tool chains, so that the system demonstrates iterative agent behavior.
9. As a project owner, I want `list_dir`, `read_file`, `write_file`, and `edit_file` tools, so that Phase 1 can demonstrate real file-based agent work.
10. As a project owner, I want file tools to follow Akashic-style `allowed_dir` boundaries, so that path safety is enforced inside the tools.
11. As a project owner, I want runtime hooks to enforce global filesystem policy, so that tool execution has a centralized security boundary.
12. As a project owner, I want reads and directory listing to cover the Amadeus workspace, so that the agent can inspect project context during a turn.
13. As a project owner, I want writes and edits to default to `runtime-artifacts/`, so that real LLM smoke tests cannot silently alter source code.
14. As a project owner, I want attempts to write outside the allowed artifact area to be denied, so that dangerous paths are handled predictably.
15. As a project owner, I want path normalization for relative and absolute paths, so that tool behavior is consistent across CLI usage and model-generated arguments.
16. As a project owner, I want denied tool calls recorded in traces, so that safety behavior is visible rather than hidden.
17. As a project owner, I want file writes and edits to use a file-level mutation lock, so that concurrent writes cannot corrupt the same target.
18. As a project owner, I want `read_file` to support pagination or truncation, so that reading large files does not explode the context.
19. As a project owner, I want `edit_file` to require exact old-text matching, so that model edits do not accidentally modify the wrong text.
20. As a project owner, I want `edit_file` to report ambiguous multiple matches, so that precision is required before broad replacement.
21. As a project owner, I want `edit_file` to return a diff summary, so that edits can be audited from the tool result.
22. As a project owner, I want `write_file` to create parent directories when allowed, so that artifact creation is ergonomic.
23. As a project owner, I want `write_file` to be treated as full overwrite, so that its semantics are clear and distinguishable from `edit_file`.
24. As a project owner, I want the tool loop to support multiple iterations, so that the model can write, read, verify, and then answer.
25. As a project owner, I want the tool loop to support multi-tool batches, so that it can handle providers that return more than one tool call at a step.
26. As a project owner, I want assistant tool-call messages and tool result messages to be reconstructed correctly, so that follow-up LLM calls remain provider-compatible.
27. As a project owner, I want a loop guard to detect repeated calls, so that the agent does not spin forever on the same tool request.
28. As a project owner, I want guard-triggered stops to produce a useful progress summary, so that failed tool loops still produce an explainable result.
29. As a project owner, I want max-iteration stops to preserve the completed tool chain, so that debugging evidence is not lost.
30. As a project owner, I want provider usage and model metadata captured when available, so that real smoke runs have observable integration evidence.
31. As a project owner, I want SQLite session persistence to remain the source for committed turns, so that message IDs and source references are stable.
32. As a project owner, I want tool-chain data persisted with the assistant message, so that later turns can rebuild the conversation history.
33. As a project owner, I want CLI output to optionally show trace details, so that I can demonstrate the runtime in an interview.
34. As a project owner, I want CLI trace output to include session key and message IDs, so that persistence is visible.
35. As a project owner, I want CLI trace output to include exposed tools, so that the difference between chat and agent loop is visible.
36. As a project owner, I want CLI trace output to include context retry or trim details, so that prompt handling is visible.
37. As a project owner, I want CLI trace output to include the tool chain, so that the multi-step file workflow can be inspected.
38. As a project owner, I want deterministic fake-provider tests for ordinary chat, so that normal conversation does not depend on network credentials.
39. As a project owner, I want deterministic fake-provider tests for a write/read tool loop, so that the agent loop is regression-tested.
40. As a project owner, I want hook tests for path escape, write-denial, and allowed artifact writes, so that security policy is not just prose.
41. As a project owner, I want Reasoner unit tests, so that tool loop behavior can be verified without the full passive pipeline.
42. As a project owner, I want integration tests at the passive runtime seam, so that lifecycle, Reasoner, commit, and trace work together.
43. As a project owner, I want a real LLM smoke command for ordinary chat, so that provider integration is demonstrable.
44. As a project owner, I want a real LLM smoke command for multi-step file tools, so that Phase 1's headline behavior can be demonstrated.
45. As a project owner, I want Phase 1 to explicitly exclude memory retrieval, so that Phase 2 can focus on Markdown and vector memory without mixed failure causes.
46. As a project owner, I want Phase 1 docs to distinguish session SQLite from vector-memory SQLite, so that interview wording stays accurate.
47. As a project owner, I want the Phase 1 implementation to leave outbound, Telegram, scheduler, proactive, and drift boundaries untouched, so that architecture order remains clean.
48. As a future implementer, I want a PRD that states test seams and scope clearly, so that implementation can proceed without another requirements interview.

## Implementation Decisions

- Phase 1 服从当前路线图的依赖顺序：先被动 runtime，再 memory system。
- Phase 1 是 Akashic-style passive agent runtime，不是一次 chat completion wrapper。
- passive runtime 保留生命周期顺序：BeforeTurn、BeforeReasoning、PromptRender、Reasoner/tool loop、AfterReasoning commit、AfterTurn。
- 将 reasoning/tool execution 从 `PassiveRuntime` 拆成独立 `Reasoner` 边界。`PassiveRuntime` 负责编排 lifecycle、context rendering、retry、commit、after-turn hooks。
- `Reasoner` 负责 prompt render 后的 provider calls、多轮 tool execution、tool result reinjection、max iteration handling、loop guard handling、reasoner-level trace metadata。
- 现有 OpenAI-compatible provider 继续作为 Phase 1 的真实 LLM 集成点。
- Phase 1 默认关闭 vector memory retrieval，不要求 AM-Base、embedding config 或 vector-memory setup。
- SQLite session persistence 已经存在，并继续作为 Phase 1 证据。实现应通过 trace/smoke 更清楚地展示 session DB、message IDs 和 source references。
- 文件工具集包含 `list_dir`、`read_file`、`write_file`、`edit_file`。
- 文件工具参考 Akashic：allowed directory resolution、path escape rejection、read limits、exact edit matching、diff output、file-level mutation lock。
- 文件安全采用 defense-in-depth：工具自身有 `allowed_dir`，runtime hooks 再执行全局策略。
- 默认 read/list policy 允许访问 Amadeus workspace。
- 默认 write/edit policy 只允许写入 `runtime-artifacts/`。
- 真实 LLM 默认不能修改源码。未来如果需要源码编辑模式，必须通过配置或 CLI 显式开启。
- hook denial 必须生成 tool trace status，不能只是未结构化异常。
- tool-chain trace 字段需要稳定到足以展示和测试：iteration、assistant text、calls、call ID、tool name、arguments、status、result preview、denial/error reason。
- loop guard 参考 Akashic guard concept：重复 tool signatures 和 no-progress loops 必须在 provider 消耗无限 iterations 之前停止。
- guard stop 和 max-iteration stop 应返回基于已完成 tool_chain evidence 的用户可读进度总结。
- CLI 需要支持 trace 展示模式，用于面试演示 runtime evidence。
- 真实 LLM smoke 任务应要求模型写入 `runtime-artifacts/` 下的文件，读回，验证一致性，并返回最终答复。
- Phase 1 文档需要说明哪些 Akashic contracts 已迁移，哪些明确延后。

## Testing Decisions

- 测试优先验证公开行为和 runtime seams，避免只测私有 helper。
- Phase 1 的最高测试 seam 是 passive runtime `run_turn`，使用 fake provider 和真实 tool registry/executor。
- 抽出的 `Reasoner` 可以作为更低一层 seam 单独测试，因为它承担 provider/tool loop 的核心行为。
- 文件工具需要直接测试，因为 path handling、truncation、exact matching、diff output 是工具契约。
- filesystem hooks 需要直接测试，因为它们负责 runtime policy 和 denial semantics。
- session persistence 应通过 committed turns 和 reloaded session history 测试，而不是只读数据库内部。
- deterministic fake-provider tests 必须覆盖 ordinary chat、single tool call、multi-step write/read loop、multi-tool batch、unknown tool、denied tool、repeated loop guard、max-iteration summary。
- integration tests 必须覆盖 passive runtime ordinary reply、passive runtime tool loop commit、tool_chain persistence、CLI trace-friendly result fields。
- 现有 bootstrap、runtime、tool executor、readonly tools、session memory runtime 测试可作为先例。
- real LLM smoke 不进入默认 CI，但应作为手动验证命令记录。它验证 provider compatibility 和真实模型 tool-call behavior。
- ordinary chat smoke 失败意味着 provider 或 prompt/commit integration 退化。
- tool-loop smoke 失败意味着 function-calling、tool execution、reinjection 或 final response synthesis 退化。
- hook tests 失败意味着 runtime safety boundary 不足以支撑真实 LLM 执行。
- session persistence tests 失败意味着 traceability 和 stable message IDs 的面试说法不安全。

## Out of Scope

- AM-Base integration 不属于 Phase 1。
- Markdown memory optimization 和长期记忆行为不属于 Phase 1。
- Vector memory、embedding、retrieval ranking、recall、forgetting、correction、source-backed memory eval 不属于 Phase 1。
- 产品化 Evaluation runner 不属于 Phase 1，但 Phase 1 必须让行为可被后续 eval cases 覆盖。
- Telegram outbound、`OutboundPort`、Scheduler、ProactiveLoop、DriftRunner 不属于 Phase 1。
- Deferred tool discovery 和 `tool_search` 默认不属于 Phase 1，除非实现中发现直接必要性。
- 全量搬迁 Akashic 目录结构不属于 Phase 1。目标是迁移 contracts、boundaries 和 behavior。
- 默认允许真实 LLM 编辑项目源码不属于 Phase 1。

## Further Notes

这个 PRD 明确把 Phase 1 提升到 interview-grade evidence，而不是最小 smoke。目标是一个真实可运行的 passive agent runtime：lifecycle boundaries、independent Reasoner、file tools、safety hooks、loop protection、SQLite persistence、traceable behavior。

Phase 2 应在这个基座上接入 Markdown memory 和 vector memory retrieval。Phase 1 不应混淆这些关注点。
