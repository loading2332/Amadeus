Status: ready-for-agent
Label: ready-for-agent

# 实现 Akashic-inspired tool loop guard 和收束摘要

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

参考 Akashic 的 tool loop guard 思路，为 Amadeus 的 Reasoner 增加循环保护。系统应识别重复 tool signature、重复无进展调用、超过最大 iteration 的工具循环，并在失控前停止。停止时不能丢失已有证据，应保留 completed tool_chain，并返回用户可读的阶段性进度总结。

这个 slice 的目标是把 agent loop 的失败边界变成面试可讲的设计：模型可以调用工具，但 runtime 有 guard、trace 和收束策略。

## Acceptance criteria

- [ ] guard 能识别重复 tool name + normalized arguments 的调用序列。
- [ ] guard 能处理 repeated multi-tool batch，不留下未闭合 tool-call history。
- [ ] 达到 max tool iterations 时，Reasoner 停止继续请求 provider。
- [ ] guard stop 和 max-iteration stop 都保留已完成 tool_chain。
- [ ] 返回给用户的阶段性总结基于已执行工具和结果预览，不暴露内部 schema 或原始 tool_call_id 细节。
- [ ] trace 中记录 stop reason，例如 repeated_tool_signature、no_progress 或 max_iterations。
- [ ] 测试覆盖未达到阈值时不误杀、达到阈值时停止、multi-tool batch 重复、工具结果错误后重复调用。
- [ ] 与 filesystem hook denial 共存：被拒绝的重复危险调用不会导致无限重试。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/04-reasoner-multistep-tool-loop-trace.md`
