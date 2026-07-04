# Migrate persistence to PostgreSQL worker runtime

## Goal

将 Amadeus 的运行时持久化从本地 SQLite 文件完全迁移到 PostgreSQL，并保留现有 Web Turn + Worker 的异步产品行为：FastAPI 请求只创建 pending turn 并快速返回，Worker 异步消费 turn、运行真实 passive runtime、写回 answer/error，同时用 PostgreSQL 并发控制避免同一 session 的上下文写入乱序。

该任务支持的产品/架构能力：

- Passive runtime 可以在异步 Worker 中运行真实 LLM turn，而不是阻塞 FastAPI 请求。
- user/session/message/turn/memory 使用同一个 PostgreSQL 持久化边界，放弃 SQLite 作为生产状态源。
- `conversation_turns` 是轻量任务队列的公共行为入口，状态变化可被 API/SSE/测试观察。
- 同一 session 的消息序列和 memory 写入有明确并发边界，降低并发请求导致的上下文乱序。

## Confirmed Facts

- 当前仓库仍直接依赖 SQLite：
  - `amadeus/session/store.py` 使用 `sessions.db` 存储 `sessions` 和 `messages`。
  - `amadeus/turns/store.py` 使用 `turns.db` 存储 `conversation_turns`，并用 `BEGIN IMMEDIATE` 模拟 claim 队列。
  - `amadeus/memory/store.py` 使用 SQLite 存储 `memory_items` 和 `memory_replacements`。
  - `amadeus/memory/markdown.py` 仍有 markdown memory index 的 SQLite 使用。
- 当前 Web 产品行为已存在：`POST /api/messages` 创建 pending turn 后返回，`TurnWorker` claim pending turn 后调用 `PassiveRuntime.run_turn`，再 `mark_done` 或 `mark_failed`。
- 当前测试已覆盖：
  - turn 创建、读取、claim、同 session processing 互斥、terminal 写回；
  - Worker 成功/失败写回；
  - FastAPI 创建 pending turn、查询 turn、SSE 输出 terminal turn。
- `pyproject.toml` 当前没有 PostgreSQL 客户端、SQLAlchemy、migration 工具或 pgvector 依赖。
- 当前仓库没有 Docker/PostgreSQL/compose/devcontainer 配置文件。
- Akashic 参考仓库没有 PostgreSQL 版本；可迁移的是设计契约，不是数据库实现：
  - session/message 的 `next_seq` 单调写入与 source_ref 可追踪；
  - Markdown memory 是独立记忆层，负责 human-readable profile、self model、recent context、history timeline、pending buffer，并非可直接删除的遗留实现；
  - memory 的 source_ref 去重、active/superseded 状态、replacement relation；
  - post-response memory worker 的写入/纠错/遗忘生命周期；
  - 队列/Worker 的失败可见性和可重试边界。

## Requirements

- R1. 生产运行时不得再创建或依赖 SQLite 文件作为 user/session/message/turn/memory 的状态源。
- R2. PostgreSQL schema 必须覆盖 user、session、message、conversation_turn、memory item、memory replacement 等当前运行时必需数据。
- R2a. Schema 和 API 分发必须按“约 100 个真实用户同时使用”设计：用户、会话列表、消息列表、个人记忆都要有明确归属和查询边界。
- R2b. 本任务先使用内部 `user_id` 作为用户隔离边界；认证/登录系统不在本任务内，但 API、turn、session、message、memory 必须都可追溯到 `user_id`。
- R3. `conversation_turns` 必须支持 lightweight queue 行为：create pending、claim processing、mark done/failed、read by id、API/SSE 可见。
- R3a. Web API 第一版必须提供最小会话产品接口：为 `user_id` 创建 session、按 `user_id` 列出 sessions、按 `user_id + session_id` 列出 messages，并要求发消息时绑定 `user_id + session_id`。
- R4. Worker 必须异步消费 PostgreSQL 中的 pending turns，并把真实 runtime 结果写回 `conversation_turns`。
- R5. Turn claim 必须使用 PostgreSQL 级并发控制，目标形状为 `FOR UPDATE SKIP LOCKED`，避免多个 worker claim 同一 turn。
- R6. 同一 session 的上下文写入必须有并发边界，目标形状为 session 级锁或等价 PostgreSQL 锁，保证 message seq 与 runtime history 不乱序。
- R6a. 用户认可方案 B：不跨 LLM 调用持有数据库锁；同一 `user_id + session_id` 通过 `conversation_turns` 状态机保证最多一个 `processing` turn，数据库锁只用于短事务内写 user message、读 history snapshot、写 assistant message/turn result。
- R7. Memory 迁移必须保留 Akashic-inspired 公共行为：retrieval、source reference、correction/supersede、forget/undo 可观察。
- R7a. Memory retrieval 必须真正使用 PostgreSQL vector 能力；`pgvector` 是生产硬要求，不允许把 Python 全表扫描当作完成态。
- R7b. Markdown memory 必须作为独立记忆层保留：`MEMORY.md`、`SELF.md`、`RECENT_CONTEXT.md`、`HISTORY.md`、`PENDING.md` 的语义和 consolidation/optimizer 流程不能被向量层替代。
- R7c. Markdown memory 的幂等写入索引、pending snapshot 状态或其他运行时状态必须迁到 PostgreSQL；不得继续使用 `consolidation_writes.db` 或任何 SQLite 文件。
- R7d. Markdown 内容文件继续保存在 workspace / Docker volume 中；PostgreSQL 管理用户归属、幂等写入记录、pending snapshot/状态、与 message/source_ref 的一致性。
- R8. 配置必须显式要求 PostgreSQL 连接信息；缺失时应 fail fast，不静默回退到 SQLite。
- R9. 启动时必须检测 PostgreSQL `vector` extension；不可用时 fail fast。
- R10. 不允许保留 SQLite 生产遗留路径；`session`、`turns`、long-term memory、markdown memory index 若仍存在必须全部迁到 PostgreSQL 或明确删除对应生产能力。
- R11. 本任务是破坏性切换，不迁移本机已有 SQLite 数据；旧 `.db` 文件不是新运行时的输入。
- R12. Docker Compose 应成为产品化默认运行形态，覆盖 PostgreSQL + pgvector、FastAPI Web API、Turn Worker；本机命令可保留为开发辅助。
- R13. Compose 启动必须处理数据库健康检查、`pgvector` 可用性、app/worker 环境变量和启动顺序。
- R14. Schema 版本使用 Alembic 管理，但运行时代码使用原生 SQL / explicit store API，不以 ORM entity 作为核心业务模型。
- R15. 重要行为必须通过代码证据和可运行验证证明；不能只写文档声称迁移完成。

## Acceptance Criteria

- [ ] 子任务按顺序完成并通过各自验收：
  - `.trellis/tasks/07-04-postgres-foundation`
  - `.trellis/tasks/07-04-turn-session-worker`
  - `.trellis/tasks/07-04-memory-postgres-pgvector`
  - `.trellis/tasks/07-04-markdown-memory-postgres-state`
  - `.trellis/tasks/07-04-docker-runtime-cleanup`
- [ ] `rg -n "sqlite3|sessions\\.db|turns\\.db|long_term_memory\\.db" amadeus tests` 不再显示生产运行时依赖 SQLite 的 user/session/message/turn/memory 路径；若仍存在测试 fixture 或明确非生产路径，必须有命名和文档解释。
- [ ] `amadeus/memory/markdown.py` 不再使用 SQLite index；Markdown memory 的 `source_ref/kind/target` 幂等记录由 PostgreSQL 表保证。
- [ ] `POST /api/messages` 仍快速返回 pending turn，不直接运行 LLM turn。
- [ ] Worker 可从 PostgreSQL claim pending turn，成功时写回 `done + answer`，失败时写回 `failed + error`。
- [ ] 并发 Worker 测试证明同一 pending turn 不会被重复 claim。
- [ ] 同一 session 并发 turn 测试证明不会并行写乱 message seq/history；不同 session 可并行处理。
- [ ] Session/message round-trip 测试证明 user/assistant/tool-chain 历史从 PostgreSQL 恢复后仍可供 runtime 使用。
- [ ] Memory store 公共行为测试证明 source_ref 去重、retrieval、supersede/replacement、forget/undo 仍通过 PostgreSQL 工作。
- [ ] Memory retrieval 测试证明相似度查询走 `pgvector` 路径，并且无 `vector` extension 时启动失败。
- [ ] Markdown memory 测试证明 `HISTORY.md` / `PENDING.md` / `RECENT_CONTEXT.md` 仍按 Akashic 语义工作，重复 `source_ref` 不会重复追加，且不会创建 SQLite 文件。
- [ ] Web API/SSE 测试改用 PostgreSQL-backed store 并通过。
- [ ] Runtime/bootstrap 配置测试证明缺少 PostgreSQL DSN 会 fail fast，且不会创建 SQLite 文件。
- [ ] 100 用户产品化路径有行为证明：不同 user 的 session/message/memory 查询互不串线，同一 user 可列出自己的会话和消息。
- [ ] Web API 提供并测试：`POST /api/sessions`、`GET /api/sessions?user_id=...`、`GET /api/sessions/{session_id}/messages?user_id=...`、`POST /api/messages` with `user_id + session_id`。
- [ ] `docker-compose` 能启动 PostgreSQL + pgvector、FastAPI、Worker，并能通过 health check 表明数据库可用。
- [ ] Alembic 可从空 PostgreSQL 数据库升级到 head，生成 user/session/message/turn/memory/pgvector 所需 schema。
- [ ] 文档或 `.env.example` 给出 Docker 默认 DSN、app/worker 启动方式、常用验证命令。
- [ ] 运行并记录最窄有意义验证命令；至少覆盖 turns、worker、web、session、memory 相关测试。

## Out of Scope

- 不在本任务中实现 Telegram outbound、Scheduler、ProactiveLoop 或 DriftRunner。
- 不迁移或重建 Akashic 的目录结构。
- 不把 PostgreSQL 迁移做成 SQLite/PostgreSQL 双栈长期兼容层；本目标是放弃 SQLite。
- 不迁移已有 SQLite 数据；如后续需要，可单独做 one-shot importer。
- 不要求真实 LLM 或真实 Telegram smoke，除非配置可用且用户明确要求集成验证。
- 不在本任务中重做完整前端；React 会话列表 UI 等新 API 和 PostgreSQL 稳定后另做。

## Task Map

This parent task is the planning source of truth for the overall architecture, cross-child design, and ordered implementation plan. Child tasks are intentionally lightweight PRD slices unless a child discovers new complexity during implementation; their role is to define independently verifiable scope and dependencies, not to duplicate the parent `design.md` and `implement.md`.

- `07-04-postgres-foundation`: PostgreSQL dependency/config/pool, Alembic, `pgvector`, and database Docker base.
- `07-04-turn-session-worker`: user/session/message/turn PostgreSQL stores, minimum session API, Worker queue, same-session serialization.
- `07-04-memory-postgres-pgvector`: long-term memory store on PostgreSQL + pgvector with source_ref and mutation lifecycle.
- `07-04-markdown-memory-postgres-state`: keep Markdown memory files, migrate Markdown write/state index from SQLite to PostgreSQL.
- `07-04-docker-runtime-cleanup`: align Docker/runtime configuration, remove SQLite production leftovers, update docs/specs, and collate evidence for parent final integration.

## Open Questions

- None.

## Notes

- Akashic reference: `../akashic-agent/session/store.py`, `../akashic-agent/memory2/store.py`, `../akashic-agent/memory2/post_response_worker.py`, `../akashic-agent/bus/queue.py`, and related tests. PostgreSQL-specific queue/locking is Amadeus project-specific because Akashic has no matching PostgreSQL mechanism.
- Akashic Markdown memory reference: `../akashic-agent/_handbook/memory-markdown.md` says Akashic has two memory layers: Markdown file layer for human-readable full-picture memory and vector DB layer for semantic retrieval. This task must preserve that layering while replacing SQLite state with PostgreSQL.
- User approved keeping Markdown content files while moving Markdown runtime state/indexes to PostgreSQL; SQLite must not remain for Markdown memory.
- User clarified that this migration is mainly for productization under roughly 100 users: FastAPI receives requests, routes them into the reply pipeline, stores each user's conversations and memories in PostgreSQL, and uses locks to prevent same-session context corruption.
- User approved hard-requiring `pgvector`; Amadeus has not previously used a real database vector plugin for memory retrieval, so this task should make that capability real instead of preserving the old JSON embedding scan shape.
- User approved using `user_id` as the first user isolation boundary and emphasized that SQLite must be fully replaced by PostgreSQL without historical leftover production paths.
- User confirmed no existing SQLite data migration is required.
- User prefers taking the short-term pain to make Docker the convenient default going forward, likely including app and worker rather than only the database.
- User prefers Alembic only for migration/version control, with runtime database access using native SQL rather than ORM-centered business models.
- User approved concurrency option B: serialize same-session work through conversation_turns processing state and use database locks only for short database transactions, not across LLM calls.
- User confirmed the first version needs minimal session APIs for creating/listing sessions and listing messages, not only turn creation.
- User wants to leave frontend redesign untouched for now; after the new API and PostgreSQL backend are stable, the frontend should be implemented fully in React.
- User approved splitting the migration into child tasks while keeping this task as the parent for total design and final integration acceptance.
- User reviewed and approved the planning direction on 2026-07-04; implementation should start with `.trellis/tasks/07-04-postgres-foundation` when the workflow enters implementation mode.
