# Implementation Plan

## Guardrails

- User approved these planning artifacts on 2026-07-04. Do not start coding unless the active workflow is in implementation mode.
- Do not keep SQLite as a production fallback.
- Do not introduce ORM-centered runtime entities.
- Use Alembic for schema versioning and native SQL in stores.
- Keep Markdown memory as a first-class Akashic layer; migrate only its SQLite state/index to PostgreSQL.

## Ordered Child Work

Implementation should happen through child tasks, not directly through the parent, unless the parent needs final integration edits.

This `implement.md` is the execution source of truth for all five child slices. The child tasks do not need separate `design.md` or `implement.md` files at planning time; their `prd.md` files define local scope, explicit dependencies, and proof obligations. If a child reveals a new architectural decision during implementation, update the parent design first and then tighten that child PRD.

1. `.trellis/tasks/07-04-postgres-foundation`
2. `.trellis/tasks/07-04-turn-session-worker`
3. `.trellis/tasks/07-04-memory-postgres-pgvector`
4. `.trellis/tasks/07-04-markdown-memory-postgres-state`
5. `.trellis/tasks/07-04-docker-runtime-cleanup`

## Full Work Breakdown

1. Add PostgreSQL dependencies and config
   - Add `psycopg[binary,pool]` and `alembic`.
   - Add `AMADEUS_POSTGRES_DSN` config.
   - Fail fast when DSN is absent.
   - Add `.env.example` entries.

2. Add Alembic migration
   - Create Alembic config and initial migration.
   - Migration creates `vector` extension and all user/session/message/turn/memory/markdown-state tables.
   - Add a migration smoke test or documented command against Docker PostgreSQL.

3. Build PostgreSQL connection boundary
   - Add a small `amadeus/db/postgres.py` or equivalent owner module.
   - Provide pool lifecycle, row mapping helpers, extension check, and clean shutdown.
   - Keep SQL parameterized and explicit.

4. Replace turn store
   - Implement `PostgresTurnStore`.
   - Preserve `Turn` dataclass and statuses.
   - Claim with `FOR UPDATE SKIP LOCKED` and same-session `processing` exclusion.
   - Add duplicate-claim and same-session serialization tests.

5. Replace session/message store
   - Implement PostgreSQL-backed session store and manager boundary.
   - Add user/session/message APIs: create/list sessions, list messages.
   - Preserve `fetch_messages`, `search_messages`, source_ref resolution, and tool-chain history reconstruction.
   - Add user isolation tests.

6. Wire FastAPI to new API contracts
   - Update request/response schemas to use `user_id` and `session_id`.
   - Keep `POST /api/messages` immediate pending behavior.
   - Add session endpoints.
   - Keep turn query and SSE behavior.
   - Do not build React UI in this task.

7. Replace long-term memory store with PostgreSQL + pgvector
   - Implement `PostgresMemoryStore`.
   - Preserve current `MemoryStore` public methods or adapt through `MemoryEngine` without leaking DB details.
   - Implement vector search through `embedding <=>`.
   - Preserve source_ref, replacement, forget, undo, active/superseded behavior.
   - Add pgvector path and missing-extension fail-fast tests.

8. Migrate Markdown memory state
   - Keep Markdown files.
   - Replace `consolidation_writes.db` with `memory_markdown_writes`.
   - Move pending snapshot/recovery state to PostgreSQL if needed for crash-safe semantics.
   - Add tests proving duplicate source_ref does not append twice and no SQLite file is created.

9. Update bootstrap/runtime wiring
   - Compose PostgreSQL stores into `build_passive_app`.
   - Remove `long_term_memory_db_path` and SQLite file paths from runtime config.
   - Ensure app cleanup closes PostgreSQL pools.
   - Ensure plugin manager and tools receive the PostgreSQL-backed memory/session boundaries.

10. Add Docker default runtime
   - Add `Dockerfile`.
   - Add `docker-compose.yml` with `postgres`, `api`, `worker`, and migration command/service.
   - Persist PostgreSQL data and Markdown workspace files.
   - Add health checks and startup ordering.

11. Remove SQLite production code
   - Delete or rewrite production `sqlite3` imports in `amadeus`.
   - Remove `sessions.db`, `turns.db`, `long_term_memory.db`, and `consolidation_writes.db` assumptions.
   - Keep only explicitly named test fakes if needed.

12. Update docs/specs
   - Update `.env.example`.
   - Update backend database guidelines to describe PostgreSQL/Alembic/native SQL.
   - Add Docker usage notes.
   - Update interview evidence docs only if directly affected.

13. Collate final integration evidence
   - Parent task owns the final end-to-end acceptance.
   - The cleanup child should link to child evidence and run only consistency checks unique to cleanup.

## Validation Commands

Narrow first:

```powershell
pytest tests/turns tests/worker tests/web
```

Memory and session:

```powershell
pytest tests/memory tests/tools/test_recall_memory.py tests/tools/test_memorize_tool.py tests/tools/test_forget_memory_tool.py tests/tools/test_undo_memory_by_source_tool.py
```

Runtime/bootstrap:

```powershell
pytest tests/app tests/runtime
```

Full quality:

```powershell
ruff check amadeus tests
mypy
pytest
```

Docker/PostgreSQL smoke, when Docker is available:

```powershell
docker compose up -d postgres
docker compose run --rm migrate
docker compose up -d api worker
```

Then verify:

```powershell
curl http://127.0.0.1:8000/api/health
```

and run an API pending-turn to worker-complete smoke if LLM config is available.

## Risk Points

- Holding database locks across LLM calls would exhaust connections; use turn status serialization and short transactions only.
- Keeping `messages_json` plus row messages would create two sources of truth; use row messages as canonical.
- Rewriting Markdown memory too aggressively would lose Akashic's prompt-cache-friendly memory layer; preserve file semantics while moving SQLite state to PostgreSQL.
- pgvector embedding dimension must match configured embedding model; migration/config must make this explicit.
- Docker compose app/worker startup must not auto-create schema silently if Alembic migration has not run.

## Rollback Shape

This is a destructive switch with no SQLite data migration. Rollback is git-level only: revert this task's changes and run the previous SQLite-backed application against old local `.db` files if still present. No automatic data backfill from PostgreSQL to SQLite is planned.
