# Design: Structured Session Identity Only

## Architecture

Session identity has one owner: `amadeus.session.identity.SessionRef`. It should be a structured value object with `user_id: int` and `session_id: int`. Runtime code passes `SessionRef`; JSON boundaries pass `user_id` and `session_id`; database code persists the two columns directly. A bare `session_id` is not a complete boundary identity; the pair `(user_id, session_id)` is the identity.

This intentionally diverges from Akashic's string `session_key` mechanism while preserving the lifecycle boundary idea. Akashic's implementation is useful as a cautionary source for where identity leaks can spread; RedrumY's web/turn branch is the closer structural reference for this task.

The target shape is:

```text
CLI/env/web JSON
  -> user_id + session_id
  -> SessionRef
  -> runtime/events/memory/tools/session manager
  -> Postgres user_id/session_id columns
```

No layer should parse a session identity string to recover IDs.

## Contract Changes

- `amadeus.session.identity`
  - Keep `SessionRef`.
  - Treat `SessionRef(user_id, session_id)` as the only complete internal identity.
  - Remove `session_key`, `__str__`, `SessionRefLike`, parse/build/require string helpers.
  - Add small explicit helpers only if they preserve structure, such as `ensure_session_ref(user_id, session_id)`.

- `amadeus.session.store`
  - Change `Session.key: str` to `Session.ref: SessionRef`.
  - Cache by tuple `(user_id, session_id)` or by `SessionRef`, not string.
  - `SessionStoreProtocol` methods receive `SessionRef` or explicit IDs.
  - Message rows include `user_id`, `session_id`, `seq`, `id`, role/content/timestamp; no `session_key`.

- `amadeus.session.postgres`
  - Public methods accept `SessionRef` or explicit IDs.
  - `_session_row`, `_session_meta_from_row`, and `_message_row` stop returning `session_key`.
  - Message IDs can continue to be stable source ids if planning allows source-reference strings.

- `amadeus.turns`
  - `Turn` removes `session_key`.
  - `PostgresTurnStore._row_to_turn` returns `user_id` and `session_id` only.
  - Worker reconstructs `SessionRef` directly from turn fields without fallback parsing.

- `amadeus.events`
  - `ToolCallStarted`, `ToolCallCompleted`, and `TurnCommitted` carry `session: SessionRef`.

- `amadeus.web`
  - Requests and responses expose `user_id` and `session_id`; response models remove `session_key`.
  - Frontend removes `sessionKey` state and legacy storage cleanup.

- `amadeus.app`
  - Remove the chat subcommand and chat trace formatting.
  - Keep eval subcommands that call memory evaluation runners.
  - Remove default chat session config (`RuntimeConfig.default_session`, `default_session_key`, and `AMADEUS_SESSION_KEY`).
  - `PassiveApp` composition should not own a default session; entry points must provide session identity explicitly.

- `amadeus.tools`
  - Tool schemas replace `session_key` arguments with `user_id` and optional `session_id`.
  - Store search filters accept structured session filters.

- Source references
  - Keep source-reference strings as evidence/message locators.
  - Source refs should encode session scope before message scope so a referenced message cannot be confused with the same sequence number in another session.
  - Fetch-by-source-ref may parse source refs to locate historical messages.
  - Runtime identity, session manager cache keys, store APIs, web APIs, events, CLI/config, and tool filters must not accept source refs as session identity.

## Data Flow

Web chat:

```text
browser localStorage user_id/session_id
  -> POST /api/messages { user_id, session_id, message }
  -> PostgresTurnStore.create_turn(user_id, session_id)
  -> worker claims Turn(user_id, session_id)
  -> SessionRef(user_id, session_id)
  -> runtime.run_turn(session=SessionRef(...))
  -> SessionManager.get_or_create(SessionRef)
  -> PostgresSessionStore queries user_id/session_id
```

Evaluation:

```text
amadeus eval memory-recall / memory-quality
  -> evaluation runner
  -> generated SessionRef per case
  -> PassiveApp/runtime/tool execution
```

Tool search:

```text
tool args { query, user_id?, session_id? }
  -> structured store filter
  -> rows with source_ref and user/session metadata
```

## Compatibility and Migration

This is intentionally breaking. Old `AMADEUS_SESSION_KEY`, `--session-key`, `amadeus chat`, web `amadeus_session_key` localStorage, and `session_key` JSON fields should stop working instead of silently migrating.

Existing PostgreSQL data remains usable because the schema stores `user_id` and `session_id` already. Only runtime contracts and tests need migration.

## Rollback

Rollback is file-level through git. Avoid database migrations unless a test proves they are necessary.

## Risks

- Some memory/source-ref flows use string IDs containing the word `session`; those are allowed only as evidence identifiers with message-level scope and must stay outside identity contracts.
- Broad test churn is expected because `session_key` appears in many tests.
- The frontend currently has recent uncommitted changes from the previous cleanup; preserve intent while replacing it with fully structured state.
