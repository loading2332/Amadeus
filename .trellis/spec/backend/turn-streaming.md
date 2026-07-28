# Turn 增量流式运行时契约

## 场景：跨进程、可恢复的回答流

### 1. 范围 / 触发

- 触发：修改 `LLMProvider`、`Reasoner`、`PassiveRuntime`、turn worker/store、turn API、SSE，或 `conversation_turns` / `conversation_turn_events`。
- 目标：worker 产生的进度以 PostgreSQL 为事实源，API 进程只负责按序读取；浏览器连接不是执行所有者。
- 原因：API 与 worker 是独立进程，进程内 callback、队列或 SSE 连接都无法承担断线恢复和崩溃对账。

### 2. 签名

- `LLMProvider.chat(messages, tools=None, *, content_sink=None) -> LLMResponse`
- `TurnStreamSink.publish_content(delta) -> Awaitable[None]`
- `TurnStreamSink.publish_tool_activity(*, activity_id, tool_name, state) -> Awaitable[None]`
- `TurnStreamSink.check_cancelled() -> Awaitable[None]`
- `TurnStreamSink.begin_finalization() -> Awaitable[None]`
- `GET /api/sessions/{session_id}/turns`
- `GET /api/turns/{turn_id}/events?after_seq=<int>`，并兼容 `Last-Event-ID`
- `POST /api/turns/{turn_id}/cancel`
- `POST /api/turns/{turn_id}/retry`
- 数据库：`conversation_turn_events(turn_id, seq, event_type, payload_json, created_at)`，主键为 `(turn_id, seq)`；消息以 `turn_id` 关联成功提交。

### 3. 契约

- 普通文本事件使用 turn 级累计 `content_snapshot`。共享 reducer 保存上一快照，只把新增后缀追加到当前 text part；工具事件结束当前 part，后续快照的新增后缀创建新 part。part 的本地稳定 ID 使用首个贡献快照的 `seq`，无需重复持久化。`done.answer` 仍是 runtime 返回的权威最终回复，事件时间线可以额外保留工具前的普通文本。
- SSE envelope 固定为 `{seq, type, turn_id, occurred_at, data}`；SSE `id` 等于 `seq`，事件名为 `turn_event`。
- 每个 turn 的 `seq` 严格递增并持久化。重连只读取 `seq > after_seq`；断开连接不得隐式取消 turn。
- SSE 每轮先读取 turn 快照，再读取 `seq > cursor` 的事件；即使快照已是终态，也必须先发完本轮查到的尾部事件再关闭，避免终态写入与轮询之间的竞态丢失。
- 不区分“过程文本”和“最终回答文本”，不使用 `answer_started`：provider 普通 text/content delta 到达即发布，即使同一步稍后产生工具调用也不得撤回。工具调用分片不得拼入普通文本。独立 reasoning/thinking channel 若要展示，必须新增独立 typed part，不能伪装成 text。
- MVP 工具事件包含稳定 activity ID、工具名和 `started|completed|failed`；`completed|failed` 事件驱动对应工具卡片立即折叠。
- 同一 `(user_id, session_id)` 最多一个 `pending|processing|finalizing` turn；跨会话可独立处理。
- `processing -> finalizing` 是取消/成功提交的线性化点。进入前必须强制刷新正文并在数据库事务内确认没有取消请求；进入后才能提交成功消息与 after-turn 副作用，取消请求返回 `409`。
- `done|failed|cancelled` 为不可逆终态。重试只为 `failed|cancelled` 创建新 turn，并记录 `retry_of_turn_id`。
- worker claim 生成 `lease_id`；心跳、增量、工具事件和终态写入必须匹配该 lease。过期恢复先查询带相同 `turn_id` 的 assistant message：存在则对账为 `done`，否则为 `failed/interrupted`，都不得重新执行。
- 环境变量：`AMADEUS_TURN_STREAM_FLUSH_CHARACTERS`、`AMADEUS_TURN_STREAM_FLUSH_INTERVAL_SECONDS`、`AMADEUS_TURN_HEARTBEAT_INTERVAL_SECONDS`、`AMADEUS_TURN_STALE_AFTER_SECONDS`；均为正有限数，且 stale 必须大于 heartbeat。

### 4. 验证与错误矩阵

| 条件 | 结果 |
|---|---|
| 同会话已有活跃 turn | `409 active_turn_exists` |
| 取消 pending | 直接进入 `cancelled`，保留既有快照 |
| 取消 processing | 写取消请求，worker 在正文或工具边界协作停止 |
| 取消已登记、worker 准备完成 | `begin_finalization` 拒绝进入，worker 收口为 `cancelled`，不提交成功消息 |
| 取消 finalizing | `409 invalid_turn_transition`，成功提交继续收口 |
| 重试 done / 非终态 | `409`，原 turn 不变 |
| turn 不属于 owner | 与不存在统一为 `404` |
| 旧 lease 写增量或终态 | 拒绝写入，不得覆盖当前执行者 |
| provider/runtime 已输出部分正文后失败 | 保留快照，进入 `failed`，不写成功 assistant message |
| 未知异常 | 公开 `runtime_error` 与安全中文消息；原始异常仅记服务端日志并关联 `turn_id` |
| stale processing/finalizing 且已有 assistant message | 幂等对账为 `done` |
| stale processing/finalizing 且无 assistant message | `failed/interrupted`，不自动重试 |
| 升级前遗留多个 active turn | processing 全部中断；每组 pending 只保留最早一个；其余写安全 terminal 事件后再建唯一索引 |

### 5. Good / Base / Bad Cases

- Good：客户端收到快照 A 后断网；worker 继续写 AB 和 done；重连以 A 的 seq 查询，只恢复后续持久事件。
- Base：非流式调用方不传 sink，仍获得完整 `LLMResponse`；流式调用方立即得到普通文本。若模型先输出说明再调用工具，事件时间线保留说明，`done.answer` 仍是 runtime 最终回复。
- Bad：带 tools 时先缓冲普通文本，响应结束发现 tool call 后丢弃；这会让用户看不到模型已经产生的文本，并破坏 `text -> tool -> text` 顺序。
- Bad：API 进程用 `asyncio.Queue` 接 worker callback；多进程不可见，重启或断线后事件丢失。
- Bad：把 token 逐个写数据库；造成写放大。必须按字符/时间阈值写累计快照，并在工具、失败、取消和终态前强制 flush。
- Bad：工具完成后才发现取消，却把已发生的外部副作用描述为回滚。应先持久化 `completed`，再停止后续步骤。

### 6. 必需测试

- Provider/runtime：普通文本 delta 立即有序发布、同一步 text 后出现 tool call 时文本仍保留、工具分片不混入文本、独立 thinking channel 不误标为 text、最终聚合一致。
- Store/Web：累计 content snapshot 与带稳定 `activity_id` 的工具事件共享单调 seq；历史重放和 SSE 直播使用同一 reducer，恢复相同的 `text -> tool -> text` 顺序。
- Store：事件序号单调、活跃唯一索引、终态不可逆、旧 lease 拒绝、取消与新 turn 重试关联、取消与 finalizing 的线性化竞态。
- Worker：部分失败安全错误、processing 取消、快照强制 flush、消息已提交/未提交两类 stale 恢复。
- Web：owner 404、409 映射、typed SSE、`after_seq` / `Last-Event-ID` 重连、终态关闭、时间线保留失败与取消。
- 跨进程集成：分别启动 FastAPI 与 worker，在首个快照后关闭 SSE，再重连并断言完整快照、单调 seq 和 done。
- Migration：从旧版本注入重复 pending 与遗留 processing 后 upgrade，断言安全收敛及 terminal 事件；再 downgrade 一版并 upgrade，断言表、列、索引与外键均恢复。

### 7. Wrong vs Correct

#### Wrong

```python
# API 连接同时拥有执行；断线就丢状态或取消任务。
async for delta in runtime.run(content):
    yield f"data: {delta}\n\n"
```

#### Correct

```python
# worker 只写持久状态；API 按游标读取事实源。
await sink.publish_content(delta)  # 批量形成累计 snapshot
events = store.list_events(turn_id, after_seq=cursor)
```

#### Wrong：等待工具判定后才发布文本

```python
buffered.append(delta)
if not response.tool_calls:
    for delta in buffered:
        await sink.publish_content(delta)
```

#### Correct：普通文本与工具生命周期独立追加

```python
response = await provider.chat(
    messages,
    tools=tools,
    content_sink=sink.publish_content,
)
await sink.publish_tool_activity(
    activity_id=tool_call.id,
    tool_name=tool_call.name,
    state="started",
)
```

---

## 场景：回答终态与后台记忆抽取分离

### 1. 范围 / 触发

- 触发：修改成功 turn 提交、`AfterTurn`、长期记忆抽取、turn worker、
  memory worker，或 `post_response_memory_jobs`。
- 目标：用户可见终态只依赖回答和 job 已可靠落库，不依赖第二次 LLM
  记忆抽取完成。
- 原因：记忆抽取是派生计算；把它放在回答主链路会让第二次模型调用的延迟
  伪装成“回答还没结束”。

### 2. 签名

- `TurnExecutionResult(answer, user_message_id, assistant_message_id, explicit_memory_ids, enqueue_post_response_memory)`
- `PostgresTurnStore.complete_success(turn_id, lease_id, result) -> Turn`
- `PostgresPostResponseMemoryJobStore.claim_next_pending() -> PostResponseMemoryJob | None`
- `PostResponseMemoryWorker.run_once() -> bool`
- 数据库：
  `post_response_memory_jobs(turn_id, user_id, session_id, user_message_id, assistant_message_id, explicit_memory_ids, status, attempts, lease_id, heartbeat_at, result_json, error_code, error_message, ...)`。

### 3. 契约

- `conversation_turns.status = done`、`turn_terminal` 事件和
  `post_response_memory_jobs.status = pending` 必须在同一个 PostgreSQL 事务中提交。
- 创建 job 前必须验证两条消息均已落库，且 ID、角色、user、session、turn
  全部匹配；后台抽取只按 job 固化的消息 ID 读取证据，不能读取“当前会话尾部”。
- `AfterTurn` 不得调用 `MemoryEngine.run_post_response`。memory worker 独立
  claim、心跳和收口；所有同步 store 调用都经 `asyncio.to_thread`。
- 同一 session 同时最多一个 processing memory job，且 pending job 按
  `created_at, id` 顺序 claim；不同 session 可并行。
- 浏览器收到持久化 `done` 后立即退出生成态。验收目标为完整回答可见后
  500ms 内停止按钮消失、输入框恢复；memory job 此时允许仍为 pending 或 processing。
- Akashic 参考的是 `TurnCommitted -> TurnIngested` 的异步投递边界；Amadeus
  使用 PostgreSQL job/lease 扩展其可靠性，不能退化为进程内队列。

### 4. 验证与错误矩阵

| 条件 | 结果 |
|---|---|
| 成功消息缺失或边界不匹配 | 拒绝 `complete_success`，turn 不得进入 `done` |
| turn 已 `done` 但 job 插入事务失败 | 整个事务回滚，不允许只有 `done` 没有 job |
| 记忆模型阻塞 | turn/SSE/browser 已完成；job 保持 processing 并持续心跳 |
| memory worker 重启或心跳过期 | stale job 回到 pending，增加下一次 claim 的 attempts |
| 旧 lease 心跳或收口 | 拒绝更新，不覆盖当前执行者 |
| 记忆抽取失败 | 只收口 memory job；不得修改已完成 turn 或追加聊天错误提示 |
| stale turn 已有成功消息 | 对账为 done 时同事务补建缺失的 memory job |

### 5. Good / Base / Bad Cases

- Good：回答消息、done 事件和 pending job 原子提交；浏览器立刻结束生成态，
  memory worker 数秒后完成抽取。
- Base：长期记忆未配置时不创建 job，turn 仍按原路径完成。
- Bad：`await memory_engine.run_post_response(...)` 后才调用 `mark_done`；
  第二次模型调用会直接增加用户可见终态延迟。
- Bad：只在进程内 `create_task`；worker 崩溃后任务和证据边界一起丢失。
- Bad：job 消费时读取整个 session 最新消息；并发新 turn 会污染上一轮的抽取证据。

### 6. 必需测试

- Runtime：`run_post_response` 永久阻塞时，`run_turn` 仍在短 deadline 内返回。
- Store/Migration：done、terminal event、pending job 原子存在；消息边界错误时
  全部拒绝；lease、session 串行和 stale recovery 可验证。
- Worker：成功、阻塞心跳、失败隔离、消息 ID/角色/user/session/turn 边界。
- 浏览器 E2E：完整回答可见后 500ms 内停止按钮消失且输入框恢复。
- Docker/配置：Compose 同时声明 `worker` 与 `memory-worker`，两者共享
  PostgreSQL DSN 和 workspace。

### 7. Wrong vs Correct

#### Wrong

```python
result = await runtime.run_turn(...)
await memory_engine.run_post_response(messages=session.messages)
store.mark_done(turn.id, lease_id, result.assistant_response)
```

#### Correct

```python
execution = await runtime.run_turn(...)
await asyncio.to_thread(
    store.complete_success,
    turn.id,
    lease_id,
    TurnExecutionResult(
        answer=execution.assistant_response,
        user_message_id=execution.user_message_id,
        assistant_message_id=execution.assistant_message_id,
        enqueue_post_response_memory=True,
    ),
)
# 独立进程随后 claim post_response_memory_jobs。
```
