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

## 场景：独立双 lane 长期记忆检索

### 1. 范围 / 触发

- 触发：修改长期记忆候选生成、hypothesis 生成、RRF 排序、`recall_memory`、被动 context injection 或 retrieval trace/eval 字段。
- 该行为跨越 PostgreSQL、`MemoryRetriever`、lane-aware ranking、runtime/bootstrap config、tool trace、canonical eval 与面试声明，因此必须维护代码级规格。

### 2. 签名

- `MemoryRetriever.recall(request: MemoryRecallRequest) -> MemoryQueryResult`
- `HypothesisProvider.generate(query: str, *, style: str) -> str`
- `MemoryRetrievalStoreProtocol.search_vector_candidates(..., limit: int) -> list[dict[str, Any]]`
- `MemoryRetrievalStoreProtocol.search_lexical_candidates(*, terms: tuple[str, ...], ..., limit: int) -> list[dict[str, Any]]`
- `MemoryRetrievalParameters.vector_candidate_limit(request_limit: int) -> int`
- `MemoryRetrievalParameters.lexical_candidate_limit(request_limit: int) -> int`
- `rank_candidate_lanes(candidates: MemoryCandidateLanes, query_vectors: list[list[float]], query_texts: list[str], *, limit: int, threshold: float, lexical_weight: float = 1.0, rrf_k: int = 60, hotness_alpha: float = 0.2, hotness_half_life_days: float = 14.0, reinforcement_strength: float = 1.0, emotional_half_life_scale: float = 0.5, ranking_now: datetime | None = None) -> tuple[list[MemoryRecord], RetrievalLaneTrace]`
- `load_runtime_config(...) -> RuntimeConfig`

### 3. 契约

- Vector 与 lexical 必须分别从完整 eligible corpus 生成候选。在 pgvector shortlist 上补算 substring 分数不构成 lexical retrieval lane。
- 显式 `intent="answer"` / `recall_memory` 最多生成两种 memory-shaped 辅助 query：`event` 与 `general`。
- 被动 `intent="context"` 不调用 hypothesis provider；raw query 始终参与 vector retrieval，显式 context queries 只能追加，不能替换 raw query。
- 生成的 hypothesis 只参与 vector retrieval；lexical 永远只由 `MemoryRecallRequest.text` 驱动。
- Lexical extraction 对齐 Akashic：先提取全部 ASCII `[A-Za-z0-9_.-]{2,}`，再处理汉字、平假名、片假名；2～4 字 chunk 保留完整，长 chunk 拆相邻 bigram；应用 CJK stopwords，最后对“ASCII terms + CJK terms”拼接序列稳定去重并限制为 20 个。
- 多个 vector query 命中同一 memory id 时，只保留最佳 vector hit，不得按 query 累加多份 RRF contribution。
- `MemoryCandidateLanes` 保留原始 vector groups 与 lexical rows。lane membership、rank 与 contribution 不得从 union 上重新打分推断。
- Vector candidate 必须先通过 semantic threshold，再做 hotness fusion；整次排序共享同一个时间快照。Lexical candidate 使用 store 返回的 coverage score，不要求 embedding。
- 最终 RRF 按稳定 id 去重，`k=60`，lexical weight `1.0` 是首轮 deterministic eval 基线，最终参数由 eval 决定。权重为 0 时不得返回零分 lexical-only 结果。
- candidate window、RRF、threshold 与 hotness 的生产/实验真值由不可变 `MemoryRetrievalParameters` 持有；旧 constructor 字段只能在构造时转换成 profile override，排序过程不得继续读取第二份常量。
- `candidate_counts.vector/lexical` 表示 SQL 返回的 raw unique candidates；`lane_counts` 表示通过 threshold/score 校验后真正贡献排名的候选；兼容字段 `candidate_count` 表示 union count。
- public trace 额外记录 profile、fingerprint、effective candidate limits 和每条 vector query 的 raw count；完整 candidate ids 不进入生产 trace，只能通过默认关闭的 `RetrievalCandidateSnapshot` observer 提供给本地实验 runner。
- Record signals 暴露 1-based `vector_rank` / `lexical_rank` 与两路 RRF contribution；context injection 保留最终融合顺序。
- Long-term memory 配置 provider 后 hypothesis 默认开启，`AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED=0` 是 kill switch。
- Lexical retrieval 默认开启，`AMADEUS_MEMORY_LEXICAL_RETRIEVAL_ENABLED=0` 是 query-level rollback switch。
- Hypothesis 文本只进入 structured trace，不进入渲染后的 retrieved-memory/context-frame 文本。

### 4. 验证与错误矩阵

- 一个 hypothesis style 失败 -> 保留成功 style，并记录 style-specific fallback/error。
- 两种 hypothesis 都失败或超时 -> 降级为 raw-only retrieval。
- Hypothesis 输出为空 -> 忽略该 generated query，并记录 empty-output fallback。
- 缺少 hypothesis provider 或配置关闭 -> raw-only retrieval，并在 trace 中记录 disabled reason。
- 一个 vector embedding/search 失败 -> 用空 vector group 保持 index 对齐；成功的 vector groups 与 lexical 继续执行，`lane_status.vector="degraded"`。全部 vector queries 失败 -> `lane_status.vector="error"`，lexical 仍可返回。
- Lexical 关闭 -> 不执行 lexical SQL，`lane_status.lexical="disabled"`；无有效 terms -> `"no_terms"`；scoped lexical 失败而 global retry 成功 -> `"degraded"`，不能重标为 `"ok"`。
- Lexical SQL 失败 -> 返回 vector 结果，记录 `lexical_retrieval_failed`、稳定错误类型与 `lane_status.lexical="error"`。
- Scoped 两路都无最终结果 -> 两个 lane 一起按 global scope 重试。任一尝试发生的失败都不得被后续成功重标为完整双 lane 成功。

### 5. Good / Base / Bad Cases

- Good：一个位于所有 vector windows 外、`embedding IS NULL` 的 memory 精确命中 raw-query 稀有标识符，以 lexical-only 进入默认 final top-8，并保留 source evidence。
- Base：被动 context retrieval 执行 raw-query vector + raw-query lexical，不调用 hypothesis provider，注入时保留最终融合顺序。
- Bad：generated hypothesis 的字面词与 summary 重叠，从而制造 lexical-only hit。
- Bad：同一 memory 因 raw、event、general vector query 分别获得多份 RRF contribution。
- Bad：先 union vector/lexical rows 再打分，导致记录被伪标成未真正召回它的 lane 成员。

### 6. 必需测试

- Retriever test：event/general hypotheses 能召回 raw wording 未命中的 candidate。
- Retriever test：被动 context 不调用 hypothesis provider，explicit context queries 也不能替换 raw query 或驱动 lexical。
- Retriever test：generated hypotheses 不制造 lexical hit。
- Ranking test：重复 vector-query hit 只保留最佳 hit，不按 query 累加 RRF；等价候选使用单一时间快照与稳定 id tie-break。
- Ranking tests：vector-only、lexical-only、双 lane、lane rank/contribution、threshold-before-hotness、零权重行为，以及 `0.5` 对比 `1.0` 的 final 可见性。
- Retriever tests：embedding failure、vector SQL failure、lexical SQL failure、partial/degraded、disabled/no-terms、scope retry 状态聚合与 context injection 顺序。
- 真实 PostgreSQL acceptance：至少 32 个 vector decoys 加一个 NULL-embedding lexical target；先断言目标不在 vector window，再断言它进入公开 final top-8。
- Canonical memory recall eval：用 NULL-embedding fixture 断言 lexical candidate count/status，并按 recalled item id 关联 trace，证明 lexical rank/contribution 为正且 vector provenance 缺失。
- Bootstrap/config test：证明 lexical 默认开启，kill switch 正确注入 composed retriever。

### 7. Wrong vs Correct

#### 错误

```python
vector_rows = union_vector_rows(raw_query, event_hypothesis, general_hypothesis)
ranked = rank_multi_query_rows(
    vector_rows,
    query_vectors,
    queries,
    limit=top_k,
    threshold=threshold,
)
```

#### 正确

```python
queries = [raw_query, event_hypothesis, general_hypothesis]
query_vectors = await embed_with_per_query_failure_isolation(queries)
vector_groups = search_each_vector_query(query_vectors, filters)
lexical_rows = store.search_lexical_candidates(
    terms=tuple(extract_terms(raw_query)),
    **filters,
    limit=max(30, top_k * 2),
)
ranked, lane_trace = rank_candidate_lanes(
    MemoryCandidateLanes(
        vector_groups=vector_groups,
        lexical=tuple(lexical_rows),
    ),
    query_vectors,
    queries,
    limit=top_k,
    threshold=threshold,
    lexical_weight=1.0,
)
```

## 场景：长期记忆 retrieval 参数实验

### 1. 范围 / 触发

- 触发：新增或修改 Gold Set schema、qrels 指标、检索参数 profile、embedding cache、本地 PostgreSQL sweep、development/holdout 选择或实验 artifacts。
- 目标：用可复现的公共 `MemoryEngine.recall()` 行为选择参数，同时阻止 AI 自生成标签、跨用户数据、随机 embedding 或 holdout 泄漏制造虚假结论。

### 2. 签名

- `load_memory_retrieval_benchmark(case_file, *, enforce_v1_distribution=True) -> MemoryRetrievalBenchmark`
- `evaluate_retrieval_observation(query, observation, *, cutoff=8) -> QueryRetrievalMetrics`
- `aggregate_retrieval_metrics(metrics) -> RetrievalAggregateReport`
- `run_memory_retrieval_experiment(benchmark, *, profiles, split, ranking_time, db, embedding_provider, embedding_identity, artifacts_dir, formal=False, unlock_holdout=False, embedding_cache_fingerprint=None, ...) -> MemoryRetrievalExperimentReport`
- `python -m amadeus.evaluation.memory_retrieval_cli prepare-cache --benchmark <yaml> --cache <json> --env <env>`
- `python -m amadeus.evaluation.memory_retrieval_cli run --benchmark <yaml> --cache <json> --split <development|holdout> --stage <0..5> --ranking-time <ISO> --artifacts <dir>`
- `python -m amadeus.evaluation.memory_retrieval_cli collect-pool --benchmark <yaml> --cache <json> --split <development|holdout> --stage <0..5> --ranking-time <ISO> --artifacts <dir>`
- `python -m amadeus.evaluation.memory_retrieval_cli freeze-shortlist --results <stage-results.json> --source-stage <1..5> --profile <name> --output <shortlist.json>`
- `python -m amadeus.evaluation.memory_retrieval_cli rebase-shortlist --shortlist <stage-5.json> --source-benchmark <selection.yaml> --benchmark <adjudicated.yaml> --approved-overlay <holdout-qrels.yaml> --output <rebased.json>`

### 3. 契约

- qrels 使用 `0..3`；二值 relevant 固定为安全且 `grade >= 2`。`dangerous` 与 relevance 独立；缺少 judgment 是 unknown，不是 grade 0。
- 同一 `family_id` 的 variants 必须在同一 split；聚合先在 family 内平均，再跨 family macro average。
- `corpus_id` 是 family fixture 的组织边界，不是检索隔离边界；同一 split 引用的全部 corpora 必须 seed 到同一个实验 user/search universe。development eligible memory 数必须大于最大候选窗口 64，holdout 与 development 的 universe 必须隔离。
- `review_status=draft` 只能做 runner smoke；formal run 要求 dataset 与每个 family 都是 `approved`，并验证 60/42/18、30/21/9 和 6×10 分布。
- 正式 `memory_retrieval_benchmark_v1.yaml` 的规范化 `content_hash` 必须写入 task 的 `review/dataset-freeze.md`；测试重新计算并逐字比较 hash。修改正式语料、qrels、split 或 strata 时，必须显式发布新版本并重新审核，不能只更新冻结记录来掩盖漂移。
- final cutoff 固定为公开 request 的 `8`；参数 profile 不包含 final K。
- formal run 使用只读、文本哈希 keyed embedding cache；cache identity、维度或 input hash 漂移，以及 cache miss，都必须失败。
- cache prepare 使用 async provider 时，填充向量与 `provider.aclose()` 必须发生在同一个 event loop；禁止先 `asyncio.run(populate)` 再用第二个 `asyncio.run(aclose)`，否则 httpx transport 绑定的原 loop 已关闭。
- 每个 corpus 分配带 `memory_retrieval_experiment_id` marker 的随机高位 PostgreSQL user；其他用户干扰项使用另一个 user。清理只删除本次 marker 匹配的 users，依靠 FK cascade 清理其 memory rows；不得 `TRUNCATE`。
- corpus seed 一次，各 profile 只读复用；fixture SQL 显式冻结 `updated_at`、reinforcement、emotional weight、status 和 NULL embedding。
- 每个 profile/query 使用相同 frozen hypotheses、embedding 与 ranking time 重跑两次；top ids、candidate keys 或 lane status 不一致即 `nondeterministic_ranking` 硬门失败。
- Stage 2～4 必须加载上一阶段最多两个 frozen profiles，并校验 source stage、dataset hash、profile fingerprint 和 shortlist hash；变体从完整 inherited parameters `replace()` 当前 stage 字段，禁止从 baseline 重建。
- Stage 4 可在用户明确批准后收缩为每个 inherited profile 的 hotness baseline；Stage 5 只生成生产 baseline 与最多两个 Stage 4 finalists，并允许冻结最多三个 profile。
- Holdout pool 只能在 Stage 5 finalists 冻结后以 `split=holdout`、`stage=5`、显式 `unlock_holdout` 收集。unknown 仍须逐 pair 审核；proposal 和 approved qrels overlay 顶层都必须保留 `split: holdout`。
- 只新增 holdout qrels 会改变全局 dataset hash，但不得重新选参数。`rebase-shortlist` 必须加载 selection source benchmark，验证其 content hash、corpus、去除 judgments 后的 query 合同、全部旧 qrels 和 overlay 新 qrels；只有新 benchmark 恰好等于“source + approved holdout overlay”时才保留 finalist 参数并记录 `selection_dataset_hash` 与新 hash。
- 正式 holdout 必须在 rebased completeness 为 0 unknown 后运行一次；结果只用于预注册决策，不回流当前参数搜索。
- artifacts 输出 JSON、CSV 和中文 Markdown，记录 dataset/profile/git/database/provider lineage、逐 case stable keys、候选与质量指标；本任务不采集 P50/P95/elapsed，也不调用 LangSmith/answer LLM/judge。

### 4. 验证与错误矩阵

- draft dataset + `formal=True` -> 在 seed 前拒绝。
- 正式 YAML 的 `content_hash` 与冻结记录不一致 -> 测试失败；不得使用旧 hash 的实验 artifact 解释新数据集。
- holdout 未显式 unlock -> 拒绝；unlock 后结果不得回流本轮调参。
- final top-8 出现 unknown key -> `UnknownRetrievalJudgmentError`，先 adjudicate 并生成新 dataset version。
- development judging-pool 可在各 stage 收集；holdout judging-pool 只接受 frozen Stage 5 finalists + `unlock_holdout`。两者都使用冻结 embedding cache，只输出 unknown `(query, memory)`、summary 与 profile ranks，不得输出伪造的 Precision/Recall，也不得自动写回 grade 0。
- Stage 2～4 未提供连续上一阶段 shortlist、dataset hash/fingerprint/hash 不匹配 -> seed 前拒绝。
- Holdout proposal/approved overlay 缺少 `split: holdout`、引用 development query 或 source hash 不匹配 -> 在 rebase 前拒绝。
- Holdout qrels 改 hash 后直接加载旧 finalists -> 拒绝；只能通过验证后的 `rebase-shortlist` 重签，不能重跑 development 选择。
- Source benchmark 缺失、hash 不等于 shortlist selection hash，或新 benchmark 同时修改 corpus/query/旧 qrels/额外 qrels -> 拒绝为“only add approved qrels”。
- abstention query 声明 safe relevant/required key -> schema 拒绝；正常 query 没有 safe relevant -> schema 拒绝。
- dangerous judgment 无 reason、required key 不是 safe grade 2/3、family 跨 split、重复 id/key、空 strata -> schema 拒绝。
- embedding cache miss/identity/dimension/input hash 漂移 -> formal run 失败，不临时请求 provider。
- cache 已成功 flush、但 provider 在另一个 event loop 关闭 -> CLI 可能错误返回失败；改为单一 async 生命周期，并保留已落盘 cache 的只读完整性校验。
- vector/lexical error 或 degraded、跨 user/status/type/time/scoped candidate 泄漏、dangerous hit、重复运行不稳定 -> profile 硬门失败。
- 实验失败且 cleanup 同时失败 -> 保留原始异常，并用 exception note 记录 cleanup 类型；cleanup 不得掩盖根因。

### 5. Good / Base / Bad Cases

- Good：NULL-embedding 稀有标识符只由 lexical candidate lane 进入 top-8；observer 证明它不在任一 vector group，artifact 以 benchmark key 记录结果。
- Base：baseline 与候选 profile 对同一 approved development corpus 只读运行，输出 family-first Recall@8/nDCG/MRR/Precision 与 strata，速度不参与选择。
- Good：三组 finalists 先在 selection hash 上冻结；holdout unknown 经 approved holdout-only overlay 补齐后，只重签 dataset hash，再在 0 unknown 条件下运行一次正式 holdout。
- Bad：AI 同时生成 query/qrels 后直接标 approved；把未审核 top result 当 0；为每个 profile 重新调用 embedding provider；用 session id 隔离长期记忆；调用 `clean_postgres()`；把完整候选永久写进生产 trace。
- Bad：看到 holdout unknown 后重新选择参数，或补 qrels 后绕过 rebase 用旧 hash manifest 运行 formal holdout。

### 6. 必需测试

- Parameter unit：默认 profile、Akashic 15-window、范围/finite 校验、fingerprint、RRF k、hotness strength/emotional scale。
- Schema unit：YAML `embedding_mode: null`、重复 key/id、unknown corpus/key、danger reasons、required、abstention、family split 与 v1 distribution。
- Shared-universe integration：两个 development corpus 的 active memories 使用同一个实验 user；query 的候选能包含另一个 corpus 的已知干扰项，other-user 仍为零泄漏。
- Stage inheritance unit：Stage 2 继承 Stage 1 的 candidate windows；shortlist dataset drift 与 fingerprint drift 均拒绝。
- Finalist/rebase unit：Stage 5 可冻结最多三组；rebase 只接受 approved holdout-only qrels，保持参数不变并同时记录 selection/new dataset hash。
- Freeze unit：正式 dataset 可通过 `require_approved()`，且重新计算的 `content_hash` 必须存在于 `review/dataset-freeze.md`。
- Metric unit：grade 0-3、unknown、dangerous、required 合取、abstention、空/不足 8、rank 8/9、duplicate ids、family-first weighting。
- Cache unit：hashed keys 不保存原文、只读 replay、miss、identity/input drift、维度与 finite vector。
- Cache lifecycle unit：fake provider 记录 `embed()` 与 `aclose()` 的 running loop，断言二者是同一个对象。
- Real PostgreSQL integration：public recall、lexical-only provenance、other-user candidate zero leak、两次稳定、JSON/CSV/Markdown、只删除 experiment users 并保留既有 user。
- 广回归：`tests/evaluation tests/memory tests/db`、Ruff 与 Mypy。

### 7. 错误与正确示例

#### 错误

```python
for profile in profiles:
    clean_postgres()
    embeddings = await provider.embed_all(corpus)
    results = rank_candidate_lanes(rows, vectors, queries, limit=8, threshold=0.35)
```

#### 正确

```python
cache = FileEmbeddingCacheProvider(
    cache_path,
    identity=provider_identity,
    dimensions=1024,
    input_hash=benchmark_embedding_input_hash(benchmark),
)
report = run_memory_retrieval_experiment(
    benchmark,
    profiles=profiles,
    split="development",
    ranking_time=frozen_now,
    db=database,
    embedding_provider=cache,
    embedding_identity=provider_identity,
    embedding_cache_fingerprint=cache.fingerprint,
    artifacts_dir=artifacts_dir,
    formal=True,
)
```

补齐 holdout qrels 后，正确路径是重签而不是重新选点：

```python
rebase_finalist_shortlist_for_holdout_qrels(
    frozen_stage_five_path,
    source_benchmark=selection_benchmark,
    benchmark=benchmark_with_approved_holdout_qrels,
    approved_overlay_path=holdout_overlay_path,
    output_path=rebased_finalists_path,
)
```
