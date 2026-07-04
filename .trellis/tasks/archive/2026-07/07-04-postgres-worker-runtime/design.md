# PostgreSQL Worker Runtime Design

## Architecture

This migration makes PostgreSQL the only production state backend while preserving Amadeus runtime boundaries.

```text
FastAPI
  -> PostgresTurnStore.create_turn(user_id, session_id, message)
  -> immediate pending response

TurnWorker
  -> PostgresTurnStore.claim_next_pending()
  -> PassiveRuntime.run_turn(...)
  -> PostgresTurnStore.mark_done / mark_failed

PassiveRuntime
  -> PostgresSessionStore for history/messages
  -> AkashicMemoryEngine backed by PostgresMemoryStore + pgvector
  -> MarkdownMemoryRuntime backed by markdown files + PostgreSQL write/state indexes
```

The implementation should not introduce an ORM-centered model. Alembic owns schema versioning; runtime stores use native SQL through `psycopg` and typed store APIs.

## PostgreSQL Schema

Initial Alembic migration creates:

- `users`
  - `id BIGSERIAL PRIMARY KEY`
  - `external_key TEXT UNIQUE`
  - `display_name TEXT`
  - `metadata JSONB`
- `conversation_sessions`
  - `id BIGSERIAL PRIMARY KEY`
  - `user_id BIGINT NOT NULL REFERENCES users(id)`
  - `title TEXT`
  - `metadata JSONB`
  - `last_consolidated INTEGER NOT NULL DEFAULT 0`
  - timestamps
- `conversation_messages`
  - `id TEXT PRIMARY KEY`
  - `user_id BIGINT NOT NULL`
  - `session_id BIGINT NOT NULL`
  - `seq INTEGER NOT NULL`
  - `role TEXT NOT NULL`
  - `content TEXT NOT NULL`
  - `extra JSONB NOT NULL DEFAULT '{}'`
  - `ts TIMESTAMPTZ NOT NULL`
  - `UNIQUE(user_id, session_id, seq)`
- `conversation_turns`
  - `id UUID PRIMARY KEY`
  - `user_id BIGINT NOT NULL`
  - `session_id BIGINT NOT NULL`
  - `content TEXT NOT NULL`
  - `status TEXT NOT NULL`
  - `answer TEXT`
  - `error TEXT`
  - `metadata_json JSONB NOT NULL DEFAULT '{}'`
  - `attempts INTEGER NOT NULL DEFAULT 0`
  - timestamps
- `memory_items`
  - current memory fields plus `user_id`, `embedding vector(<embedding_dim>)`, status/source_ref/extra_json/reinforcement/emotional_weight
- `memory_replacements`
  - replacement relation with user scope and source_ref
- `memory_markdown_writes`
  - `user_id`, `source_ref`, `kind`, `target`, `created_at`
  - `PRIMARY KEY(user_id, source_ref, kind, target)`
- `memory_markdown_state`
  - per-user/session markdown state needed for pending snapshot or recovery, if file-only snapshot semantics cannot be made crash-safe without SQLite

The migration must `CREATE EXTENSION IF NOT EXISTS vector` and fail if the extension cannot be created or detected.

## API Contracts

Minimum productized Web API:

- `POST /api/sessions`
  - input: `user_id` or `external_user_key`, optional metadata/title
  - output: `session_id`
- `GET /api/sessions?user_id=...`
  - returns only that user's sessions
- `GET /api/sessions/{session_id}/messages?user_id=...`
  - returns only that user's messages for that session
- `POST /api/messages`
  - input must include `user_id`, `session_id`, and `message`
  - creates `pending` turn and returns immediately
- existing turn status/SSE endpoints continue to work.

Full React session UI is explicitly out of scope.

## Queue And Locking

Turn claim uses PostgreSQL as a lightweight queue:

```sql
WITH candidate AS (
  SELECT id
  FROM conversation_turns AS pending
  WHERE pending.status = 'pending'
    AND NOT EXISTS (
      SELECT 1
      FROM conversation_turns AS active
      WHERE active.status = 'processing'
        AND active.user_id = pending.user_id
        AND active.session_id = pending.session_id
    )
  ORDER BY pending.created_at ASC, pending.id ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
UPDATE conversation_turns AS turn
SET status = 'processing',
    attempts = attempts + 1,
    started_at = COALESCE(started_at, now()),
    updated_at = now()
FROM candidate
WHERE turn.id = candidate.id
RETURNING turn.*;
```

Same-session concurrency follows the approved option B:

- Do not hold DB locks while waiting for LLM.
- `conversation_turns` ensures only one `processing` turn per `user_id + session_id`.
- Short database transactions may take a session advisory lock when appending messages or updating session cursors.
- Different sessions may process in parallel.

## Session And Message Flow

`PostgresSessionStore` replaces `SessionStore` and keeps the public runtime shape:

- `SessionManager.get_or_create(user_id/session_id)` loads session metadata and ordered messages.
- Messages are append-only with stable `seq`.
- Message ids should be source-ref friendly, for example `session:{user_id}:{session_id}:{seq}` or equivalent stable text id.
- `fetch_messages` and `search_messages` resolve `source_ref` through PostgreSQL messages only.

The implementation should avoid dual facts such as both `messages_json` and row-level `conversation_messages`. Row-level messages are the source of truth.

## Memory Flow

Amadeus keeps Akashic's two-layer memory design:

- Markdown layer: human-readable `MEMORY.md`, `SELF.md`, `RECENT_CONTEXT.md`, `HISTORY.md`, `PENDING.md`.
- Vector layer: PostgreSQL `memory_items` with `pgvector` retrieval and mutation lifecycle.

Migration rules:

- Keep Markdown files in workspace / Docker volume.
- Replace `consolidation_writes.db` with `memory_markdown_writes`.
- Preserve Markdown consolidation behavior: recent context refresh, history append, pending append, journal append, optimizer snapshot/commit/rollback.
- Preserve vector behavior: retrieval, source refs, correction, replacement, forget, undo.
- Do not let Markdown files become the only long-term fact source; vector memory remains queryable through `MemoryEngine` and tools.

## Configuration And Docker

Runtime config requires:

- `AMADEUS_POSTGRES_DSN`
- OpenAI provider config
- embedding model config when memory is enabled

Missing PostgreSQL DSN or missing `vector` extension is a startup error. There is no SQLite fallback.

Docker Compose should include:

- `postgres` using `pgvector/pgvector:pg16`
- `api` running FastAPI
- `worker` running turn worker
- optional migrate service or documented `alembic upgrade head` command
- persistent volumes for PostgreSQL data and Markdown workspace files

## Compatibility And Rollout

This is a destructive runtime switch. Existing SQLite data is not migrated. Old `.db` files are not read.

The migration must remove or rewrite production imports of `sqlite3`. Tests may keep local fakes only if clearly named and not used by production bootstrap.

## Akashic References

- `../akashic-agent/_handbook/memory-markdown.md`: two-layer memory contract.
- `../akashic-agent/core/memory/markdown.py`: Markdown consolidation, recent context, pending flow.
- `../akashic-agent/memory2/store.py`: vector memory lifecycle and consolidation source refs.
- `../akashic-agent/memory2/post_response_worker.py`: post-response mutation lifecycle.
- `../akashic-agent/session/store.py`: session/message seq and source refs.

PostgreSQL locking, Alembic migrations, Docker Compose, and `pgvector` usage are Amadeus-specific extensions because Akashic does not provide a PostgreSQL backend.

## Task Split

The parent task owns the shared architecture, cross-child acceptance criteria, and final integration review. This `design.md` is the only full technical design artifact for the migration unless a child task later discovers a new design decision that cannot be represented as a PRD acceptance update.

Child tasks are deliberately lightweight. Each child PRD must state its own dependencies and observable acceptance criteria; dependency order is not implied only by the tree.

Implementation should proceed through children in this order:

1. `.trellis/tasks/07-04-postgres-foundation`
   - database dependencies, config, pool, Alembic, `pgvector`, Docker postgres.
2. `.trellis/tasks/07-04-turn-session-worker`
   - users/sessions/messages/turns, minimum Web API, Worker queue, same-session serialization.
3. `.trellis/tasks/07-04-memory-postgres-pgvector`
   - long-term memory store on PostgreSQL + pgvector.
4. `.trellis/tasks/07-04-markdown-memory-postgres-state`
   - Markdown memory state/index migration to PostgreSQL while keeping file semantics.
5. `.trellis/tasks/07-04-docker-runtime-cleanup`
   - align compose/runtime config, remove SQLite production paths, update docs/specs, collate evidence for parent final integration.
