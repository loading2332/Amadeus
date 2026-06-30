Status: ready-for-agent
Label: ready-for-agent

# 完善 Reasoner 多步工具循环和 trace

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

让独立 `Reasoner` 承担完整的多步 tool loop：向 provider 暴露 tool schemas，处理模型返回的 tool calls，执行工具，把 assistant tool-call message 和 tool result message 回灌给 provider，继续下一轮，直到得到最终 assistant reply。

这个 slice 要证明 Amadeus 不是单次 function call wrapper，而是可观察、可持久化的 agent loop。完成后，tool_chain trace 应能记录每个 iteration 的 assistant text、calls、call_id、tool name、arguments、status、result preview、denial/error reason，并随最终 assistant message 持久化，供后续 session history 重建。

## Acceptance criteria

- [ ] `Reasoner` 支持无工具最终回复、单工具调用、多轮工具调用、多工具 batch。
- [ ] `Reasoner` 正确构造 assistant tool-call message 和 tool result message，后续 provider call 兼容 OpenAI-style chat completions。
- [ ] tool execution 的 success、error、denied 状态都会进入稳定 tool_chain trace。
- [ ] 最终 assistant reply 和 tool_chain 能通过 passive runtime commit 写入 SQLite-backed session。
- [ ] 后续 turn 能从 persisted assistant message 中重建包含 tool-call/tool-result 的 session history。
- [ ] fake-provider integration test 覆盖 write -> read -> final reply 的多步工具链。
- [ ] fake-provider test 覆盖 multi-tool batch 和工具执行错误路径。
- [ ] 现有 tool registry/executor 行为保持兼容，已有工具测试不退化。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/01-extract-reasoner-ordinary-chat.md`
- `.scratch/phase-1-akashic-passive-runtime/issues/02-akashic-style-file-tools.md`
- `.scratch/phase-1-akashic-passive-runtime/issues/03-workspace-filesystem-hook-policy.md`
