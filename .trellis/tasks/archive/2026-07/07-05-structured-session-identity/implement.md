# Implementation Plan: Structured Session Identity Only

## Order

1. Add or simplify identity helpers around `SessionRef`.
   - Remove string compatibility helpers.
   - Update direct identity tests first.

2. Refactor session stores.
   - Change `Session` to hold `SessionRef`.
   - Update `SessionStoreProtocol`, `InMemorySessionStore`, `SessionManager`, and `PostgresSessionStore`.
   - Remove `session_key` fields from row payloads.
   - Update session tests.

3. Refactor runtime and lifecycle contracts.
   - Remove `session_key` properties from runtime/lifecycle result/context classes where they are identity aliases.
   - Update events to carry `SessionRef`.
   - Update reasoner/tool-call event emission.

4. Refactor turn and worker contracts.
   - Remove `Turn.session_key`.
   - Update worker to construct `SessionRef(turn.user_id, turn.session_id)` directly.
   - Update turn and worker tests.

5. Refactor web API and frontend.
   - Remove `session_key` from schemas and responses.
   - Frontend stores/renders numeric user/session IDs only.
   - Update web tests and static contract assertions.

6. Refactor CLI/config.
   - Remove the `chat` subcommand, `_run_chat`, and chat trace formatting.
   - Keep eval subcommands and report printing.
   - Remove `AMADEUS_SESSION_KEY`, `RuntimeConfig.default_session`, and `default_session_key`.
   - Update CLI tests to cover eval only and prove chat/session-key flags are gone.

7. Refactor tools and memory search filters.
   - Replace `session_key` tool schema args with structured filters.
   - Update memory/tool tests.

8. Run global search and remove leftover naming.
   - `rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|--session-key|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for" amadeus tests .env.example docs`
   - Resolve every production hit according to PRD scope.

9. Audit allowed source-reference strings.
   - `rg -n "source_ref|source_refs|session:" amadeus tests`
   - Keep only evidence/message locator strings that include session scope before message scope.
   - Confirm no source ref is accepted by API/store/runtime/tool filters as a session identity.

## Validation Commands

Run narrow first:

```powershell
uv run pytest tests/session tests/turns tests/worker
uv run pytest tests/runtime tests/memory tests/tools
uv run pytest tests/app tests/web
```

Then broader:

```powershell
uv run pytest tests/session tests/runtime tests/memory tests/tools tests/app tests/web tests/worker tests/turns
uv run ruff check amadeus tests
```

Search gate:

```powershell
rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|--session-key|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for" amadeus tests .env.example docs
rg -n "source_ref|source_refs|session:" amadeus tests
```

## Risky Files

- `amadeus/session/store.py`
- `amadeus/session/postgres.py`
- `amadeus/session/identity.py`
- `amadeus/runtime/passive.py`
- `amadeus/runtime/lifecycle.py`
- `amadeus/events.py`
- `amadeus/turns/store.py`
- `amadeus/turns/postgres.py`
- `amadeus/worker/turn_worker.py`
- `amadeus/app/bootstrap.py`
- `amadeus/app/cli.py`
- `amadeus/web/schemas.py`
- `amadeus/web/static/app.js`
- `amadeus/tools/defaults.py`

## Review Gates Before Start

- Review PRD/design/implement with the user.
- Run `task.py start` only after approval to implement.

## Implemented

- `SessionRef(user_id, session_id)` is now the only internal session identity.
- Removed string identity helpers and compatibility paths from session identity, config, runtime, events, turn queue, worker, web schemas, frontend state, and tool search filters.
- Removed `amadeus chat` and its trace formatter; CLI now keeps eval commands only.
- Store/search/tool filters now use `user_id` and `session_id`.
- Source refs remain string evidence locators, scoped as `session:<user_id>:<session_id>:<seq>`, and are only consumed by fetch-by-source-ref flows.
- `.env.example` no longer advertises a session identity env var.

## Verification Run

```powershell
uv run pytest tests/session/test_postgres_session_store.py tests/tools/test_readonly_tools.py tests/memory/test_session_memory_runtime.py tests/app/test_cli.py tests/web/test_postgres_web_app.py
uv run pytest tests/app/test_bootstrap.py tests/runtime/test_runtime.py tests/worker tests/turns tests/tools/test_memorize_tool.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_memory_retrieval_acceptance.py
uv run ruff check amadeus tests
node --check amadeus\web\static\app.js
rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|default_session|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for|--session-key|amadeus chat" amadeus tests .env.example docs
```

Results:

- 22 focused tests passed.
- 64 broader affected tests passed.
- Ruff passed.
- Frontend syntax check passed.
- Search gate returned no matches.

## Trellis Check Follow-up

Additional check pass found and fixed:

- `tests/runtime/test_before_turn.py` still expected memory context scope to receive a string chat id. It now asserts `MemoryScope.session == SessionRef(...)` and `chat_id is None` for runtime session recall.
- Legacy `chat:*` source-ref fixtures were replaced with session-scoped message ids.
- Evaluation seed source refs were changed from `seed:*` to session-scoped message ids.
- `_print_eval_report` now has a concrete evaluation-report union type instead of `object`.

Additional verification:

```powershell
uv run pytest tests/session tests/runtime tests/memory tests/tools tests/app tests/web tests/worker tests/turns tests/evaluation --ignore=tests/app/test_debug_context_llm.py --ignore=tests/app/test_openai_provider.py
uv run ruff check amadeus tests
node --check amadeus\web\static\app.js
rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|default_session|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for|--session-key|amadeus chat" amadeus tests .env.example docs
rg -n "seed:|\\[\\\"chat:" tests amadeus
```

Results:

- 246 tests passed with the two existing `dev_utils`-dependent app tests ignored.
- Ruff passed.
- Frontend syntax check passed.
- Session-key legacy search returned no matches.
- Non-session legacy source-ref fixture search returned no matches.

Known pre-existing check gaps:

- Full pytest collection still fails on `tests/app/test_debug_context_llm.py` and `tests/app/test_openai_provider.py` because `dev_utils` is not importable in this environment.
- Full mypy still fails in existing evaluation/dev_utils areas; the session-identity check removed the new CLI report typing error from that list.
