# Implementation Plan

## Ordered Checklist

- [ ] Refactor session-layer shared types/helpers away from SQLite-specific
      storage classes.
- [ ] Remove `SessionStore` and the `SessionManager` default SQLite fallback.
- [ ] Remove `TurnStore` and update turn/web/SSE/dependency typing to the
      PostgreSQL-only queue contract.
- [ ] Remove `MemoryStore`, extract any shared helper functions that
      `PostgresMemoryStore` still needs, and tighten memory retriever/store
      contracts to PostgreSQL-only behavior.
- [ ] Update package exports in `amadeus/session/__init__.py`,
      `amadeus/turns/__init__.py`, `amadeus/memory/__init__.py`, and
      `amadeus/__init__.py`.
- [ ] Replace or delete SQLite-only tests and port required public behavior
      coverage to PostgreSQL-backed fixtures.
- [ ] Run focused lint/type/test checks for touched modules.

## Validation Commands

- `uv run pytest -q tests/session/test_postgres_session_store.py tests/turns/test_postgres_turn_store.py tests/web/test_postgres_web_app.py tests/worker/test_turn_worker.py`
- `uv run pytest -q tests/memory/test_postgres_memory_store.py tests/memory/test_memory_memorizer.py tests/memory/test_memory_retriever.py tests/memory/test_memory_post_response_worker.py tests/memory/test_memory_retrieval_acceptance.py tests/tools/test_memorize_tool.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_forget_memory_tool.py`
- `uv run ruff check amadeus tests`

## Risky Files

- `amadeus/session/store.py`
- `amadeus/session/postgres.py`
- `amadeus/turns/store.py`
- `amadeus/turns/postgres.py`
- `amadeus/memory/store.py`
- `amadeus/memory/postgres.py`
- `amadeus/memory/retriever.py`
- `amadeus/web/app.py`
- `amadeus/tools/defaults.py`

## Rollback Points

- After session-layer cleanup.
- After turn/web cleanup.
- After memory contract cleanup.
- After test migration.

## Planning Gate Before `task.py start`

- Confirm the intended test preservation level for old SQLite-only tests.
- Review the artifact set (`prd.md`, `design.md`, `implement.md`) and approve
  implementation against the PostgreSQL-only scope.
