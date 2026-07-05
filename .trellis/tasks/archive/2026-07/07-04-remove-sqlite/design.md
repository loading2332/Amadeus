# Design

## Problem Restatement

Amadeus already runs production state on PostgreSQL, but SQLite-era stores and
fallbacks still exist in code and tests. That leaves two storage models in the
repository, weakens contracts, and keeps runtime modules coded against legacy
compatibility instead of the real production shape.

## Architecture Boundaries

- `PassiveApp` remains the production composition root and must stay
  PostgreSQL-only.
- `SessionManager` remains the in-memory/session-history coordinator, but it
  should no longer construct a local SQLite store by default.
- `PostgresSessionStore`, `PostgresTurnStore`, and `PostgresMemoryStore` become
  the only persistent state implementations in-tree for these domains.
- Tool-facing helpers such as `fetch_messages` and `search_messages` should be
  retained if still useful, but they must depend on PostgreSQL-era store
  contracts rather than a SQLite class name.

## Data Flow And Contracts

### Session

- Keep `Session` and `SessionManager` as runtime-layer types.
- Remove `SessionStore`.
- Introduce or reuse a store protocol/typed contract that matches the methods
  `SessionManager`, `FetchMessagesTool`, and `SearchMessagesTool` actually need.
- `SessionManager` must require an injected PostgreSQL-capable store instead of
  defaulting to `sessions.db`.

### Turns

- Keep `Turn` and shared status constants.
- Remove `TurnStore`.
- Make web/SSE/dependency typing target `PostgresTurnStore` or a small queue
  protocol owned by the PostgreSQL implementation path.
- Remove legacy test-only app construction that injects SQLite turns.

### Memory

- Remove `MemoryStore`.
- Move any still-needed shared helpers, such as content-hash/date normalization,
  out of the SQLite store module into a Postgres-neutral helper module.
- Tighten `MemoryRetriever` to depend on the Postgres-era retrieval contract
  directly instead of carrying fallback logic for stores without
  `search_active_items`.
- Update tests and fakes to satisfy the tighter retrieval/store contract.

## Test Strategy

- Delete tests whose only purpose is validating SQLite implementations.
- Preserve public behavior coverage by porting the important cases to
  PostgreSQL-backed fixtures:
  session/message fetch and search, turn queue transitions, web API turn
  lifecycle, memory memorize/recall/undo/post-response behavior.
- Continue using `tests/db/postgres_helpers.py` as the primary fixture root for
  touched integration-style tests.

## Compatibility Notes

- No runtime compatibility with old local SQLite files is preserved.
- No public Python export compatibility is guaranteed for removed SQLite store
  classes.
- `MemoryEngine.run_post_response(...)`, CLI canonical session-key parsing, and
  the web message request shape are explicit breaking-surface changes in this
  task and should be communicated as such.
- Any code still importing `SessionStore`, `TurnStore`, or `MemoryStore` should
  be updated in the same change or removed.

## Tradeoffs

- Removing fallback paths simplifies the architecture and aligns code with the
  actual production runtime.
- Tests become more integration-heavy and more dependent on PostgreSQL
  availability.
- This is an intentional trade: one real storage model with stronger contracts
  is more valuable here than keeping cheap local SQLite unit fixtures.
