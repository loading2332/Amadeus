# 实现回答增量流式链路

## Goal

为 Amadeus 建立可恢复、可观察、与前端框架无关的回答增量流式链路，使 Web 客户端能在 turn 完成前持续获得回答正文，同时保留最终完整答案作为权威结果。

本任务依赖 `07-18-owner-scoped-web-identity` 完成；流式查询、SSE 和取消端点必须沿用服务器注入的 owner identity。

## Background

- 当前 `LLMProvider.chat()` 等待完整 Chat Completions 响应后才返回 `LLMResponse`（`amadeus/provider.py:86-139`）。
- `Reasoner` 和 `PassiveRuntime` 只消费完整响应，`TurnWorker` 只在 runtime 完成后调用 `mark_done()` 一次性写入答案。
- API 与 worker 是独立进程，现有 SSE 通过轮询 PostgreSQL turn 状态工作；进程内回调无法独立支持浏览器重连。
- Akashic 的对应设计由 provider 产生 `content_delta/thinking_delta`，通过 runtime stream sink/event 交给 channel，同时累计最终回复；Amadeus 迁移其边界思想，不照搬 session key 或 Telegram 实现。

## Requirements

- R1. Provider 支持在仍返回最终 `LLMResponse` 的同时，以异步回调发布回答正文增量。
- R2. Reasoner/PassiveRuntime 负责把增量输出交给显式 stream sink，核心 runtime 不依赖 FastAPI、SSE 或 React。
- R3. Worker 使用 `turn_id` 把增量关联到当前 turn，并通过 PostgreSQL 共享状态使独立 API 进程可以观察。
- R4. 增量持久化采用累计快照和单调序号/版本，按时间或字符阈值批量刷新，避免逐 token 数据库写入。
- R5. SSE 支持首次订阅与断线重连；客户端能够从最新累计快照继续，不重复拼接已经收到的正文。
- R6. `done` 的最终答案是权威结果，并与已发布增量收口一致；`failed` 保留明确错误和可识别的非完整部分输出。
- R7. 工具调用轮次不得把工具参数、工具结果或模型内部推理误当作最终回答正文发布。
- R8. 产品流式契约只公开面向用户的最终回答 `content_delta`；原始 `thinking_delta`、chain-of-thought 和供应商私有推理字段不得持久化为可展示消息或通过 Web SSE 暴露。
- R9. MVP 通过统一的 typed event envelope 展示安全工具活动：事件与 `turn_id` 关联，只包含工具名称以及 `started/completed/failed` 生命周期状态，不包含参数、返回值、隐藏提示词或原始推理。
- R10. 事件顺序必须可验证，使客户端能够按同一条流正确组合 turn 状态、工具活动和回答正文。
- R11. 如果 turn 在产生增量后失败，累计部分回答必须保留并以“不完整”语义对外可见，但不得提交为成功 assistant message，也不得触发仅适用于成功回答的记忆提取或 after-turn 副作用。
- R12. MVP 支持持久化的协作式取消：API 接收停止请求，worker 在流式增量或工具步骤边界检测取消并终止后续处理，turn 最终进入独立的 `cancelled` 终态。
- R13. 取消后的部分回答保留并标记为用户取消；系统不得声称已经撤销取消发生前完成的外部工具副作用。
- R14. 同一会话一次只允许一个未终结 turn；跨会话的 turn 状态彼此独立，允许所有者在一个会话生成期间切换并使用另一个会话。
- R15. `failed` 或 `cancelled` turn 支持重试；重试不得重开或改写原终态 turn，而是以原始用户输入创建一个新的 turn，并记录 `retry_of_turn_id` 关联。MVP 不为成功的 `done` turn 提供“重新生成”。
- R16. 重试必须沿用原 turn 的 owner 与 session 边界，只能针对终态 `failed/cancelled` turn，且仍受“同一会话最多一个未终结 turn”的约束。
- R17. 安全工具生命周期事件必须持久化到 PostgreSQL，并使用与 turn 关联的单调序号；首次加载、页面刷新和 SSE 断线重连后均可恢复相同的事件顺序。
- R18. 持久化工具事件只允许包含稳定事件类型、`turn_id`、工具名称、`started/completed/failed` 状态、序号和必要时间戳；不得持久化或下发参数、返回值、隐藏提示词或原始推理。事件与所属 turn 采用相同的生命周期策略。
- R19. 会话时间线必须保留并返回 `failed` 和 `cancelled` turn，将其呈现为带终态标记的“未完成尝试”；如果已经产生部分回答，则一并返回，并提供基于原 turn 的重试入口。成功重试不得覆盖或删除原失败记录。
- R20. 历史读取契约必须包含渲染时间线所需的 turn 状态与重试关联，不能仅依赖成功后才写入的会话消息记录来重建失败或取消过程。
- R21. turn 的执行生命周期必须与 SSE/浏览器连接生命周期解耦；断网、刷新、关闭标签页或 SSE 断开均不得隐式取消 turn，只有显式停止请求或服务器自身的终止策略可以结束执行。
- R22. 客户端重新连接后必须从 PostgreSQL 中的持久状态恢复当前 turn、累计回答和安全事件，而不是要求原 SSE 连接仍然存在。
- R23. worker 必须为 `processing` turn 维护持久化心跳或等价租约；超过可配置期限的 turn 必须收口为 `failed`，并使用稳定的 `interrupted` 原因标识，同时保留部分回答和已记录事件。
- R24. 中断恢复不得自动重新执行原 turn；尤其在工具可能已经产生外部副作用时，系统只能暴露失败状态并等待所有者显式重试。原 turn 保持不可变，新 turn 沿用 R15-R16 的重试关联。
- R25. Web API 与 SSE 不得返回原始异常文本；失败对外采用稳定 `error_code`、安全中文 `message` 与 `retryable` 标记。完整异常和堆栈仅写入服务端日志，并用 `turn_id` 关联诊断。
- R26. 错误映射必须有明确的白名单与未知错误兜底；未知异常不得因为 `str(exc)` 或元数据透传而泄露文件路径、供应商响应、工具输入、配置值或其他内部信息。
- R27. runtime 的会话消息提交与 worker 的 turn 终态更新之间必须可对账：消息需带稳定 `turn_id` 关联并支持幂等检查；处理中断恢复时，如果该 turn 的成功 assistant message 已经提交，则只将 turn 对账为 `done`，否则收口为 `failed/interrupted`。两种情况都不得重新执行模型或工具。

## Acceptance Criteria

- [ ] Provider/runtime 测试证明多个正文 delta 按顺序发布且最终结果完整一致。
- [ ] Worker/store 测试证明增量与正确 `turn_id` 绑定，序号单调，并在终态后拒绝继续追加。
- [ ] SSE 测试证明处理中可观察累计正文，重连不会要求依赖 API 进程内状态，并在 `done/failed/cancelled` 后关闭。
- [ ] 工具调用测试证明只有最终面向用户的回答正文被流式发布。
- [ ] 测试证明即使 provider 返回思考增量，Web SSE 也不会包含原始推理内容或供应商私有字段。
- [ ] 工具活动测试证明开始、完成和失败事件按序可见，且 payload 不包含工具参数或结果。
- [ ] SSE schema 测试证明不同事件种类具有稳定判别字段，React 无需根据可选字段猜测事件类型。
- [ ] 中途失败测试证明部分回答可恢复且终态明确为失败，同时会话历史和记忆系统不会把它当作成功完整回答。
- [ ] 取消测试证明请求跨 API/worker 进程可见，provider 流停止，turn 进入 `cancelled`，已有部分回答保留且不会提交为成功回答。
- [ ] 工具边界取消测试证明已经完成的外部副作用不会被错误标记为已回滚，取消后不再启动新的推理或工具步骤。
- [ ] 同会话并发测试证明第二个未终结 turn 会被拒绝或由明确契约阻止；不同会话的状态和事件不会串流。
- [ ] 重试测试证明原 `failed/cancelled` turn 保持不可变，新 turn 复用原始用户输入并带有可追溯的 `retry_of_turn_id`，且不会造成成功会话历史中的重复用户消息。
- [ ] API 测试证明不能重试 `done` 或非终态 turn，不能跨 owner/session 重试，也不能绕过同会话未终结 turn 约束。
- [ ] 持久化事件测试证明页面刷新或 SSE 重连后仍能按原序恢复工具生命周期，并且事件字段白名单中不存在参数、返回值、隐藏提示词或原始推理。
- [ ] 历史接口测试证明重新打开会话后仍能看到 `failed/cancelled` turn、部分回答、终态原因和重试关联；成功重试后原失败记录仍保持不变。
- [ ] 生命周期测试证明关闭 SSE 不会取消 worker 中的 turn；重新订阅可以恢复进度，而显式停止请求仍可令 turn 进入 `cancelled`。
- [ ] worker 崩溃恢复测试证明过期心跳会把 `processing` turn 收口为 `failed/interrupted`、保留已有快照和事件，并且不会自动创建或执行替代 turn。
- [ ] 错误契约测试证明已知错误映射为稳定代码，未知错误使用安全兜底；API/SSE payload 均不包含原始异常、堆栈、内部路径或敏感字段，服务端日志仍能通过 `turn_id` 定位。
- [ ] 双写故障测试覆盖“会话消息已提交但 turn 尚未标记 done”的崩溃窗口：恢复只对账终态，不重复添加消息、不重新调用模型或工具；未找到已提交 assistant message 时才标记 `failed/interrupted`。
- [ ] 现有非流式调用方和 turn 状态公共行为保持兼容。

## Out of Scope

- React 组件和视觉界面。
- 引入 Redis、Kafka 或新的消息基础设施。
- 将隐藏的 chain-of-thought 作为默认产品输出。
- 对成功 `done` turn 的重新生成、回答分支和分支切换。
