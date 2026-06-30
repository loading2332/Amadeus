Status: ready-for-agent
Label: ready-for-agent

# 增加 CLI trace 与真实 LLM smoke 路径

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

增强 CLI，使 Phase 1 的普通对话和多步文件工具 agent loop 可以被手动演示。CLI 应支持 trace 展示模式，输出 session key、message IDs、sessions DB path、exposed tools、context retry/trim 信息、provider model/usage、tool_chain、guard/denied/error 状态。

同时记录两条真实 LLM smoke 路径：普通对话 smoke，以及多步文件工具 smoke。多步 smoke 应要求模型写入 `runtime-artifacts/` 下的文件，读回验证内容，然后给出最终总结。

## Acceptance criteria

- [ ] CLI 支持普通对话运行，并能显示 session key、user_message_id、assistant_message_id。
- [ ] CLI trace 模式能显示 exposed tools 和 context retry/trim 信息。
- [ ] CLI trace 模式能显示 tool_chain，包括每个工具调用的 name、arguments、status、result preview。
- [ ] CLI trace 模式能显示 provider model/usage 或在 provider 不返回时明确为空。
- [ ] CLI trace 模式能显示 sessions DB path，证明 SQLite session persistence 的位置。
- [ ] 文档或命令说明包含普通真实 LLM smoke。
- [ ] 文档或命令说明包含多步文件工具真实 LLM smoke：写 artifact、读回、验证、最终总结。
- [ ] smoke 默认关闭 vector memory retrieval，不要求 embedding 或 AM-Base。
- [ ] 自动测试覆盖 CLI trace formatting 的确定性字段，不要求真实网络调用。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/04-reasoner-multistep-tool-loop-trace.md`
- `.scratch/phase-1-akashic-passive-runtime/issues/05-tool-loop-guard-progress-summary.md`
