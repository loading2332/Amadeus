Status: ready-for-agent
Label: ready-for-agent

# 提取 Reasoner 并保持普通对话闭环

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

把 provider 调用和 reasoning/tool-loop 责任从被动 runtime 中提取到独立 `Reasoner` 边界，同时保持现有普通对话闭环不退化。完成后，被动 runtime 仍负责 lifecycle、context render、retry、commit、after-turn hooks；`Reasoner` 负责 prompt render 之后的 provider 调用，并返回可被 commit 的结果。

这一 slice 的目标不是先实现新工具能力，而是把 Akashic-style passive pipeline 的关键边界立起来，并证明普通对话仍然能通过正式 runtime 写入 SQLite session。

## Acceptance criteria

- [ ] 普通对话仍能通过正式 passive runtime 完成 context render、provider call、assistant reply、SQLite session commit。
- [ ] `Reasoner` 成为独立可测试边界，负责 provider 调用结果到 reasoner result 的转换。
- [ ] `PassiveRuntime` 不再直接承担普通 provider call 的主要 reasoning 责任。
- [ ] 现有普通 runtime/bootstrap/session 相关测试通过，或按新边界做等价更新。
- [ ] 新增或更新测试证明普通对话在拆分后仍持久化稳定 message IDs。
- [ ] 代码和测试能说明 Phase 1 仍默认关闭 vector memory retrieval，不依赖 AM-Base 或 embedding。

## Blocked by

None - can start immediately
