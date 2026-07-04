# PostgreSQL turn session worker runtime

## Goal

迁移 user/session/message/turn 运行时到 PostgreSQL，并让 FastAPI 请求通过 `conversation_turns` 轻量队列异步分发给 Worker。该子任务证明 100 用户下的会话归属、消息列表、turn 状态和同会话串行处理。

该子任务是轻量 PRD 切片；完整迁移设计和执行顺序以父任务 `.trellis/tasks/07-04-postgres-worker-runtime/design.md` 与 `implement.md` 为准。

## Requirements

- 使用 `user_id` 作为第一版用户隔离边界。
- 提供 `users`、`conversation_sessions`、`conversation_messages`、`conversation_turns` 的 PostgreSQL store 行为。
- Web API 提供 `POST /api/sessions`、`GET /api/sessions?user_id=...`、`GET /api/sessions/{session_id}/messages?user_id=...`、`POST /api/messages`。
- `POST /api/messages` 必须立即创建 pending turn，不直接运行 LLM。
- Worker 使用 `FOR UPDATE SKIP LOCKED` claim pending turn。
- 同一 `user_id + session_id` 最多一个 processing turn；不同 session 可并行。
- 不跨 LLM 调用持有数据库锁；只在短事务内保护 message seq/history 写入。
- `fetch_messages` / `search_messages` 从 PostgreSQL messages 解析 source_ref。

## Acceptance Criteria

- [ ] Web API session 和 message endpoint 测试通过，并证明不同 user 数据不串线。
- [ ] Turn store 并发测试证明同一 turn 不会重复 claim。
- [ ] Same-session pending turn 在已有 processing turn 时不会被 claim；other-session pending turn 可以被 claim。
- [ ] Worker 成功时写回 `done + answer`，失败时写回 `failed + error`。
- [ ] Session/message round-trip 能恢复 runtime history，包括 assistant/tool-chain 结构。
- [ ] 本子任务不引入 SQLite fallback。

## Notes

- Depends on `.trellis/tasks/07-04-postgres-foundation` for PostgreSQL config, pool, Alembic schema, and Docker database availability.
- Produces source_ref and message/session contracts consumed by `.trellis/tasks/07-04-memory-postgres-pgvector` and `.trellis/tasks/07-04-markdown-memory-postgres-state`.
- Full React frontend is out of scope.
