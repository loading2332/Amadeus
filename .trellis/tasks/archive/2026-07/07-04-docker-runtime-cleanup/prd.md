# Docker runtime cleanup and PostgreSQL integration

## Goal

在 PostgreSQL foundation、turn/session worker、pgvector memory、Markdown memory PostgreSQL state 全部完成之后，完成运行时收口：让 Docker Compose、migration、API、worker、配置、文档和数据库规范对齐到同一个 PostgreSQL 默认运行形态，并移除生产路径里的 SQLite 遗留。

该子任务不重新实现或重新证明各子系统核心行为；它负责清除配置漂移、生产遗留和文档缺口，并整理父任务最终验收所需的证据入口。

该子任务是轻量 PRD 切片。完整迁移设计和执行顺序以父任务 `.trellis/tasks/07-04-postgres-worker-runtime/design.md` 与 `implement.md` 为准。

## Confirmed Facts

- `07-04-postgres-foundation` 已完成 PostgreSQL/Alembic/pgvector foundation，并且真实 Docker PostgreSQL health check 和 Alembic upgrade 已通过。
- `07-04-turn-session-worker` 已完成 PostgreSQL user/session/message/turn store、最小 session API、Worker claim、同 session serialization，并通过相关测试。
- `07-04-memory-postgres-pgvector` 仍是 `planning`，所以 `amadeus/memory/store.py` 仍存在生产 SQLite long-term memory 路径。
- `07-04-markdown-memory-postgres-state` 仍是 `planning`，所以 `amadeus/memory/markdown.py` 仍存在 `consolidation_writes.db` / SQLite index 路径。
- 当前 `docker-compose.yml` 只有 `postgres` service，还没有 `api`、`worker`、migration service/command 或 Markdown workspace volume。
- 当前 `.env.example` 已有 `AMADEUS_POSTGRES_DSN=postgresql://amadeus:amadeus@localhost:5432/amadeus`，但 Docker app/worker 使用说明和 migration 流程尚未文档化。
- 当前 `.trellis/spec/backend/database-guidelines.md` 仍描述 SQLite 持久化规范，不能作为 PostgreSQL runtime 的当前规范。
- 当前 `rg -n "sqlite3|sessions\\.db|turns\\.db|long_term_memory\\.db|consolidation_writes\\.db|DATABASE_PATH|sqlite|SQLite" amadeus .env.example docker-compose.yml docs .trellis/spec` 显示仍有生产和历史文档命中；cleanup 需要逐项分类处理。

## Requirements

- R1. 只有在 `memory-postgres-pgvector` 和 `markdown-memory-postgres-state` 完成后，才能进入本子任务实现；否则 cleanup 会误删仍在用的 memory SQLite 代码或产生半迁移文档。
- R2. Docker Compose 必须对齐 `postgres`、`api`、`worker`、migration、Markdown workspace volume、health check、启动顺序和环境变量。
- R3. `api` 和 `worker` 必须使用同一 PostgreSQL DSN 约定；缺少 DSN、未迁移 schema 或缺少 `vector` extension 时应 fail fast，不静默回退 SQLite。
- R4. 生产路径中不得保留 SQLite imports、`.db` 默认路径、fallback backend、旧环境变量或误导性注释。测试 fake 或历史文档可以保留，但必须命名清楚且不被生产 bootstrap 使用。
- R5. 文档必须说明默认 Docker 运行流程、migration 流程、API/Worker 启动方式、Markdown workspace volume、常用调试命令和明确非目标项。
- R6. `.trellis/spec/backend/database-guidelines.md` 必须更新为 PostgreSQL/Alembic/native SQL 约定，不再把 SQLite store `_init_schema()` 描述为当前生产规范。
- R7. 父任务最终验收清单必须逐项映射到子任务证据、验证命令或明确未覆盖说明；本子任务只补 cleanup 层验证，不复制前置子任务核心行为测试。

## Acceptance Criteria

- [ ] 所有前置子任务状态均为 completed：
  - `.trellis/tasks/07-04-postgres-foundation`
  - `.trellis/tasks/07-04-turn-session-worker`
  - `.trellis/tasks/07-04-memory-postgres-pgvector`
  - `.trellis/tasks/07-04-markdown-memory-postgres-state`
- [ ] `docker-compose.yml` 覆盖 PostgreSQL + pgvector、API、Worker、migration、PostgreSQL volume、Markdown workspace volume 和 health/startup ordering。
- [ ] `.env.example`、bootstrap 配置、worker/API 启动命令使用一致的 PostgreSQL/Alembic/Markdown volume 约定，没有互相矛盾的 DSN 或旧 SQLite 变量。
- [ ] `rg -n "sqlite3|sessions\\.db|turns\\.db|long_term_memory\\.db|consolidation_writes\\.db|DATABASE_PATH" amadeus .env.example docker-compose.yml docs .trellis/spec` 的结果已逐项处理：生产遗留清除，测试 fake 或历史文档有明确命名。
- [ ] 文档说明默认 Docker 运行流程、migration 流程、API/Worker 启动方式、Markdown workspace volume、常用调试命令和已知非目标项。
- [ ] 后端数据库规范更新为 PostgreSQL/Alembic/native SQL 约定，不再描述 SQLite store `_init_schema()` 作为当前生产规范。
- [ ] 父任务最终验收清单中每项都有对应子任务证据、命令或明确未覆盖说明；cleanup 不复制前置子任务核心行为测试。
- [ ] cleanup 层验证命令通过，至少包括 lint、SQLite 遗留扫描、Docker PostgreSQL/API/Worker/migration smoke，以及相关 bootstrap/runtime tests。

## Out of Scope

- 不实现 pgvector memory store；该工作属于 `.trellis/tasks/07-04-memory-postgres-pgvector`。
- 不迁移 Markdown memory SQLite state；该工作属于 `.trellis/tasks/07-04-markdown-memory-postgres-state`。
- 不重做 Web frontend 或 React session UI。
- 不迁移旧 SQLite 数据。
- 不要求真实 LLM 或 Telegram smoke，除非配置可用且用户明确要求集成验证。

## Implementation Gate

当前本子任务不应进入 implementation。原因是两个 memory 前置子任务仍在 planning，仓库中仍存在生产 memory SQLite 路径：

- `amadeus/memory/store.py`
- `amadeus/memory/markdown.py`
- `amadeus/app/bootstrap.py` 的 `long_term_memory.db` 配置路径

推荐执行顺序：

1. 回到 `.trellis/tasks/07-04-memory-postgres-pgvector` 完成 pgvector memory store。
2. 完成 `.trellis/tasks/07-04-markdown-memory-postgres-state`。
3. 再进入本 cleanup 子任务，实现 Docker/app/worker/migration/docs/spec/evidence 收口。

## Open Questions

- 是否接受本子任务保持为 blocked-by-dependencies 的 planning 状态，并先回到 `memory-postgres-pgvector` 子任务？

推荐答案：接受。这样不会在 memory 迁移未完成时提前删除或文档化错误的运行路径。

如果选择不同：可以先做部分 Docker/docs cleanup，但必须保留 memory SQLite 例外，最终还要再返工一次，不符合“生产路径完全无 SQLite 遗留”的父任务验收。
