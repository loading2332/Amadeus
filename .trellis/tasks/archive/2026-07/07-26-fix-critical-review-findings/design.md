# 技术设计：修复 4 个严重问题

## F1 worker 容错

- `run_forever`：将 `await self.run_once()` 包进 try/except Exception；异常记 `logger.exception` 后 `asyncio.sleep(backoff)` 继续。退避从 0.5s 起、指数增长、上限 10s，成功一轮后复位。`asyncio.CancelledError` 不拦截（保持可停止）。
- `run_once` 失败路径：`mark_failed(...)` 包进 try/except Exception，失败只记日志。理由：lease 已失效时该 turn 会被 `recover_stale_once` 的 reconcile 回收，重复抛错没有价值。
- 测试：注入会抛错的 store（heartbeat/mark_failed 抛 `InvalidTurnTransition`），断言 `run_forever` 不退出且后续 turn 仍被处理（用 deadline 轮询，不裸 sleep）。

## F2 同步 DB 下沉线程

- 方案：保持 `PostgresTurnStore` 同步不变，在 async 调用点用 `asyncio.to_thread` 封装。不引入原生 async store（改动面过大，超出本任务）。
- web：`sse.py` 轮询体内的 `get_turn`/`list_events`、`routes.py` 各路由的 store 调用改为 `await asyncio.to_thread(...)`。
- worker：`PersistedTurnStream` 的落库 flush 改为 `await asyncio.to_thread(...)`（回调本身若是 async 即可直接 await；若是同步回调需先确认调用链）。注意保持事件写入的顺序性：同一 turn 的 flush 不得并发乱序——如有并发风险用 per-stream `asyncio.Lock` 串行化。
- 连接池：确认 `amadeus/db` 使用的 psycopg pool 是线程安全实现（psycopg_pool.ConnectionPool 线程安全）。若代码里是单连接/非池化，需换为池或在封装层加锁。
- 测试：现有 web/worker/SSE 测试全绿即可；不强求新增事件循环阻塞性测试（难以稳定断言），但心跳按时性已有测试不得回归。

## F3 tool-call JSON 防护

- `_extract_tool_calls` 内 `json.loads(payload)` 捕获 `json.JSONDecodeError`（含空串），失败时不抛：将该 tool call 标记为参数解析失败，走结构化降级。降级形态由实现者按 Reasoner 现有 tool 结果回传协议选择（倾向：arguments 置为 `{}` 并附带解析错误标记，使 Reasoner 能把错误作为 tool result 回传给模型自纠），流式与非流式统一走同一解析函数。
- 非流式调用点（`provider.py:126`）如仍可能抛出其他异常，纳入现有错误归一化路径。
- 测试：`tests/app/test_provider.py` 新增流式与非流式畸形 arguments 用例（截断 JSON、空串），断言不抛异常且降级结果符合协议。

## F4 前端 SSE 过滤

- `ChatView.tsx` 的 connect 循环加状态过滤：仅 `ACTIVE_TURN_STATUSES`（同文件已有集合）内的 turn 调 `turnStreamManager.connect`。
- 终态 turn 已建立的连接不需要额外清理逻辑（manager 现有 disconnect/handOff 机制不变）。
- 测试：组件测试给出含 done/failed/cancelled + processing 的 turn 列表，断言只对 processing 建连（fake EventSource 计数）。

## 回滚

四个修复相互独立、均为小改动，可按文件 revert 单独回滚。
