# 拆分回答终态与后台记忆生命周期：技术设计

## 1. 设计目标

把当前一条同步调用链拆成两个可独立观察、独立恢复的生命周期：

```text
回答生命周期（用户关键路径）
LLM stream
-> finalization 取消线性化
-> 持久化 user/assistant message
-> 同一数据库事务提交 turn done + turn_terminal + memory job
-> 浏览器结束生成状态

后台记忆生命周期（非用户关键路径）
memory worker claim durable job
-> 按 job 固定的 message ids 读取本轮消息
-> MemoryEngine.run_post_response
-> 记录 job done / failed 与 trace
```

第一性原理约束：

1. “回答成功”只表示回答事实已经可靠持久化，不表示所有衍生计算已经完成。
2. 后台任务若只存在于 Python 内存，进程退出时就不存在，因此不能满足 durable。
3. `done` 与 job 创建若分成两个事务，进程可能在两者之间崩溃，产生“回答成功但永远没有记忆任务”的断层，因此必须原子提交。
4. 后台任务若读取执行时的整个 session，可能把后续轮次再次当作当前轮证据，因此 job 必须固定本轮消息边界。
5. 若后台记忆仍在唯一的 turn worker 顺序循环中运行，下一轮回答仍会被记忆模型阻塞，因此必须有独立消费循环。

## 2. Akashic 参考与 Amadeus 扩展

参考 Akashic：

- `../akashic-agent/plugins/default_memory/engine.py:649`：`TurnCommitted` 后只 enqueue `TurnIngested`，主回复不等待 post-response。
- `../akashic-agent/bus/event_bus.py:75`：进程内后台队列负责把事件交给 fanout。
- `../akashic-agent/memory2/post_response_worker.py`：保留 post-response 候选抽取和记忆变更生命周期。

不直接照搬的部分：

- Akashic EventBus 队列是进程内状态，重启后丢失。
- Akashic 没有与 Amadeus 当前 PostgreSQL turn lease 对应的 durable post-response queue。
- 因此，PostgreSQL job 表、事务性 enqueue、`FOR UPDATE SKIP LOCKED` claim、租约与 stale recovery 是 Amadeus 专有扩展。

## 3. 数据模型

新增 `post_response_memory_jobs`：

| 字段 | 含义 |
|---|---|
| `id UUID PRIMARY KEY` | job 身份 |
| `turn_id UUID NOT NULL UNIQUE` | 每个成功 turn 最多一个 post-response job |
| `user_id BIGINT NOT NULL` | user scope |
| `session_id BIGINT NOT NULL` | session scope |
| `user_message_id TEXT NOT NULL` | 本轮用户消息边界 |
| `assistant_message_id TEXT NOT NULL` | 本轮助手消息边界 |
| `explicit_memory_ids JSONB NOT NULL DEFAULT '[]'` | 保留现有显式记忆去重上下文 |
| `status TEXT NOT NULL` | `pending / processing / done / failed` |
| `attempts INTEGER NOT NULL DEFAULT 0` | claim 次数 |
| `lease_id UUID` | processing 所有权 |
| `heartbeat_at TIMESTAMPTZ` | stale recovery 判断 |
| `result_json JSONB NOT NULL DEFAULT '{}'` | 成功 trace |
| `error_code TEXT / error_message TEXT` | 最低限度失败可观察性 |
| `created_at / started_at / completed_at / updated_at` | 生命周期时间 |

约束与索引：

- `UNIQUE(turn_id)` 是 enqueue 幂等键。
- claim 索引覆盖 `(status, created_at, id)`。
- 外键关联 turn、user、session；message id 可使用外键或在事务内显式验证存在，最终以现有 schema 兼容性为准。
- 状态约束拒绝未知值。

本任务不增加重放次数、告警状态、dead-letter 管理字段或管理员备注。

## 4. 公共类型与存储边界

新增明确类型：

```python
@dataclass(frozen=True)
class TurnExecutionResult:
    answer: str
    user_message_id: str
    assistant_message_id: str
    explicit_memory_ids: tuple[str, ...]

@dataclass(frozen=True)
class PostResponseMemoryJob:
    id: str
    turn_id: str
    user_id: int
    session_id: int
    user_message_id: str
    assistant_message_id: str
    explicit_memory_ids: tuple[str, ...]
    status: str
    attempts: int
    lease_id: str | None
```

`PassiveAppTurnRunner.run()` 从只返回字符串改为返回 `TurnExecutionResult`。这些字段来自 `PassiveTurnResult` 和当前 memory trace，不从非类型化 metadata 重新猜测。

新增 `PostResponseMemoryJobStore` 契约：

```python
claim_next_pending() -> PostResponseMemoryJob | None
heartbeat(job_id, lease_id) -> bool
mark_done(job_id, lease_id, trace) -> PostResponseMemoryJob
mark_failed(job_id, lease_id, error) -> PostResponseMemoryJob
recover_stale(stale_after_seconds) -> int
```

`PostgresTurnStore` 的成功提交入口扩展为事务性方法：

```python
complete_success(
    turn_id,
    lease_id,
    result: TurnExecutionResult,
) -> Turn
```

该方法在同一 PostgreSQL 事务内：

1. 锁定 `processing/finalizing + lease_id`；
2. 再次确认取消没有在线性化点前获胜；
3. 验证两个 message id 属于同一 user/session/turn；
4. 必要时补齐最终 content snapshot；
5. 更新 turn 为 `done`；
6. 插入 `turn_terminal`；
7. `INSERT ... ON CONFLICT (turn_id) DO NOTHING` 创建 memory job；
8. commit。

`mark_done()` 不再作为生产成功路径的分散入口；测试辅助是否保留由实现阶段按兼容性决定。stale turn 对账在发现 assistant message 时也必须走等价的“done + enqueue”原子路径，避免恢复路径漏任务。

## 5. Runtime 边界

`after_reasoning.persist` 继续负责：

- 写入本轮 user/assistant messages；
- 返回稳定 message ids；
- 发出既有 `TurnCommitted` lifecycle event。

`after_turn` 不再同步执行 `_RunPostResponseMemoryModule`。它只保留不属于 post-response memory 的 lifecycle/plugin 合约，并快速返回。

`MemoryEngine.run_post_response(...)` 公共接口保持不变；迁移的是调用位置，不重写记忆算法。

后台 job runner 必须：

1. 使用 job 的 `user_id` 构建 user-scoped app/memory engine；
2. 只按 `user_message_id + assistant_message_id` 读取本轮两条消息；
3. 验证两条消息与 job 的 user/session/turn 一致；
4. 通过 `MemoryEngine.run_post_response` 执行，不直接访问 memory store；
5. 把返回 trace 写入 job `result_json`。

## 6. Worker 与并发

新增独立进程入口，例如：

```text
python -m amadeus.worker.post_response_memory_worker
```

Docker Compose 新增 `memory-worker` 服务。它与 `worker` 使用相同镜像、PostgreSQL 和 workspace volume，但拥有独立消费循环。

并发规则：

- PostgreSQL 使用 `FOR UPDATE SKIP LOCKED`，同一 job 不会被两个 worker 同时领取。
- `UNIQUE(turn_id)` 保证重复成功提交不重复创建 job。
- 同一 session 的 memory jobs 按创建顺序串行领取；不同 session 可以独立推进。这样纠错/替换决策不会越过前一轮记忆状态。
- worker 崩溃留下的 stale `processing` job 可恢复为 `pending`。
- 普通执行异常最低限度标记 `failed` 并记录安全错误；自动业务重试、人工重放和告警不在本任务内。

幂等依据：

- job enqueue 以 `turn_id` 幂等。
- job 输入固定为稳定 message ids。
- 现有 memory 写入已用 `(user_id, memory_type, source_ref)` 和 content hash 约束去重；恢复执行必须继续生成稳定 source ref。
- replacement relation 保留既有唯一性和 source-ref 语义。

## 7. 终态与前端

公开 SSE 协议无需新增 memory job 事件：

- 浏览器仍只消费 `content_snapshot / tool_activity / turn_terminal`。
- `turn_terminal: done` 在事务提交后由现有 SSE 读取。
- 前端收到 terminal 后立即退出 active 状态；Query refetch 只负责权威快照交接，不把 memory job 状态暴露给聊天界面。

500ms 指标定义：

```text
浏览器最后一个回答字符可见
-> streaming cursor 消失
-> stop 恢复为 send
-> composer 可提交下一轮
总计 <= 500ms（可控 E2E 环境）
```

后台 memory runner 在测试中保持阻塞，仍必须满足该指标。

## 8. 故障边界

| 故障点 | 预期行为 |
|---|---|
| assistant message 持久化失败 | turn 不得进入 `done`，不得创建 job |
| `complete_success` 事务失败 | `done`、terminal、job 全部不提交；由现有 stale turn 机制恢复 |
| `complete_success` commit 后进程退出 | 回答已是 `done`，job 仍在 PostgreSQL 等待独立 worker |
| memory worker 启动前/运行中退出 | 回答不变；pending/stale job 可重新发现 |
| post-response 模型或 embedding 异常 | job 标为 `failed` 并记录安全错误；回答保持 `done` |
| 重复领取或重复 enqueue | 唯一键、lease 和 memory source-ref 幂等约束阻止重复破坏 |

## 9. 兼容、发布与回滚

发布顺序：

1. Alembic 先创建 job 表；
2. 部署包含新成功提交事务和 memory worker 的代码；
3. 启动 `memory-worker`；
4. 通过 smoke/查询确认 pending job 能转为 done。

兼容：

- Web API 与 SSE payload 不变。
- 已有 `done` 历史 turn 不回填 job；本任务只保证部署后的成功 turn。
- 长期记忆关闭时，成功提交不创建 job，或创建可立即完成的 skipped job；实现阶段应选择不制造无意义队列数据的前者。

回滚：

- 在保留新表的情况下可回滚应用代码；新表不影响旧代码读取。
- 不在同一发布中删除现有 memory 实现或改变候选算法。
- 若 memory-worker 有问题，可先停止该服务；回答链路仍正常，pending jobs 保留待后续处理。

## 10. 文档与观测

需要更新：

- `.trellis/spec/backend/turn-streaming.md`：成功提交与 post-response job 的事务边界。
- `.trellis/spec/backend/async-boundaries.md`：独立 memory worker、同步 store 下沉线程的约束。
- `.trellis/spec/frontend/react-chat-client.md`：500ms 用户终态验收。
- `docs/postgres-runtime.md`、`README.md`、`.env.example`：memory worker 启动与基础配置。

基础结构化日志字段：

```text
job_id, turn_id, user_id, session_id, status, attempts, duration_ms, error_code
```

日志不得输出消息全文、模型密钥或原始异常中可能包含的敏感 payload。
