# 回答增量流式链路技术设计

## 1. 设计目标与依赖

本设计把“执行一个 turn”和“浏览器观看这个 turn”拆成两个独立生命周期。PostgreSQL 是跨 FastAPI 与 worker 进程的权威状态；SSE 只是读取并推送持久状态的传输适配器。

前置依赖：必须先完成 `07-18-owner-scoped-web-identity`。本任务新增的 turn 查询、时间线、SSE、取消和重试端点都必须通过服务器端 `OwnerScope` 校验，不接受浏览器选择 `user_id`。

参考 Akashic：

- `../akashic-agent/agent/provider.py`：provider 在累计最终回复的同时产生增量。
- `../akashic-agent/agent/looping/core.py`：runtime 通过 stream sink/event 边界接收增量。
- `../akashic-agent/bus/events_lifecycle.py`：生命周期事件与具体 channel 解耦。

迁移上述契约思想，不迁移 Akashic 的字符串 session key或 Telegram 消息替换方式。普通文本与工具活动按到达顺序公开；独立 thinking/reasoning channel 是否展示不在本任务扩展。

## 2. 核心边界

```text
LLMProvider
  -> TurnStreamSink（普通文本增量）
Reasoner
  -> TurnStreamSink（安全工具生命周期）
PassiveRuntime
  -> 仍返回完整 PassiveTurnResult
TurnWorker / PersistedTurnStream
  -> 批量写 PostgreSQL 快照与事件
FastAPI SSE
  -> 只读取 PostgreSQL，发布 typed envelope
React EventSource manager
  -> 消费事件；不拥有执行生命周期
```

核心 runtime 不导入 FastAPI、SSE、React 或 PostgreSQL turn store。它只依赖一个可选的异步 `TurnStreamSink`。没有 sink 的既有调用继续走完整响应路径。

## 3. 领域契约

### 3.1 状态机

```text
pending -> processing -> finalizing -> done
                    \-> failed       \-> failed
                    \-> cancelled
pending ----------------> cancelled
```

- `done/failed/cancelled` 都是不可变终态。
- 终态之后拒绝快照、事件、心跳、取消或再次终结。
- `finalizing` 是成功提交的持久化线性化点：worker 先强制 flush 并在事务内确认没有取消请求，再进入该状态；进入后才允许写成功消息和 after-turn 副作用。
- 同一 owner/session 仅允许一个 `pending`、`processing` 或 `finalizing` turn；用 PostgreSQL partial unique index 在创建时强制，而不只依赖 worker 调度。
- 不同 session 可并行。

### 3.2 内部流事件

核心层只定义两类立即可判别的事件：

- `ContentDelta(text)`：provider 普通 text/content channel 产生的文本片段，包括随后可能出现工具调用的 LLM 步骤文本。
- `ToolActivity(activity_id, tool_name, state)`：同一次调用的开始和结束共享稳定 `activity_id`；`state` 仅为 `started/completed/failed`。

不定义“过程文本”“最终文本”或 `answer_started`。provider 的独立 thinking/reasoning channel 不冒充 `ContentDelta`；工具调用分片由 provider 累积为结构化调用，不能拼入普通文本。工具参数与结果的详细展示不在本任务扩展，MVP 工具卡片仍使用名称和生命周期。

### 3.3 Web typed envelope

统一结构：

```json
{
  "seq": 12,
  "type": "content_snapshot",
  "turn_id": "uuid",
  "occurred_at": "2026-07-18T12:00:00Z",
  "data": {"content": "turn 累计普通文本", "version": 7}
}
```

允许的 `type`：

- `turn_status`：`pending/processing/finalizing` 状态变化；
- `content_snapshot`：turn 累计普通文本而非 token delta；
- `tool_activity`：稳定 `activity_id`、工具名与生命周期；
- `turn_terminal`：`done/failed/cancelled` 以及安全错误对象。

SSE 使用 `id: <seq>`、固定 `event: turn_event` 和 JSON `data`。客户端按 `seq` 去重。共享 reducer 保存上一份累计正文：新快照必须以旧正文为前缀，只把新增后缀追加到当前 text part；工具事件到达后关闭当前 text part，下一份快照的新增后缀创建新 part。该 part 的稳定本地 ID 使用首个贡献快照的 `seq`，不再重复持久化 `part_id`。

## 4. PostgreSQL 模型

### 4.1 `conversation_turns` 扩展

新增或规范化字段：

- `partial_answer TEXT NOT NULL DEFAULT ''`
- `stream_version BIGINT NOT NULL DEFAULT 0`
- `next_event_seq BIGINT NOT NULL DEFAULT 0`
- `cancel_requested_at TIMESTAMPTZ NULL`
- `heartbeat_at TIMESTAMPTZ NULL`
- `lease_id UUID NULL`
- `retry_of_turn_id UUID NULL REFERENCES conversation_turns(id)`
- `error_code TEXT NULL`
- `error_message TEXT NULL`
- `error_retryable BOOLEAN NULL`

旧 `error` 字段不得再写原始异常；迁移后只保留兼容读取或安全内容，并逐步由 typed error 字段替代。

约束与索引：

- `retry_of_turn_id` 不能等于自身；
- owner/session 与被重试 turn 必须由 store 事务校验；
- `(user_id, session_id)` 对 `pending/processing/finalizing` 建 partial unique index；
- `status/heartbeat_at` 索引用于中断回收。

### 4.2 `conversation_turn_events`

追加式事件表至少包含：

- `turn_id UUID`，随 turn 删除；
- `seq BIGINT`，与 `turn_id` 组成唯一键；
- `event_type TEXT`；
- typed 安全 payload；
- `created_at TIMESTAMPTZ`。

事件只能通过 `TurnEventStore` 的 typed 方法创建，不能让调用方提交任意 JSON。`content_snapshot` 保存 turn 累计普通文本，`tool_activity` 保存稳定 `activity_id`、工具名和生命周期；两者共享 turn 内单调 `seq`。事件与 turn 同生命周期，不设置 MVP 独立清理周期。

每次快照/事件写入在一个事务内锁定 turn、校验 `processing + lease_id`、分配递增 `seq`、更新当前快照并插入事件。

### 4.3 消息幂等关联

成功会话消息必须带 `turn_id` 和 role 关联，并建立足以阻止同一 turn 重复提交 user/assistant message 的唯一约束或等价 store 幂等契约。

这是修复现有双写窗口所必需的：`PassiveRuntime._complete_turn()` 当前先由 after-reasoning 保存消息，worker 随后才 `mark_done()`。恢复器发现过期 processing turn 时：

1. 如果已存在该 `turn_id` 的成功 assistant message，用其正文对账 `done`；
2. 否则标记 `failed/interrupted`；
3. 两种路径都不重新调用 provider 或工具。

## 5. Provider 与 Runtime 数据流

### 5.1 Provider

`LLMProvider.chat()` 增加可选普通文本回调或 sink 参数，默认 `None`。流式路径使用供应商 stream API：

1. 累计正文；
2. 累计工具调用分片供最终 `LLMResponse` 使用；
3. 普通 text/content delta 到达即交给 sink，不等待当前响应结束，也不因稍后出现 tool call 而丢弃；
4. 返回与非流式路径等价的最终 `LLMResponse`。

非流式调用者不传 sink，公共结果保持兼容。独立 thinking/reasoning channel 不伪装成普通文本；后续若展示必须新增明确事件类型。

### 5.2 Reasoner 与工具活动

Reasoner 在实际工具调用前后发布安全生命周期事件：

- 调用前 `started`；
- 正常返回 `completed`；
- 异常返回 `failed`，然后沿用现有错误控制流。

每次新 LLM 步骤、正文 flush 前后和工具步骤边界检查取消。已完成的外部工具副作用不回滚；取消后不得启动新的模型步骤或工具调用。

### 5.3 Worker 持久化适配器

worker 为已 claim 的 turn 创建 `PersistedTurnStream`：

- 维护完整累计普通文本并按阈值写 `content_snapshot`；工具事件前强制 flush，确保 `seq` 顺序足以让消费端 reducer 切分 text part；
- 达到字符阈值或时间阈值时写累计快照；
- 工具事件、取消、失败和终态前强制 flush；
- 独立心跳协程定期续租并检查 `cancel_requested_at`；
- 所有写入带 `lease_id`，防止过期 worker 覆盖已回收终态。

默认阈值作为配置提供，初始建议正文累计 128 字符或 100ms flush，心跳 10s、过期 120s；必须验证过期时间大于心跳间隔并允许部署调整。

## 6. 取消、中断与错误

### 6.1 显式取消

- `pending`：API 可在事务内直接转为 `cancelled`。
- `processing`：API 只写 `cancel_requested_at`；worker 在每个语义边界强制重读取消状态，协作式停止并写终态。
- `finalizing`：取消返回 `409 invalid_turn_transition`；成功提交已经取得执行权，继续收口为 `done` 或 `failed`。
- 终态：取消返回 `409 invalid_turn_transition`，不改变结果。

SSE 断开、页面刷新和浏览器关闭不触发取消。

### 6.2 worker 中断

claim 循环或独立维护动作扫描过期心跳。先按消息 `turn_id` 对账已提交成功，再选择 `done` 或 `failed/interrupted`，绝不自动重跑。

### 6.3 安全错误契约

Web 只返回：

```json
{"error_code": "provider_timeout", "message": "模型响应超时，请重试", "retryable": true}
```

至少定义 `provider_timeout`、`tool_timeout`、`interrupted`、`provider_error`、`runtime_error`。未知异常统一映射 `runtime_error`，不得返回 `str(exc)`。原始异常仅通过 `logger.exception(... turn_id=...)` 记录。

## 7. Web API

所有资源先经过 `OwnerScope`：

- `GET /api/sessions/{session_id}/turns`：turn 时间线，包含成功与未完成尝试；
- `GET /api/turns/{turn_id}`：当前权威快照；
- `GET /api/turns/{turn_id}/events?after_seq=N`：SSE，支持 `Last-Event-ID` 与显式 cursor；
- `POST /api/turns/{turn_id}/cancel`：显式停止；
- `POST /api/turns/{turn_id}/retry`：仅 `failed/cancelled`，创建带 `retry_of_turn_id` 的新 turn。

`GET .../messages` 暂时保留兼容和 runtime 历史用途；React 的可恢复聊天时间线以 turns API 为准。创建、重试和同会话活跃约束冲突返回稳定 `409 active_turn_exists`。

SSE 从数据库读取 `seq > cursor` 的事件，空闲时发送注释 keepalive；终态事件发出后关闭。找不到或不属于 owner 的 turn 统一 404。

## 8. 兼容、迁移与回滚

- 数据库迁移先增列/增表/回填安全默认值，再建立约束；不破坏既有 turn 与 message 读取。
- 建立活跃唯一索引前必须收敛旧数据：遗留 `processing` 一律标记为可重试的 `failed/interrupted`；同一 owner/session 的多个 `pending` 只保留最早一个，其余标记为 `failed/interrupted`；每个被收敛的 turn 都追加安全 `turn_terminal` 事件。
- 非流式 provider/runtime 调用方继续可用。
- 旧静态 Web 在 React 子任务完成前仍可通过最终 turn 状态工作；新字段均为增量兼容。
- 回滚应用版本时，新表和可空列可留存；数据库 downgrade 只有在确认没有新状态写入后执行。
- 不引入 Redis/Kafka；如果单用户 PostgreSQL 轮询经测量不足，再另立任务评估 LISTEN/NOTIFY。

## 9. 关键验证

- provider：普通文本立即发布、同一步 text 后出现工具调用时不丢文本、工具分片累计、独立 thinking channel 不误标、最终响应一致；
- runtime：`text -> tool -> text` 边界、取消不提交成功消息、after-turn 只在成功后执行；
- store：状态机、lease、防双写、单调 seq、同 session 唯一活跃 turn；
- worker：批量 flush、显式取消、崩溃对账、原始异常不落库；
- Web：owner 404、SSE reconnect、时间线、重试、409 冲突、安全错误；
- 集成：API 与 worker 分进程，共享 PostgreSQL 后可在刷新页面时恢复；SSE 观察到终态时必须先排空同一事实源中已经持久化的尾部事件，再关闭连接。
