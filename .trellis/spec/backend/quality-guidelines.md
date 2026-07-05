# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

Amadeus quality is judged by interview-ready behavior: code should preserve
clear runtime boundaries, produce observable traces, and come with focused
tests or eval cases. Internal helper tests are useful, but they do not replace
public behavior proof.

Project tooling from `pyproject.toml`:

- Python `>=3.11`.
- Ruff target `py311`, line length `88`, lint families `E`, `F`, `I`, `B`, `UP`, with `E501` ignored.
- Mypy is configured in strict mode for `amadeus`, `tests`, and `dev_utils`, with relaxed overrides for tests and fixture-style modules.
- Pytest uses `tests/` as the test root and `.` on `pythonpath`.

Primary examples:

- Runtime behavior tests: `tests/runtime/test_runtime.py`, `tests/runtime/test_reasoner_tool_loop.py`.
- Memory behavior tests: `tests/memory/test_memory_retrieval_acceptance.py`, `tests/memory/test_memory_post_response_worker.py`.
- Evaluation behavior tests and cases: `tests/evaluation/test_memory_quality_runner.py`, `tests/evaluation/cases/memory_quality_v1.yaml`.
- CLI trace tests: `tests/app/test_cli.py`.

---

## Forbidden Patterns

- Do not bypass the architecture order: Passive runtime -> Memory system -> Evaluation harness -> OutboundPort / Telegram -> Scheduler -> ProactiveLoop -> DriftRunner.
- Do not make proactive code import or call Telegram directly; use an outbound boundary.
- Do not let proactive or runtime code read memory storage directly when a `MemoryEngine` or explicit context contract exists.
- Do not back resume claims with prose only. Important claims need code evidence plus runnable tests, smoke checks, or eval cases.
- Do not replace Akashic-inspired mechanisms with fake production behavior. Fakes belong in tests and deterministic eval fixtures.
- Do not let skipped evaluation infrastructure count as a passing behavioral proof.
- Do not add broad refactors while delivering a narrow vertical slice.

---

## Required Patterns

- Start from the real repository state and inspect code, tests, config, and relevant Akashic reference files before changing architecture.
- Keep behavior behind explicit boundaries: runtime phases, `Reasoner`, `ToolExecutor`, `MemoryEngine`, plugin manager, and evaluation runners.
- Preserve typed dataclasses and protocol-style contracts at module edges, such as `PassiveTurnResult`, `MemoryWriteRequest`, `MemoryMutationResult`, and `ToolTrace`.
- Prefer structured traces and artifacts over hidden side effects.
- Keep canonical eval cases under `tests/evaluation/cases/` and expose local JSON/Markdown artifacts for runs.
- Use deterministic fakes in tests for LLM, embedding, and LangSmith clients.
- Keep docs under `docs/interview/` aligned with code evidence and known gaps.

---

## Testing Requirements

- Run the narrowest meaningful tests first for touched modules.
- Broaden to integration tests when behavior crosses runtime, memory, tools, plugins, outbound, or evaluation layers.
- Add eval cases when behavior depends on LLM judgment, retrieval quality, send/skip decisions, or memory correctness.
- For memory changes, verify public behavior through recall/fetch/source_ref, active/superseded state, trace fields, and context injection.
- For CLI changes, test printed summaries and trace formatting.
- Real LLM or Telegram smoke tests are only required when configuration is available and the user expects integration verification.

---

## Code Review Checklist

- Which resume claim does this support?
- Which public behavior proves it?
- Which Akashic design contract or lifecycle does it reference?
- Which command, test, smoke, or eval case demonstrates it?
- Are lower-layer dependencies stable before higher-layer behavior is added?
- Are memory, outbound, scheduler, proactive, and eval boundaries respected?
- Are traces and reports observable enough to debug a regression?
- Are skipped, denied, or errored outcomes represented honestly instead of counted as success?
- Are unrelated dirty files left untouched?

---

## Scenario: Memory Supersede Lifecycle

### 1. Scope / Trigger

- Trigger: memory mutation APIs that create, supersede, replace, forget, or undo long-term memory rows.
- This requires code-spec depth because the flow crosses service logic, SQLite state, replacement relation records, tests, and evaluation traces.

### 2. Signatures

- `MemoryMemorizer.memorize(request: MemoryWriteRequest) -> MemoryIngestResult`
- `MemoryMemorizer.supersede_many(*, target_ids: list[str], reason: str, replacement_id: str | None = None, replacement_source_ref: str | None = None) -> MemoryMutationResult`
- `MemoryStore.mark_items_status(ids: list[str], *, status: str, extra_patch: dict[str, Any]) -> None`
- `MemoryStore.record_replacement(old_item_id: str, new_item_id: str, source_ref: str) -> None`

### 3. Contracts

- New memory content is written only through `memorize`.
- Old memory retirement is performed through `supersede_many`.
- Replacement relation records are written only when both `replacement_id` and `replacement_source_ref` are present.
- `supersede_many` must return `trace["superseded_ids"]`, `trace["replacement_id"]`, and `trace["replacement_count"]`.
- Production replacement flows must not define or call `replace_many`; use `memorize` plus `supersede_many` directly.

### 4. Validation & Error Matrix

- Empty or missing target ids -> `accepted=False`, `status="missing"`, no store mutation.
- Some missing target ids -> supersede found ids, report missing ids in `missing_ids`.
- Replacement write fails before supersede -> do not supersede old ids.
- Replacement source ref is absent -> supersede old ids but do not record replacement relation.

### 5. Good/Base/Bad Cases

- Good: post-response correction writes the new memory, then calls `supersede_many` with old ids, replacement id, and new source ref.
- Base: forget flow marks ids superseded without replacement relation.
- Bad: a worker calls `replace_many` directly and hides the write/supersede/relation lifecycle behind one verb.

### 6. Tests Required

- Unit test `supersede_many` for multiple ids, missing ids, extra patch, and replacement relation rows.
- Regression test replacement plus `undo_by_source` restores old memory and retires the replacement memory.
- Worker test for replace decision must assert written ids and superseded old ids remain visible in the public trace.
- Search check: `rg -n "replace_many" amadeus tests` should return no matches.

### 7. Wrong vs Correct

#### Wrong

```python
mutation = await memorizer.replace_many(
    target_ids=old_ids,
    request=new_request,
    reason="correction",
)
```

#### Correct

```python
result = await memorizer.memorize(new_request)
if result.item_id:
    mutation = memorizer.supersede_many(
        target_ids=old_ids,
        reason="correction",
        replacement_id=result.item_id,
        replacement_source_ref=new_request.source_ref,
    )
```

## Scenario: Memory Hotness Ranking

### 1. Scope / Trigger

- Trigger: retrieval ranking code that changes how long-term memory rows are scored, ordered, or exposed through recall/runtime traces.
- This requires code-spec depth because ranking spans SQLite row fields, ranking utilities, retriever trace records, public `recall_memory` output, and interview documentation.

### 2. Signatures

- `rank_rows(rows: list[dict[str, Any]], query_vector: list[float], query_text: str, *, limit: int, threshold: float) -> list[MemoryRecord]`
- `hotness_signal_for_row(row: dict[str, Any], *, now: datetime | None = None, half_life_days: float = 14.0) -> dict[str, float | int | str]`
- `hotness_fused_score(semantic_score: float, hotness_score: float) -> float`
- `MemoryStore._row_to_item(row: sqlite3.Row) -> dict[str, Any]`

### 3. Contracts

- Vector candidates must pass the semantic threshold before hotness is applied.
- Vector-lane ordering uses Akashic-style fusion: `0.8 * semantic_score + 0.2 * hotness_score`.
- `hotness_score` is frequency times recency:
  - frequency is bounded from `reinforcement`;
  - recency decays from `updated_at`;
  - `emotional_weight` extends the effective half-life instead of directly adding score.
- `MemoryRecord.signals` must expose `vector_score`, `final_vector_score`, `hotness_score`, `hotness_recency`, `hotness_frequency`, `hotness_age_days`, `hotness_effective_half_life_days`, `hotness_alpha`, `reinforcement`, and `emotional_weight`.
- `vector_score` means raw semantic score; do not repurpose it as the fused score.

### 4. Validation & Error Matrix

- Missing or invalid `updated_at` -> hotness recency is `0.0`; retrieval still works.
- Missing `reinforcement` -> use `1`.
- Invalid `emotional_weight` -> clamp/default into the `0..10` range.
- Semantic score below threshold -> candidate does not enter the vector lane, even when hotness would be high.

### 5. Good/Base/Bad Cases

- Good: two semantically comparable memories are ordered by fused score, with trace showing semantic, hotness, and final vector score.
- Base: a strong semantic/lexical dual-lane match still outranks a merely hot memory.
- Bad: a hot but semantically unrelated memory enters retrieval because hotness was applied before threshold filtering.

### 6. Tests Required

- Unit test that hotness changes ordering for comparable memories.
- Unit test that `emotional_weight` slows decay or increases hotness under otherwise comparable conditions.
- Unit test that a hot unrelated memory does not cross the semantic threshold.
- Public recall/tool test that trace records include hotness component fields.

### 7. Wrong vs Correct

#### Wrong

```python
final = 0.8 * semantic_score + 0.2 * hotness_score
if final >= threshold:
    vector_scored.append((item_id, final))
```

#### Correct

```python
if semantic_score >= threshold:
    final = hotness_fused_score(semantic_score, hotness_score)
    vector_scored.append((item_id, final))
```

## Scenario: Structured Session Identity

### 1. Scope / Trigger

- Trigger: any code that creates, carries, stores, sends, or parses a session identity across runtime, lifecycle, events, memory, worker, turn queue, web API, frontend, CLI, config, or tools.
- This requires code-spec depth because the identity crosses every layer and the previous design leaked string keys (`web:*`, `cli:default`, `user:1:session:1`) through runtime, stores, events, and browser state.

### 2. Signatures

- `amadeus.session.identity.SessionRef(user_id: int, session_id: int)` — the only complete internal session identity. `identity -> tuple[int, int]` is the cache-key form.
- `Session(ref: SessionRef, ...)` in `amadeus/session/store.py` — `Session` holds a `SessionRef`, never a string key.
- `SessionStoreProtocol` / `InMemorySessionStore` / `PostgresSessionStore` methods take `SessionRef` or explicit `user_id`/`session_id`, never a session key string.
- `amadeus.events.ToolCallStarted`, `ToolCallCompleted`, `TurnCommitted` carry `session: SessionRef`.
- `Turn(user_id, session_id, ...)` in `amadeus/turns/store.py` — no `session_key` field; worker rebuilds `SessionRef(turn.user_id, turn.session_id)`.
- `build_message_id(user_id: int, session_id: int, seq: int) -> str` in `amadeus/session/identity.py` — evidence locator only.
- Web schemas expose `user_id` and `session_id`; response models have no `session_key` field.

### 3. Contracts

- A bare `session_id` is NOT a complete boundary identity; the pair `(user_id, session_id)` is the identity, represented as `SessionRef`.
- Runtime, lifecycle, prompt rendering, memory, worker, event, and tool contexts pass `SessionRef` (Python boundary) or `user_id` + `session_id` (JSON/DB boundary); never a string session key.
- No production layer parses a session identity string to recover ids. The only string form allowed is `build_message_id`-shaped source refs (`session:<user_id>:<session_id>:<seq>`), consumed ONLY by fetch-by-source-ref flows as message evidence, not as session identity, cache key, or store input.
- Source refs must encode session scope BEFORE message scope, so a referenced message cannot be confused with the same seq in another session.
- PostgreSQL queries use the existing `user_id` and `session_id` columns directly; no schema migration was needed.
- CLI/config no longer expose `amadeus chat`, `--session-key`, `RuntimeConfig.default_session`, `default_session_key`, or `AMADEUS_SESSION_KEY`. Eval runners construct their own `SessionRef` values.
- Frontend localStorage and UI state store numeric `user_id` and `session_id`; the legacy `amadeus_session_key` cleanup is gone.

### 4. Validation & Error Matrix

- Code receives a bare `session_id` or a string session key at a boundary -> reject / fix the caller; do not parse it into identity.
- Worker loads a stored `Turn` -> reconstruct `SessionRef(turn.user_id, turn.session_id)` directly; no fallback string parsing.
- Source-ref string lacks session scope (e.g. legacy `chat:*` or `seed:*`) -> treat as a fixture bug, replace with session-scoped `session:<user_id>:<session_id>:<seq>`.
- Tool search/filter called with a `session_key` argument -> reject; tool schemas accept `user_id` and optional `session_id` only.

### 5. Good/Base/Bad Cases

- Good: web posts `{user_id, session_id, message}` -> `PostgresTurnStore.create_turn(user_id, session_id)` -> worker claims `Turn` -> `SessionRef(user_id, session_id)` -> `runtime.run_turn(session=SessionRef(...))` -> `SessionManager.get_or_create(SessionRef)` -> Postgres filters on `user_id/session_id` columns.
- Base: eval runner builds a generated `SessionRef` per case and drives runtime/tools directly, no CLI chat flag.
- Bad: a store method accepts a `web:*` string and parses it. Bad: events carry `session_key: str` instead of `session: SessionRef`. Bad: frontend stores `sessionKey` and posts it back. Bad: source ref `chat:<seq>` without user/session scope leaks into fingerprint or cache key.

### 6. Tests Required

- Session store unit/integration tests prove messages persist, reload, search, and fetch through `SessionRef` / structured ids.
- Runtime tests prove `PassiveTurnResult`, lifecycle events, worker turn handling, and memory write/read paths carry `SessionRef` or structured ids (see `tests/runtime/test_before_turn.py` asserting `MemoryScope.session == SessionRef(...)` and `chat_id is None`).
- Tool tests prove session filtering uses structured `user_id`/`session_id` fields.
- Web tests prove responses have no `session_key`; frontend stores/sends only `user_id`/`session_id`.
- CLI tests cover eval only and prove `amadeus chat` / `--session-key` are gone.
- Search gate: `rg -n "session_key|sessionKey|AMADEUS_SESSION_KEY|--session-key|parse_session_key|require_session_key|build_session_key|SessionRefLike|session_key_for" amadeus tests .env.example docs` returns no hits.
- Source-ref gate: `rg -n "seed:|\[\"chat:" tests amadeus` returns no legacy fixture hits.

### 7. Wrong vs Correct

#### Wrong

```python
event = ToolCallStarted(session_key=f"web:{user_id}:{session_id}", ...)
store.get(session_key=request.session_key)
turn = Turn(session_key=f"user:{user_id}:session:{session_id}", ...)
# frontend
localStorage.setItem("amadeus_session_key", key)
```

#### Correct

```python
event = ToolCallStarted(session=SessionRef(user_id, session_id), ...)
store.get(SessionRef(user_id, session_id))
turn = Turn(user_id=user_id, session_id=session_id, ...)
# frontend
localStorage.setItem("amadeus_user_id", String(user_id))
localStorage.setItem("amadeus_session_id", String(session_id))
```

> **Gotcha — source refs are not identity.** `session:<user_id>:<session_id>:<seq>` strings look like session identity but are evidence/message locators. They may be parsed ONLY by fetch-by-source-ref code. Runtime, store, cache, event, tool-filter, and API identity must use `SessionRef` / `user_id`+`session_id`, never the source-ref string.

---

## Reference Branch Notes

- This task intentionally diverges from Akashic's `session_key` mechanism. Akashic uses string session keys across bus/lifecycle/passive/turn/tests; Amadeus expresses the same "explicit identity at lifecycle/memory boundary" idea through `SessionRef` / `user_id + session_id`. Akashic is treated as a cautionary map of where identity leaks, not a model to copy.
- Closer structural reference: `redrumY/telegram-bot@codex/web-agent-architecture` for structured web/turn contracts around `user_id`/`session_id`. Note its `MemoryScope.session_key` field is NOT copied — Amadeus keeps memory scope structured.

## Scenario: Dual-Hypothesis Memory Retrieval

### 1. Scope / Trigger

- Trigger: changes to long-term memory retrieval, hypothesis generation, `recall_memory`, passive context injection, or memory retrieval trace fields.
- This requires code-spec depth because the behavior spans `MemoryRetriever`, `rank_rows`, LLM hypothesis providers, runtime/bootstrap config, tool-facing traces, and interview documentation.

### 2. Signatures

- `MemoryRetriever.recall(request: MemoryRecallRequest) -> MemoryQueryResult`
- `HypothesisProvider.generate(query: str, *, style: str) -> str`
- `rank_rows(rows: list[dict[str, Any]], query_vector: list[float], query_text: str, *, limit: int, threshold: float, lexical_enabled: bool = True) -> list[MemoryRecord]`
- `rank_multi_query_rows(rows: list[dict[str, Any]], query_vectors: list[list[float]], query_texts: list[str], *, limit: int, threshold: float) -> tuple[list[MemoryRecord], dict[str, dict[str, int]]]`
- `load_runtime_config(...) -> RuntimeConfig`

### 3. Contracts

- Explicit `intent="answer"` / `recall_memory` retrieval may generate exactly two memory-shaped auxiliary query styles: `event` and `general`.
- Passive `intent="context"` retrieval must remain raw-query-only and must not spend an LLM call on hypothesis generation.
- Raw query always participates.
- Generated hypothesis queries participate in vector retrieval only; lexical matching must remain raw-query-only.
- Multiple vector queries that hit the same memory id must keep the best vector hit for that id, not accumulate one RRF contribution per query.
- Final RRF fusion is between the deduplicated vector pool and the raw-query lexical pool.
- Hypothesis generation is default-on when long-term memory has a provider, with `AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED=0` as the kill switch.
- Hypothesis text belongs in structured trace, not in rendered retrieved-memory/context-frame text.

### 4. Validation & Error Matrix

- One hypothesis style fails -> keep the successful style and record a style-specific fallback/error.
- Both hypothesis styles fail or time out -> fall back to raw-only retrieval.
- Empty hypothesis output -> omit that generated query and record an empty-output fallback.
- Missing hypothesis provider or disabled config -> raw-only retrieval with a disabled reason in trace.

### 5. Good/Base/Bad Cases

- Good: raw query misses a relevant memory, event/general vector lanes recall it, and trace records matched query indexes.
- Base: passive context retrieval runs once with raw query and no hypothesis provider calls.
- Bad: a generated hypothesis creates a lexical-only hit because its literal words overlap a memory summary.
- Bad: the same memory receives separate RRF contributions for raw, event, and general vector matches.

### 6. Tests Required

- Retriever test proving event/general hypotheses can recall a candidate raw wording misses.
- Retriever test proving passive context does not call the hypothesis provider.
- Retriever test proving generated hypotheses do not create lexical hits.
- Ranking test proving repeated vector-query hits keep the best vector hit instead of accumulating per-query RRF.
- Retriever tests proving exception and timeout paths fall back to raw retrieval and record trace fallbacks/errors.
- Bootstrap/config test proving default-on behavior, timeout, optional light model, and kill switch.

### 7. Wrong vs Correct

#### Wrong

```python
queries = [raw_query, event_hypothesis, general_hypothesis]
result_sets = [
    rank_rows(rows, query_vector, query, limit=top_k, threshold=threshold)
    for query in queries
]
ranked = rrf_fuse_records(result_sets, limit=top_k)
```

#### Correct

```python
queries = [raw_query, event_hypothesis, general_hypothesis]
query_vectors = await asyncio.gather(*(embed(query) for query in queries))
ranked, lane_counts = rank_multi_query_rows(
    rows,
    query_vectors,
    queries,
    limit=top_k,
    threshold=threshold,
)
```
