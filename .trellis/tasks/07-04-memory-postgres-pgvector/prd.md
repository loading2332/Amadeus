# PostgreSQL pgvector memory store

## Goal

将 Amadeus long-term memory store 从 SQLite JSON embedding 迁移到 PostgreSQL + `pgvector`，保留 Akashic-inspired retrieval、source_ref、correction/supersede、forget、undo 等公共行为。

该子任务支撑的产品和架构能力：

- 每个用户的长期记忆可按 `user_id` 隔离存储和检索。
- semantic retrieval 使用真实 PostgreSQL `pgvector`，不是 Python 全表扫描。
- `MemoryEngine` / memory tools 仍是 runtime 访问长期记忆的公共边界，runtime 不直接依赖数据库 schema。
- 后续 Markdown memory PostgreSQL state 和 Docker cleanup 可以清掉 `long_term_memory.db` 生产路径。

该子任务是轻量 PRD 切片。完整迁移设计和执行顺序以父任务 `.trellis/tasks/07-04-postgres-worker-runtime/design.md` 与 `implement.md` 为准。

## Confirmed Facts

- 前置任务已完成：
  - `.trellis/tasks/07-04-postgres-foundation`
  - `.trellis/tasks/07-04-turn-session-worker`
- 当前 Alembic migration 已创建 `memory_items`、`memory_replacements`，并启用 `vector` extension；`memory_items.embedding` 当前按用户实际 Qwen `text-embedding-v4` 配置收敛为 `vector(1024)`。
- 当前 `amadeus/memory/store.py` 仍是 SQLite store：
  - 初始化 `long_term_memory.db`；
  - `embedding` 以 JSON text 保存；
  - `memory_replacements` 无 `user_id`；
  - scope 信息放在 `extra_json.scope_channel/scope_chat_id`；
  - `upsert_item` 通过 `source_ref + memory_type` 跳过重复写入，通过 `content_hash + memory_type` reinforcement。
- 当前 `amadeus/memory/retriever.py` 仍是 store 拉取 active rows，再用 Python `rank_multi_query_rows()` 做 vector/lexical/hotness 排名。
- 当前 `amadeus/memory/memorizer.py` 通过 store API 实现 memorize、replace、supersede_many、forget、undo_by_source；这些公共行为必须保持。
- 当前 tests 覆盖 memory store schema、replacement chain、reinforcement、replace/undo、supersede_many、forget tool、recall evidence/source_ref、time filter trace 和 ranking signals。
- 当前 bootstrap 仍构造 `long_term_memory_db_path = root / "memory" / "long_term_memory.db"`；本子任务需要把 long-term memory wiring 改到 PostgreSQL，但不处理 Markdown memory 的 SQLite index。

## Requirements

- R1. 实现 PostgreSQL-backed long-term memory store，生产 runtime 不再创建或依赖 `long_term_memory.db`。
- R2. Store 必须按 `user_id` 隔离 memory items 和 replacements；默认 legacy/runtime 入口可先使用 `user_id=1`，但 API 和 schema 行为必须支持不同 user 不串线。
- R3. `memory_items.embedding` 必须使用 `pgvector` 类型；retrieval 的语义候选召回必须通过 SQL vector distance operator，例如 `<=>`，不允许把 Python 全表扫描作为完成态。
- R4. 保留现有 public store/memorizer/retriever/tool 行为：source_ref 去重、content reinforcement、active/superseded lifecycle、replacement relation、forget、undo_by_source。
- R5. 保留 recall output、evidence/source_ref、citation contract、time filter trace、scope fallback、lexical/hotness/ranking signals；可以把 SQL vector score 作为候选召回信号输入现有 ranking 层。
- R6. 缺少 PostgreSQL `vector` extension 或 schema 未迁移时，store/bootstrap 必须 fail fast。
- R7. Runtime/bootstrap wiring 必须使用 `PostgresMemoryStore`，并删除 `RuntimeConfig.long_term_memory_db_path` 作为生产配置源。
- R8. 现有 SQLite `MemoryStore` 可以在过渡中作为测试 fake 或历史代码保留，但不得被 production bootstrap 使用，并且命名/文档必须避免误导。
- R9. pgvector embedding dimension 必须与当前 schema/config 一致；本子任务使用 Qwen `text-embedding-v4` 默认维度 `vector(1024)`，并测试证明维度不匹配会失败或被明确拒绝。

## Acceptance Criteria

- [ ] 新增 `PostgresMemoryStore` 或等价 PostgreSQL store，覆盖当前 `MemoryStore` 的运行时方法：
  - `insert_item`
  - `upsert_item`
  - `record_replacement`
  - `list_replacements_for`
  - `find_replacements_by_source_ref`
  - `list_active_items`
  - `find_items_by_source_ref`
  - `get_items_by_ids`
  - `get_item_by_id`
  - `mark_items_status`
- [ ] Existing memory store/memorizer/retriever/tool tests 迁移或扩展后通过 PostgreSQL-backed 实现。
- [ ] Retrieval 测试证明 SQL 使用 pgvector distance operator，而不是只调用 Python ranking 做全表扫描。
- [ ] 缺少 `vector` extension 或未迁移 schema 时，PostgreSQL memory store 初始化或 bootstrap fail fast。
- [ ] source_ref 去重、content reinforcement、supersede/replacement、forget、undo_by_source 公共行为可观察。
- [ ] user isolation 测试证明 user 1 的 memory 不会被 user 2 recall/list/mutate。
- [ ] recall evidence/source_ref 仍可通过 PostgreSQL session messages 回源。
- [ ] time filter、scope filter、scope fallback、ranking trace 中的 vector/lexical/hotness signals 保持可观察。
- [ ] `build_passive_app` 在 long-term memory enabled 时使用 PostgreSQL-backed memory store，不创建 `memory/long_term_memory.db`。
- [ ] 本子任务完成后，`rg -n "long_term_memory\\.db" amadeus tests` 不显示生产 bootstrap 依赖；测试 fixture 若仍命中必须是明确 legacy/fake。

## Technical Notes

- 推荐保留 `MemoryMemorizer` 和 `MemoryRetriever` 的高层行为，把数据库实现替换到 store 边界。
- 推荐给 retriever 增加 store-level vector candidate method，例如 `search_active_items(...)`，由 PostgreSQL SQL 先按 `embedding <=> query_embedding`、`user_id`、status、type、scope、time filters 召回候选，再交给现有 ranking 层补 lexical/hotness trace。
- `content_hash` 当前存在于 SQLite schema，但初始 PostgreSQL migration 尚未包含该列；实现时需要通过追加 Alembic migration 或 `extra_json` 方案补齐。推荐追加真实 `content_hash TEXT NOT NULL` 和 `UNIQUE(user_id, memory_type, content_hash)` / source_ref 相关索引，避免把核心去重约束藏进 JSON。
- 当前 `memory_replacements` 已有 `user_id`，实现时所有 replacement 查询都必须带 user scope。
- `scope_channel` / `scope_chat_id` 可以继续保存在 `extra_json`，但查询必须由 SQL 过滤，避免跨 scope 候选污染。
- Akashic reference 重点是行为契约：source_ref、replacement lifecycle、post-response memory mutation、retrieval evidence。PostgreSQL/pgvector 是 Amadeus-specific extension。

## Dependencies

- Depends on `.trellis/tasks/07-04-postgres-foundation` for PostgreSQL config, pool, Alembic, Docker PostgreSQL, and `vector` extension availability.
- Depends on `.trellis/tasks/07-04-turn-session-worker` for stable `user_id`, session/message ownership, and source_ref shape.
- Blocks `.trellis/tasks/07-04-markdown-memory-postgres-state` full integration because Markdown pending ingestion writes into long-term memory.
- Blocks `.trellis/tasks/07-04-docker-runtime-cleanup` because cleanup cannot remove `long_term_memory.db` production references until this is done.

## Validation Commands

Narrow expected commands for implementation:

```powershell
uv run pytest -q tests/memory/test_memory_store.py tests/memory/test_memory_memorizer.py tests/memory/test_forget_memory_tool.py tests/tools/test_undo_memory_by_source_tool.py
uv run pytest -q tests/memory/test_memory_retrieval_acceptance.py tests/tools/test_recall_memory.py tests/tools/test_memorize_tool.py tests/tools/test_forget_memory_tool.py
uv run pytest -q tests/memory/test_bootstrap_long_term_memory.py tests/app/test_bootstrap.py
uv run ruff check amadeus/memory amadeus/tools tests/memory tests/tools
```

Docker/PostgreSQL prerequisite:

```powershell
docker compose up -d postgres
uv run alembic upgrade head
```

## Out of Scope

- 不迁移 Markdown memory `consolidation_writes.db`；该工作属于 `.trellis/tasks/07-04-markdown-memory-postgres-state`。
- 不迁移已有 SQLite 数据。
- 不重做 memory ranking 算法，只把语义候选召回迁到 pgvector 并保持现有 trace/排序合同。
- 不实现 Telegram、Scheduler、ProactiveLoop 或 DriftRunner。
- 不要求真实 OpenAI embeddings smoke；测试可使用 deterministic embedding provider。

## Open Questions

- None.

## Approval

- User approved this PRD as the implementation input on 2026-07-04.
- This lightweight child does not need separate `design.md` / `implement.md` because the parent task owns the full migration design and implementation order.
