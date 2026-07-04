# PostgreSQL state for Markdown memory

## Goal

保留 Akashic Markdown memory 作为独立记忆层，同时把 Markdown memory 的 SQLite 状态迁移到 PostgreSQL。Markdown 文件继续存在，`consolidation_writes.db` 等 SQLite 文件不再创建。

该子任务是轻量 PRD 切片；完整迁移设计和执行顺序以父任务 `.trellis/tasks/07-04-postgres-worker-runtime/design.md` 与 `implement.md` 为准。

## Requirements

- 保留 `MEMORY.md`、`SELF.md`、`RECENT_CONTEXT.md`、`HISTORY.md`、`PENDING.md` 的语义。
- 保留 consolidation、recent turns refresh、pending buffer、optimizer snapshot/commit/rollback 语义。
- 使用 PostgreSQL 表记录 Markdown 写入幂等状态，例如 `memory_markdown_writes(user_id, source_ref, kind, target)`。
- 如果 pending snapshot/recovery 需要运行时状态，也必须使用 PostgreSQL，不得使用 SQLite。
- Markdown content files 保存在 workspace / Docker volume 中。
- Markdown 层不替代 pgvector memory；两层分工按 Akashic 文档保留。

## Acceptance Criteria

- [ ] Markdown memory duplicate `source_ref` 写入不会重复追加 `HISTORY.md` / `PENDING.md`。
- [ ] 相关测试证明 `RECENT_CONTEXT.md` refresh 和 consolidation 语义仍工作。
- [ ] `consolidation_writes.db` 不再创建。
- [ ] `rg -n "sqlite3" amadeus/memory/markdown.py` 无生产 SQLite 使用。
- [ ] Markdown memory 与 PostgreSQL message source_ref 能一致回源。

## Notes

- Depends on `.trellis/tasks/07-04-postgres-foundation` for PostgreSQL config, pool, Alembic schema, and Docker database availability.
- Depends on `.trellis/tasks/07-04-turn-session-worker` for stable `user_id`, session/message ownership, and source_ref shape.
- Should run after `.trellis/tasks/07-04-memory-postgres-pgvector` enough to preserve the two-layer memory boundary in integration tests.
- Akashic reference: `../akashic-agent/_handbook/memory-markdown.md`.
