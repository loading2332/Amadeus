# PostgreSQL foundation and Docker database

## Goal

建立 Amadeus 的 PostgreSQL 基础设施：依赖、配置、连接池、Alembic 版本管理、`pgvector` extension 检测，以及数据库层 Docker 环境。该子任务为后续 turn/session/memory 迁移提供可验证的数据库基座。

该子任务是轻量 PRD 切片；完整迁移设计和执行顺序以父任务 `.trellis/tasks/07-04-postgres-worker-runtime/design.md` 与 `implement.md` 为准。

## Requirements

- 添加 PostgreSQL 客户端依赖和 Alembic。
- 新增 `AMADEUS_POSTGRES_DSN` 配置，缺失时 fail fast。
- 使用 Alembic 管理 schema 版本，不在运行时 store 中隐式创建生产表。
- 初始 migration 创建 `vector` extension，并创建后续子任务所需基础 schema。
- 提供 PostgreSQL pool/connection 边界，供后续 store 复用。
- 提供 Docker Compose 中的 `postgres` 服务，镜像必须支持 `pgvector`。
- 不接入 ORM business model；运行时数据库访问后续走原生 SQL。

## Acceptance Criteria

- [ ] `alembic upgrade head` 可在空 PostgreSQL 数据库上成功执行。
- [ ] 启动配置缺少 `AMADEUS_POSTGRES_DSN` 时失败且不创建 SQLite 文件。
- [ ] PostgreSQL 连接边界可检测 `vector` extension；缺失或不可用时报错。
- [ ] Docker `postgres` 服务可启动并通过 health check。
- [ ] `.env.example` 包含 PostgreSQL DSN 和 Docker 默认值。

## Notes

- Parent task: `.trellis/tasks/07-04-postgres-worker-runtime`.
- Depends on no other child tasks; it must land before every other child.
- This child should land before all other implementation children.
- User approved starting implementation from this child after planning on 2026-07-04.
