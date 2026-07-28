# Async 边界：事件循环上的同步 I/O

> web 与 worker 都运行在 asyncio 事件循环上，而存储层（`PostgresTurnStore` 等）是同步 psycopg。本文规定两者交界处的强制契约。
>
> 来源：07-26-fix-critical-review-findings（review 发现 SSE 轮询/路由/worker flush 同步调库阻塞事件循环）。

---

## 场景：async 路径调用同步 store

### 1. 范围 / 触发

- 触发：任何 `async def`（FastAPI 路由、SSE generator、worker 协程、LLM 流式回调）需要调用同步 store / 同步 psycopg。
- 为什么：同步 DB 调用会阻塞整个事件循环——几个并发 SSE 客户端加一次慢查询即可停摆所有请求；worker 侧还会饿死心跳协程导致 lease 误判过期。

### 2. 签名

- store 保持同步（`PostgresTurnStore.get_turn(turn_id) -> Turn` 等），**不做**原生 async 化。
- async 调用点统一封装：`await asyncio.to_thread(store.get_turn, turn_id)`。
- worker 流式落库：`PersistedTurnStream.flush()` 为 async，内部 `async with self._flush_lock:` 先取 content 快照，再 `await asyncio.to_thread(store.append_content_snapshot, ...)`。

### 3. 契约

- `amadeus/db/postgres.py` 的连接池必须是线程安全实现（当前为 `psycopg_pool.ConnectionPool`，每次调用取池化连接）。换池实现时必须重新确认线程安全。
- 同一 turn 的事件写入必须保序：可能被并发调用的写路径需 per-stream `asyncio.Lock` 串行化，且快照捕获在锁内完成。
- 异常语义不变：store 抛出的领域异常（`OwnerResourceNotFound`、`InvalidTurnTransition` 等）从线程原样传播回 async 调用方，上层处理逻辑不因 to_thread 改变。
- 测试可直接调用的同步方法（如 `recover_stale_once`）保持同步签名，由 async 侧经 to_thread 调用。
- `PostResponseMemoryWorker` 的 claim、heartbeat、done、failed、stale recovery
  以及按消息 ID 读取 session store 都属于同步存储调用，必须逐一经
  `asyncio.to_thread`；heartbeat 发现 lease 失效时必须取消仍在执行的抽取协程。

### 4. 验证与错误矩阵

- async 路由/SSE/worker 协程中出现裸 `store.xxx(...)` 调用 -> review 阻断（本契约违规）。
- to_thread 中 store 抛 `InvalidTurnTransition`（lease 失效）-> worker 循环记日志继续，turn 交由 stale reconcile 回收，进程不得退出。
- 长回复流式期间 -> 心跳协程必须能按时运行（不被 flush 阻塞）。

### 5. Good / Base / Bad Cases

- Good：SSE 轮询体 `turn = await asyncio.to_thread(store.get_turn, turn_id)`，慢查询只占用线程池线程，事件循环继续服务其他连接。
- Base：路由中 `scope.require_turn`（内部查库）同样经 to_thread。
- Bad：`async def stream(): ... store.list_events(...)` —— 同步调用藏在辅助函数里同样违规，以实际执行路径判定。

### 6. 必需测试

- worker：注入抛错 store，断言 `run_forever` 存活且后续 turn 完成（deadline 轮询 `stats`，不裸 sleep）。
- web/SSE/worker 现有测试全绿即视为行为未回归；不要求编写事件循环阻塞性断言（不稳定）。

### 7. Wrong vs Correct

#### Wrong

```python
async def turn_events(turn_id: str):
    while True:
        turn = store.get_turn(turn_id)          # 阻塞事件循环
        events = store.list_events(turn_id, after_seq)
        ...
        await asyncio.sleep(0.25)
```

#### Correct

```python
async def turn_events(turn_id: str):
    while True:
        turn = await asyncio.to_thread(store.get_turn, turn_id)
        events = await asyncio.to_thread(store.list_events, turn_id, after_seq)
        ...
        await asyncio.sleep(0.25)
```

---

## 附：worker 主循环容错（同任务沉淀）

- `run_forever` 必须迭代级 `try/except Exception`：记 `logger.exception` 后指数退避（0.5s 起、×2、上限 10s，成功一轮复位）继续；`CancelledError` 不拦截，保持可停止。
- `run_once` 失败路径中的补救调用（`flush` + `mark_failed`）自身可能因 lease 失效再抛 `InvalidTurnTransition`，必须就地捕获只记日志——僵死 turn 由 `recover_stale_once` 回收，重复上抛只会杀死唯一 worker 进程。
