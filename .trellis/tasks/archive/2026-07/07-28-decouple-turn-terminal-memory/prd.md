# 拆分回答终态与后台记忆生命周期

## Goal

让用户可见的回答终态只取决于“回答已完整生成并可靠持久化”，不再等待回答后的长期记忆抽取、去重和写入；同时保留可观察、可恢复的后台记忆处理能力。

用户价值：最后一段文字显示后，界面应立即结束生成状态并允许继续交互，记忆模型或 Embedding 的网络延迟、重试与失败不得继续占用本轮回答的可见关键路径。

## Background

- 当前 `PassiveRuntime._complete_turn()` 在流式正文结束后进入 `finalizing`，随后同步等待完整 `after_turn` 阶段。
- `after_turn.post_response` 同步调用 `MemoryEngine.run_post_response()`；生产配置使用主模型执行候选抽取，存在候选时还可能执行 Embedding、相似记忆检索和第二次主模型决策。
- `TurnWorker.run_once()` 只有在 runtime 返回后才调用 `mark_done()`，而 React 把 `finalizing` 视为活跃生成状态。
- 2026-07-28 的诊断最小复现测得：人为让 post-response 阻塞 350ms 时，“最后文字到 runtime 返回”同步增加到 353ms。
- 运行中 worker 日志显示一轮主回答请求结束后，回答后的模型请求额外持续约 7.8 秒。
- SSE 的 250ms 数据库轮询可能增加少量终态传播延迟，但不是长停顿主因；前端 `useSmoothText` 在终态到达时会立即补齐全文。
- Akashic 参考实现会在 `TurnCommitted` 后只把 `TurnIngested` 放入进程内 EventBus 队列，明确避免主回复等待 post-response；但该队列是内存态，不能满足本任务已确认的跨进程重启恢复要求。因此，异步生命周期契约参考 Akashic，PostgreSQL durable job、租约和恢复属于 Amadeus 项目扩展。

## Requirements

- R1：建立两个语义独立的生命周期：
  - 回答生命周期：生成正文、持久化用户/助手消息与回答事实、发布 turn 终态。
  - 后台记忆生命周期：抽取候选、校验来源、去重/纠错决策、写入或跳过，并记录处理结果。
- R2：只有在回答正文和成功所需的消息事实可靠持久化后，turn 才能进入 `done`；不得为了降低延迟而提前宣告一个尚未落库的回答成功。
- R3：post-response 记忆处理不得阻塞 `turn_terminal` 事件、SSE 关闭、Composer 恢复可发送状态或下一轮对话。
- R4：后台记忆处理只能通过 `MemoryEngine` 及明确的上下文契约访问记忆能力，不得绕过既有 memory boundary。
- R5：回答进入 `done` 后，后台记忆处理异常不得回滚或改写回答终态；最低限度记录独立任务状态和结构化日志，完整失败治理不属于本任务。
- R6：取消语义保持线性化：`processing -> finalizing` 仍是取消与成功提交的边界；取消成功的 turn 不得启动成功回答对应的后台记忆处理。
- R7：后台记忆处理必须作为 PostgreSQL 持久化 durable job，在进程重启后可重新发现；重复领取、worker 崩溃或重复投递不得导致同一回答的记忆副作用被无界重复执行。
- R8：保持现有公开聊天协议兼容；后台记忆 job 状态不得进入聊天 SSE payload 或前端界面，旧客户端继续只依赖现有 turn 终态完成回答交接。
- R9：用户看到最后一个回答字符后，前端必须在 500ms 内退出生成状态，包括隐藏流式光标、停止按钮恢复为发送入口并允许提交下一轮；后台记忆任务的任何状态不得占用这段预算。

## Acceptance Criteria

- [x] AC1：确定性集成测试让 post-response 记忆处理阻塞时，回答仍能先可靠落库并发布 `turn_terminal: done`，测试不等待阻塞解除。
- [x] AC2：浏览器或前端集成测试证明收到回答终态后，流式光标/停止按钮消失且 Composer 可立即再次发送，不受后台记忆处理耗时影响。
- [x] AC3：后台处理最终成功时，现有候选抽取、来源引用、去重/替换和 memory trace 语义仍有可运行测试证明。
- [x] AC4：后台处理异常时，回答保持 `done`；独立任务状态不会永久停留在不可判定的 `processing`，并有结构化日志可定位。
- [x] AC5：进程重启、stale lease 恢复或重复调度场景证明：同一 turn 只产生一个 durable job，job 输入固定为本轮消息，重复执行不产生破坏性记忆副作用。
- [x] AC6：取消与 finalization 竞态测试继续通过，且 cancelled/failed turn 不会误触发成功回答的后台记忆任务。
- [x] AC7：聚焦单元/集成测试、turn streaming 测试、memory 测试和相关前端测试全部通过；共享协议变化时补跑 E2E。
- [x] AC8：真实浏览器链路或等价的可控端到端计时证明，从最后一个回答字符可见到界面退出生成状态不超过 500ms；测试中的后台记忆处理保持阻塞，证明该指标不依赖其完成。

## Out of Scope

- 本任务不改变记忆候选的提示词、分类规则、排序算法或去重质量策略。
- 本任务不以关闭长期记忆或改用更快模型作为根因修复；这些只能作为独立优化。
- 本任务不直接建设 Telegram、Scheduler、ProactiveLoop 或 DriftRunner。
- 本任务不提供后台记忆任务的 CLI、管理 API、管理界面、人工重放或完整的失败重试/告警策略；这些在实际运营需要明确后另立任务。
