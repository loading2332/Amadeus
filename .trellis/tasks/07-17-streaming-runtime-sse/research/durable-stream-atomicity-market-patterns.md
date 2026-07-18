# 可恢复流、原子事务与市场方案研究

## 1. 研究问题

本研究回答：模型流、工具事件、PostgreSQL 快照和 SSE 之间存在延时或故障时，应该原子化什么；主流 SDK/运行时如何避免重复、乱序和恢复冲突；Amadeus 是否需要 Redis、LangGraph 或 Temporal。

研究时间：2026-07-18。资料只采用官方文档。

## 2. 第一性原理：整轮 Agent 不能成为数据库事务

一次 Agent turn 可能持续数秒或数分钟，并跨越：

```text
PostgreSQL -> 模型网络 -> 工具网络/进程 -> 模型网络 -> PostgreSQL
```

数据库事务只能原子控制同一数据库内的读写，不能把模型供应商和外部工具一起提交或回滚。长时间持有 `FOR UPDATE` 还会扩大锁等待、连接占用和失败半径。

正确粒度是短事务：

```text
BEGIN
锁定 turn 并校验 status + lease_id
更新累计快照/状态
分配 next_event_seq
插入事件
COMMIT
```

该提交对读者表现为全部出现或全部不出现。整轮运行则用状态机、事件日志、lease、幂等和恢复对账获得可靠性，而不是依靠一个跨网络大事务。

## 3. Amadeus 当前已经具备什么

`PostgresTurnStore.append_content_snapshot()` 已在同一事务内：

1. `SELECT ... FOR UPDATE` 锁定 turn；
2. 校验 `processing + lease_id`；
3. 更新 `partial_answer + stream_version`；
4. 增加 `next_event_seq`；
5. 插入 `conversation_turn_events`；
6. commit。

`append_tool_activity()` 同样锁定 turn、分配单调 seq 并插入事件。SSE 只读取已经提交的数据，因此不会观察到“状态更新了但对应事件尚未提交”的半成品。

现有防冲突机制：

- 单调 `seq`：确定事件顺序；
- `Last-Event-ID/after_seq`：断线后只取后续事件；
- 客户端忽略 `seq <= last_seq`：容忍重发；
- 累计 `content_snapshot`：丢失中间快照也能被下一快照覆盖；
- `lease_id`：旧 worker 不能覆盖新执行者；
- `processing -> finalizing`：取消与成功提交的线性化点；
- 终态不可逆：迟到写入被拒绝。

因此，网络延迟会让 UI 晚一点看到事件，但不会改变数据库中的确定顺序。

## 4. 当前仍存在的故障窗口

### 4.1 正文 flush 与工具事件是两个短事务

当前工具开始前执行：

```text
flush content snapshot -> COMMIT
append tool_started     -> COMMIT
execute tool
```

worker 如果在两个 commit 之间崩溃，会保留正文但没有 tool_started。由于工具尚未开始执行，这个历史仍然真实，只是 turn 最终会被 stale recovery 标为 interrupted。

如果产品要求“正文边界与工具卡片必须作为一个不可分割 UI 批次出现”，可以增加：

```python
append_progress_batch(
    content_snapshot=...,
    tool_activity=...,
)
```

在同一行锁事务中按两个连续 seq 插入。它增强展示边界，但不是当前正确性的硬缺口。

### 4.2 工具已经执行，但 completed 尚未提交

```text
tool_started 已提交
外部工具执行成功
worker 在 tool_completed 前崩溃
```

任何数据库事务都无法回滚外部世界。恢复时只能知道活动处于 `started`，不能证明工具未成功。成熟系统采用 `activity_id` 作为幂等键，或把状态标为 interrupted/unknown，不能盲目自动重试。

### 4.3 SSE 重复而不是严格 exactly-once

服务器可能已经发送 seq=12，但连接在客户端确认前断开；重连后 seq=12 可能再次出现。这属于正常的至少一次交付。客户端 reducer 必须按 seq 幂等去重。追求网络 exactly-once 会增加协调成本，但仍无法覆盖浏览器收到后崩溃的窗口。

## 5. 市场方案

### 5.1 Vercel AI SDK：Redis 可恢复流 + activeStreamId

Vercel AI SDK 的 resumable streams 需要应用自行提供：

- Redis 保存 UIMessage stream；
- 数据库记录 chat 对应的 `activeStreamId`；
- POST 创建流；
- GET 根据 activeStreamId 恢复；
- 完成后清除 activeStreamId。

刷新或断网只断开读取连接，不终止后端生成。其思路与 Amadeus 相同：执行生命周期与浏览器连接解耦；区别是 Vercel 用 Redis 保存流，Amadeus 已用 PostgreSQL 保存可恢复事件。

官方资料：[AI SDK UI: Chatbot Resume Streams](https://ai-sdk.dev/docs/ai-sdk-ui/chatbot-resume-streams)

### 5.2 LangGraph：步骤 checkpoint + pending writes

LangGraph 不把每个 token 作为工作流原子单位，而是在 graph super-step 边界保存 checkpoint；节点完成的 pending writes 可以先持久化，因此同一步其他节点失败后，成功节点不必重跑。

其官方 Functional API 明确要求：可能重放的 API/副作用放进 task，并设计成幂等。恢复是“从已记录步骤继续”，不是用数据库事务回滚外部 API。

官方资料：

- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Functional API: Determinism and Idempotency](https://docs.langchain.com/oss/python/langgraph/functional-api)

### 5.3 Temporal：持久事件历史 + Activity 至少一次

Temporal 把模型和工具调用建模为 Activities，由服务端保存 workflow event history、执行超时与重试。worker 崩溃后可以从历史恢复。

但 Activity 的外部副作用仍不能由 Temporal 事务性回滚；Activities 必须幂等，通常使用 workflow/activity ID 作为下游幂等键。Temporal 解决的是 durable orchestration，不是跨系统 ACID。

官方资料：[Temporal Documentation](https://docs.temporal.io/)

### 5.4 OpenAI Agents SDK：语义事件与会话持久化

OpenAI Agents SDK 提供 raw streaming events、tool/message run items、run state 和多种 session backend。它负责 Agent loop 与会话历史，但浏览器断线后的 UI stream 保存方式仍由应用选择。其 MongoDB session 实现也明确使用原子序列计数维护顺序。

官方资料：

- [OpenAI Agents SDK: Streaming](https://openai.github.io/openai-agents-python/streaming/)
- [OpenAI Agents SDK: Sessions](https://openai.github.io/openai-agents-python/sessions/)

## 6. 方案比较

| 方案 | 恢复来源 | 延迟 | 运维复杂度 | 适合 Amadeus 当前阶段 |
|---|---|---:|---:|---:|
| Provider 直接 SSE | 无或仅内存 | 最低 | 低 | 否，刷新/断线丢失 |
| PostgreSQL 快照 + 事件日志 | DB 单调 seq | 约数百毫秒 | 低 | 是 |
| Redis resumable stream + DB | Redis stream | 低 | 中 | 暂无必要 |
| LangGraph checkpoint | graph store | step 级 | 中 | Agent 图复杂后再评估 |
| Temporal workflow history | Temporal service | step 级 | 高 | 多用户、长任务、强恢复后再评估 |

## 7. 推荐决策

Amadeus 当前是单用户客户端，不建议为了流式回答立即引入 Redis、LangGraph 或 Temporal。PostgreSQL 已同时承担权威状态与可恢复事件日志，避免了 Redis/DB 双写。

建议保持：

```text
provider delta
-> 100ms/128 字符 coalescing
-> PostgreSQL 短事务写 snapshot + seq event
-> SSE 按 cursor 重放
-> React reducer 按 seq 幂等投影
```

按优先级补强：

1. 前端建立唯一共享 reducer：校验 seq 单调、重复忽略、累计快照必须保持前缀；异常时重新拉取 turn 历史，而不是继续错误拼接。
2. terminal 到达时，把仍为 running 的工具卡片投影为 interrupted，避免永久转圈。
3. 如果实测 250ms 轮询影响体验，增加 PostgreSQL `LISTEN/NOTIFY` 作为唤醒信号；事件表仍是事实源，通知丢失时继续轮询兜底。
4. 如果要求正文边界和 tool_started 同屏原子出现，再实现 `append_progress_batch()`；当前不必为理论窗口提前复杂化。
5. 对可能重试的工具使用 `activity_id` 作为幂等键；无法幂等的工具在中断后标记 unknown，等待人工决定。

## 8. 原子性结论

需要原子化：

- turn 状态/累计快照更新；
- `next_event_seq` 分配；
- 对应事件插入；
- finalizing 的取消检查与状态转换。

不应尝试原子化：

- 整个 LLM 流；
- 模型调用与 PostgreSQL；
- 外部工具副作用与 PostgreSQL；
- SSE 发送与浏览器渲染。

系统目标应表述为：数据库事实原子、事件至少一次、客户端幂等、工具可恢复或明确 unknown，而不是宣称端到端 exactly-once。
