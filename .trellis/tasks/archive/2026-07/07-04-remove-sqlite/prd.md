# Remove SQLite code

## Goal

Remove SQLite from Amadeus code paths completely. After this task, the runtime,
memory, web, and test layers should all target PostgreSQL only, with no
SQLite-backed stores, no fallback constructors, and no legacy compatibility
branches kept for old local databases.

## Confirmed Facts

- Production bootstrap already composes PostgreSQL-native stores for sessions,
  turns, and long-term memory in [amadeus/app/bootstrap.py](../../../../amadeus/app/bootstrap.py).
- The web app and worker already use PostgreSQL in the default production path
  through [amadeus/web/app.py](../../../../amadeus/web/app.py) and
  [amadeus/worker/turn_worker.py](../../../../amadeus/worker/turn_worker.py).
- SQLite implementations still exist in
  [amadeus/session/store.py](../../../../amadeus/session/store.py),
  [amadeus/turns/store.py](../../../../amadeus/turns/store.py), and
  [amadeus/memory/store.py](../../../../amadeus/memory/store.py).
- Several runtime and tool modules still import contracts from the SQLite-era
  modules, even when the concrete production implementation is PostgreSQL.
- A large set of tests still instantiate `SessionStore`, `TurnStore`, or
  `MemoryStore`, so SQLite remains part of the executable test surface.
- The user explicitly wants no legacy compatibility: remove SQLite code instead
  of preserving fallback behavior or old fixtures.

## Requirements

- Remove SQLite-backed store implementations from `amadeus/session`,
  `amadeus/turns`, and `amadeus/memory`.
- Remove runtime fallback paths that create or depend on `sessions.db`,
  `turns.db`, or `long_term_memory.db`.
- Remove public exports and type unions that keep SQLite-era store types part
  of the supported API surface.
- Keep the current PostgreSQL production runtime working for passive runtime,
  web API, worker queue, long-term memory, markdown memory state, tools, and
  plugin composition.
- Tighten contracts where appropriate so runtime code depends on PostgreSQL-era
  interfaces instead of "maybe SQLite, maybe Postgres" abstractions.
- Update tests so code-level verification no longer depends on SQLite fixtures
  or legacy store classes.
- Preserve public-behavior coverage, delete SQLite implementation-detail
  tests, and port only important behavior cases to PostgreSQL-backed tests.

## Out Of Scope

- Documentation cleanup.
- Queue concurrency improvements beyond whatever minimal changes are required by
  SQLite removal itself.
- MCP, tool-registry expansion, frontend, or broader productization work.

## Breaking Surface

The cleanup intentionally tightens several public or semi-public contracts.
These are not accidental regressions; callers must update to the PostgreSQL and
structured-session shape.

- `MemoryEngine.run_post_response(...)` now takes `session: SessionRef` instead
  of `session_key: str`.
- The web `MessageRequest` contract is structured around `user_id` and
  `session_id`; old string-only session-key request payloads are not preserved.
- CLI `--session-key` now requires canonical `user:{user_id}:session:{session_id}`
  shape and is parsed into `SessionRef` before entering runtime.

## Open Questions

- None.

## Acceptance Criteria

- [ ] No `sqlite3` imports remain under `amadeus/`.
- [ ] No SQLite-backed store classes remain under `amadeus/session`,
      `amadeus/turns`, or `amadeus/memory`.
- [ ] Runtime/bootstrap/web code no longer falls back to local SQLite files such
      as `sessions.db`, `turns.db`, or `long_term_memory.db`.
- [ ] Public exports no longer expose `SessionStore`, `TurnStore`, or
      `MemoryStore`.
- [ ] Memory retrieval/runtime code no longer contains SQLite-specific fallback
      branches for store capabilities.
- [ ] Focused tests pass using PostgreSQL-backed fixtures for the touched
      runtime, memory, web, tool, and worker behavior.
