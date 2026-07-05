# Remove legacy session key strings

## Goal

Remove `session_key` as a runtime identity and compatibility path. Amadeus should use structured session identity everywhere inside API, runtime, stores, events, tools, tests, and frontend state: `SessionRef(user_id, session_id)` in Python boundaries and `user_id` plus `session_id` in JSON/browser boundaries.

## User Value

This supports the passive runtime and memory architecture by making session identity explicit, typed, and auditable. It removes the risk that old arbitrary string keys such as `web:*`, `cli:default`, or `user:1:session:1` compatibility parsing keep leaking across runtime and storage layers.

## Confirmed Facts

- Current canonical identity type exists as `SessionRef(user_id: int, session_id: int)` in `amadeus/session/identity.py`, but it still exposes `session_key`, `SessionRefLike`, `parse_session_key`, `require_session_key`, `build_session_key`, and `session_key_for`.
- Current config still accepts `AMADEUS_SESSION_KEY` and parses it in `amadeus/app/bootstrap.py`.
- Current CLI still exposes `--session-key` in `amadeus/app/cli.py`.
- Current `SessionStoreProtocol`, `InMemorySessionStore`, and `PostgresSessionStore` accept and return `session_key` strings in core store methods.
- Current events in `amadeus/events.py` carry `session_key: str`.
- Current `Turn` in `amadeus/turns/store.py` includes `session_key: str` even though PostgreSQL turns already store `user_id` and `session_id`.
- Current web schemas return `session_key` in `SessionResponse`, `MessageResponse`, and `TurnResponse`.
- Current frontend still stores and renders `sessionKey` even though message creation now posts `user_id` and `session_id`.
- Reference branch `redrumY/telegram-bot@codex/web-agent-architecture` uses structured web requests and turn persistence around `user_id` and `session_id`, and its web response does not include `session_key`.
- Reference branch `redrumY/telegram-bot@codex/web-agent-architecture` still keeps source-reference strings such as `session:<user_id>:<chat_id>` and `session:<user_id>:<chat_id>#msg:<seq>` for memory evidence and message fetch. Its source refs are parsed only by `memory/engine.py` message-fetch code, while web/API/turn identity remains structured.
- Reference branch `redrumY/telegram-bot@codex/web-agent-architecture` has one leftover `MemoryScope.session_key` field in `memory/engine.py` populated from context, so it is not a perfect no-string model. Its stronger pattern is the web/turn/session-store side, not the memory scope field.

## Requirements

### R1. Runtime identity is structured only

- `SessionRef` remains the Python session identity with integer `user_id` and `session_id`.
- `session_id` alone is not a complete identity at Amadeus boundaries. The complete identity is the pair `(user_id, session_id)`, represented as `SessionRef`.
- Runtime, lifecycle, prompt rendering, memory, worker, event, and tool contexts must pass `SessionRef`, not session key strings.
- No production code should accept arbitrary session identity strings and parse them into a session.

### R2. Store contracts do not take session key strings

- `Session`, `SessionManager`, `SessionStoreProtocol`, `InMemorySessionStore`, and `PostgresSessionStore` must use `SessionRef` or explicit `user_id/session_id` parameters.
- Store row dictionaries may include `user_id` and `session_id`, but must not include `session_key`.
- PostgreSQL queries should continue using `user_id` and `session_id` columns directly.

### R3. API and browser contracts are structured

- Web request and response schemas must use `user_id` and `session_id`, not `session_key`.
- Frontend localStorage and UI state must store numeric `user_id` and `session_id`, not session key strings.
- Any previous compatibility cleanup for `amadeus_session_key` should be removed once the browser no longer understands session key storage.

### R4. CLI and config no longer expose chat session keys

- Remove the `amadeus chat` command because the frontend now owns manual chat/smoke usage.
- Keep evaluation CLI commands such as `amadeus eval memory-recall` and `amadeus eval memory-quality`.
- Remove `RuntimeConfig.default_session`, `default_session_key`, and `AMADEUS_SESSION_KEY`; all runtime callers must pass an explicit `SessionRef` derived from their own structured source.
- LangSmith evaluation must continue to use generated `SessionRef` values inside evaluation runners, not chat CLI flags.

### R5. Events and tool APIs are structured

- Event dataclasses must carry `session: SessionRef` or `user_id/session_id`, not `session_key`.
- Read-only message search/fetch tools must filter by structured session fields, not a `session_key` tool argument.
- Tool schemas, tests, and traces must be updated to match the structured contract.

### R6. No legacy compatibility remains

- Remove string parsing helpers and tests for noncanonical session keys.
- Remove references to `session_key`, `sessionKey`, `AMADEUS_SESSION_KEY`, and `--session-key` from production code.
- Source-reference strings must include session scope before message scope because message evidence is only meaningful inside a session. They may keep a session-scoped shape only when they identify one message or a message range inside that session. They must not be accepted as session identity, used as cache keys, or parsed by runtime/store/API code outside fetch-by-source-ref behavior.
- Existing dirty unrelated deletes in the worktree must remain untouched.

## Acceptance Criteria

- [ ] `rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|--session-key|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for" amadeus tests .env.example docs` returns no hits.
- [ ] `rg -n "source_ref|source_refs|session:" amadeus tests` returns only evidence/message locator usage where the source ref includes session scope plus message scope, not session identity usage.
- [ ] Web static code stores and sends only `user_id` and `session_id`.
- [ ] Web API responses no longer include `session_key`.
- [ ] CLI no longer exposes `amadeus chat`, `--session-key`, or chat trace session output, while eval CLI tests still pass.
- [ ] Session store unit/integration tests prove messages persist, reload, search, and fetch through structured session identity.
- [ ] Runtime tests prove `PassiveTurnResult`, lifecycle events, worker turn handling, and memory write/read paths carry `SessionRef` or structured ids.
- [ ] Tool tests prove session filtering uses structured fields.
- [ ] Focused tests pass: `uv run pytest tests/session tests/runtime tests/memory tests/tools tests/app tests/web tests/worker tests/turns`.
- [ ] `uv run ruff check amadeus tests` passes.

## Akashic / Reference Notes

- Akashic source uses `session_key` heavily across bus, lifecycle, passive/proactive turns, session store, and tests. This task intentionally does not copy that identity mechanism because the user explicitly wants no session-key string compatibility in Amadeus.
- Akashic-inspired boundary to keep: session identity must be explicit at lifecycle/memory boundaries and observable enough for traces. Amadeus will express that boundary through `SessionRef` / `user_id + session_id`, not through `session_key`.
- External reference: `redrumY/telegram-bot@codex/web-agent-architecture` demonstrates structured web and turn contracts around `user_id/session_id`, especially `web_backend/api.py`, `web_backend/static/app.js`, and `persistence/postgres_turn_store.py`.

## Out Of Scope

- Database schema changes are out of scope unless tests prove a schema-level session key column exists. Current PostgreSQL foundation already stores `user_id` and `session_id`.
- Telegram outbound, scheduler, proactive loop, and Drift runner behavior are out of scope.
- Historical documentation deletions already present in the worktree are out of scope.

## Decisions

- Follow the reference branch split, but make it stricter: remove session-key strings from identity/runtime/API/store contracts; keep source-reference strings only for memory evidence and fetch-by-source-ref message lookup.
- Source refs should be session-scoped first, then message-scoped, because a message locator without session scope can mix evidence across sessions.
- Remove chat CLI rather than replacing `--session-key` with structured chat flags. Keep eval CLI because LangSmith runners call evaluation code directly and do not depend on chat CLI session handling.
- Remove `RuntimeConfig.default_session` because frontend, worker, eval, and future scheduler/proactive entry points should all provide explicit structured session identity.
- Keep the field name `session_id`, not `chat_id`, but treat it as scoped by `user_id`. Telegram `chat_id` should map into an Amadeus `SessionRef` at the adapter boundary rather than becoming the internal identity field.
