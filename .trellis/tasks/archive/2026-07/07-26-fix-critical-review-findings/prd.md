# 修复 review 发现的严重问题

## Goal

修复 2026-07-26 全项目 review 发现的 4 个严重问题（3 后端 + 1 前端）。只修严重档，不扩散到中等问题。

## Requirements

### F1: worker 主循环容错

- 现状：`amadeus/worker/turn_worker.py` `run_forever` 无异常防护；`run_once` 的 except 分支调用 `mark_failed`，当 lease 失效或 DB 瞬断时 `mark_failed` 内部 `_lock_leased`（`amadeus/turns/postgres.py:642-647`）会再次抛出同类异常，击穿到顶层，worker 进程退出。
- 要求：
  - `run_forever` 单次迭代的异常不得杀死进程；异常后记录日志并带退避地继续循环。
  - `run_once` 失败路径中的 `mark_failed` 调用自身抛错时不得向上击穿（记录后继续；僵死 turn 交由已有的 reconcile 机制回收）。

### F2: async 路径上的同步 DB 调用

- 现状：`PostgresTurnStore` 全部为同步 psycopg。`amadeus/web/sse.py` 在 async generator 中每 0.25s 同步查库；`amadeus/web/routes.py` 的 async 路由同步调 store；worker 侧 `PersistedTurnStream.publish_content → flush()` 在 LLM 流式回调里同步写库并阻塞心跳协程。
- 要求：
  - web 层（sse.py、routes.py）所有对同步 store 的调用不再阻塞事件循环（可用 `asyncio.to_thread` 封装，不要求把 store 改成原生 async）。
  - worker 流式回调中的写库不再阻塞事件循环（心跳协程在长回复期间能按时运行）。
  - 必须确认底层连接池在多线程并发下安全；若不安全需在封装层保证。

### F3: provider tool-call JSON 解析防护

- 现状：`amadeus/provider.py:239` 对 tool-call arguments 的 `json.loads` 无 try/except；非流式路径 `_extract_tool_calls` 调用点（`provider.py:126`）在错误归一化 try 块之外。畸形 JSON 直接炸掉整个 turn。
- 要求：
  - 畸形 arguments 不得使整个 turn 失败；按现有架构选择合理降级（如把解析失败作为该 tool call 的结构化错误传递，让模型可以重试/更正），流式/非流式两条路径行为一致。
  - 新增测试覆盖畸形 tool-call JSON（流式与非流式）。

### F4: 前端历史 turn SSE 风暴

- 现状：`frontend/src/chat/ChatView.tsx:46-49` 对会话内所有 turn（含 done/failed/cancelled）逐个 `turnStreamManager.connect`，后端从 seq 0 全量重放，N 条历史 = N 个并发 EventSource + 4N 次 invalidation。
- 要求：
  - 只对活跃状态（pending/processing/finalizing，即同文件已有的 ACTIVE 集合）建立 SSE 连接。
  - 更新/新增组件测试覆盖“历史终态 turn 不建连接”。

## Constraints

- 不得触碰当前未提交的 prompt-cache-benchmark 相关文件（`amadeus/evaluation/prompt_cache_*`、`amadeus/prompting/assembler.py`、`tests/prompting/*`、`CONTEXT.md`、`docs/prompt-cache-benchmark.md`）。
- 不做超出 4 个严重问题范围的重构；中等问题（heartbeat 孤儿任务、缓存无界等）不在本任务内。

## Acceptance Criteria

- [ ] F1: 模拟 lease 失效/存储抛错的测试证明 worker 循环存活并继续处理后续 turn。
- [ ] F2: web/worker 的 async 路径不再直接同步调 store（to_thread 封装可见）；现有 SSE/web/worker 测试全绿。
- [ ] F3: 畸形 tool-call JSON 测试（流式 + 非流式）通过，turn 不因解析失败而整体失败。
- [ ] F4: 前端测试证明终态 turn 不建 SSE 连接；`pnpm typecheck && pnpm lint && pnpm test` 全绿。
- [ ] 后端 `uv run pytest` 全绿（Postgres 可用时含集成测试）。
