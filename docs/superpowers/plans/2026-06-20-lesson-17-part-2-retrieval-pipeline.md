# Lesson 17 Part 2 Retrieval Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce the retrieval-quality mechanisms that are wired into Akashic's current production call chain while preserving Amadeus's `MemoryEngine` boundary.

**Architecture:** `VectorMemoryEngine` remains the single facade used by passive pre-retrieval and `recall_memory`. Internally it plans queries by intent, runs independent dense and lexical rankings, fuses them with deterministic RRF, max-pools multi-query results, and renders a budgeted context block only for passive injection. Optional LLM hypotheses are injected through a small protocol and fail open to the raw query.

**Tech Stack:** Python 3.11, asyncio, SQLite, pytest, ruff, mypy, existing OpenAI-compatible `LLMProvider`.

---

## File map

- Modify `amadeus/memory_engine.py`: keep the public query types stable; document trace and query-context fields through tests rather than adding a second result type.
- Modify `amadeus/vector_memory.py`: query planning, independent lanes, deterministic RRF, multi-query max-pool, structured injection, trace.
- Modify `amadeus/runtime.py`: mark passive pre-retrieval as `intent="context"` and provide history context.
- Modify `amadeus/bootstrap.py`: inject the existing `LLMProvider` as an optional hypothesis provider without adding a dependency.
- Modify `tests/test_vector_memory.py`: focused tests for lanes, RRF, intents, hypotheses, procedure pooling, injection budget and trace.
- Modify `tests/test_runtime_vector_memory.py`: passive intent and context-frame smoke.
- Modify `tests/test_bootstrap_tool_runtime.py`: provider wiring without making a real chat call.
- Modify `lessons/0012-lesson-17-retrieval-quality-pipeline-part-2.html`: replace the provisional RRF-only lesson with verified Part 2A-2F evidence.
- Do not commit `learning-records/0006-rrf-fusion-gap-dual-retrieval-mode.md` until the user proves the required understanding.

### Task 1: Stabilize independent lanes and deterministic RRF

**Files:**
- Modify: `amadeus/vector_memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add failing determinism and dual-lane signal tests**

Add tests that call `_rrf_merge()` repeatedly with equal scores and assert a stable ID order, and assert a record hit by both lanes exposes both raw scores:

```python
def test_rrf_equal_scores_use_stable_id_tiebreak():
    expected = [("a", 1.0 / 61), ("b", 1.0 / 61)]
    for _ in range(10):
        assert _rrf_merge([("b", 0.5), ("a", 0.5)], [], top_n=2) == expected


def test_rank_rows_preserves_both_lane_scores():
    result = _rank_rows(_dual_lane_rows(), [1.0, 0.0], "仁王", limit=3, threshold=0.3)
    dual = next(record for record in result if record.id == "dual")
    assert dual.signals["lanes"] == ["vector", "lexical"]
    assert dual.signals["vector_score"] > 0
    assert dual.signals["lexical_score"] > 0
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "rrf or lane" -v`

Expected: the tie test or `signals["lanes"]` test fails against the provisional draft.

- [ ] **Step 3: Make RRF deterministic and preserve lane evidence**

Use score-descending/ID-ascending lane ranking and final `(-rrf_score, item_id)` ordering. Build signals as:

```python
signals = {
    "lanes": [name for name, score in (("vector", vector_score), ("lexical", lexical_score)) if score > 0],
    "vector_score": vector_score,
    "lexical_score": lexical_score,
    "rrf_score": rrf_score,
}
```

Return `[]` when `top_n <= 0`; do not coerce it to one.

- [ ] **Step 4: Run focused and existing vector-memory tests**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -v`

Expected: all vector-memory tests pass.

### Task 2: Add Akashic-aligned lexical terms and query-plan helpers

**Files:**
- Modify: `amadeus/vector_memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add failing term-extraction and query-plan tests**

Cover ASCII words, CJK bigrams, stop-word removal, explicit context queries, and procedure kinds:

```python
def test_extract_terms_adds_cjk_bigrams_and_removes_stop_words():
    terms = _extract_terms("我之前讨论过仁王机制")
    assert "仁王" in terms
    assert "机制" in terms
    assert "之前" not in terms


def test_context_query_plan_uses_explicit_queries():
    query = MemoryQuery(text="原问题", intent="context", context={"queries": ["历史问题", "偏好问题"]})
    plan = _build_query_plan(query)
    assert plan.queries == ("历史问题", "偏好问题")


def test_procedure_query_plan_limits_memory_kinds():
    plan = _build_query_plan(MemoryQuery(text="如何发布", intent="procedure"))
    assert plan.kinds == ("procedure", "preference")
    assert len(plan.queries) >= 1
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "extract_terms or query_plan" -v`

Expected: missing bigrams/query-plan helper causes failure.

- [ ] **Step 3: Implement pure planning helpers**

Add a frozen private `_QueryPlan(queries, kinds, use_hypotheses)` dataclass. Normalize whitespace, preserve order, deduplicate strings, and generate deterministic procedure variants without an LLM. Keep the lexical lane OR-LIKE; do not label it BM25.

- [ ] **Step 4: Run focused tests**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "extract_terms or query_plan" -v`

Expected: all selected tests pass.

### Task 3: Add active answer hypotheses and multi-query max-pool

**Files:**
- Modify: `amadeus/vector_memory.py`
- Modify: `amadeus/bootstrap.py`
- Test: `tests/test_vector_memory.py`
- Test: `tests/test_bootstrap_tool_runtime.py`

- [ ] **Step 1: Add failing success and fail-open tests**

Define a test double implementing:

```python
class FakeHypothesisProvider:
    async def generate(self, query: str, *, style: str) -> str:
        if style == "event":
            return "用户曾经完成 Amadeus 检索重构"
        return "Amadeus memory retrieval implementation"
```

Assert `intent="answer"` traces raw/event/general queries, deduplicates repeated hypotheses, max-pools the same memory ID, and falls back to the raw query when the provider raises.

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "hypothesis or multi_query" -v`

Expected: constructor/provider/query trace assertions fail.

- [ ] **Step 3: Implement the hypothesis boundary**

Add a protocol:

```python
class HypothesisProvider(Protocol):
    async def generate(self, query: str, *, style: str) -> str: ...
```

Add an `LLMHypothesisProvider` adapter that calls the existing `LLMProvider.chat()` with `tools=[]`, `disable_thinking=True`, a bounded token count, and a prompt for either event or general style. `VectorMemoryEngine` accepts it as optional. Use `asyncio.gather(..., return_exceptions=True)` and record errors without failing the raw query.

- [ ] **Step 4: Implement multi-query retrieval and max-pool**

For each normalized query, run the shared lane/RRF path. Merge records by ID, keeping the highest RRF score; merge `matched_queries` and lane signals. Sort by `(-score, id)` before applying `limit`.

- [ ] **Step 5: Wire the adapter in bootstrap**

When vector memory is enabled, construct `LLMHypothesisProvider(provider=provider)` and pass it to `VectorMemoryEngine`. The adapter is not called during bootstrap.

- [ ] **Step 6: Run focused tests**

Run: `uv run --extra dev pytest tests/test_vector_memory.py tests/test_bootstrap_tool_runtime.py -k "hypothesis or multi_query or build_passive" -v`

Expected: all selected tests pass without network access.

### Task 4: Implement structured context injection and character budget

**Files:**
- Modify: `amadeus/vector_memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add failing structured-output tests**

Create results containing procedure, preference/profile and event records. Assert headings, IDs, source refs, deterministic ordering, `injected_ids`, and that a small budget drops whole low-priority entries rather than truncating an entry.

```python
def test_render_context_block_groups_records_and_tracks_injected_ids():
    result = MemoryQueryResult(records=[procedure_record(), preference_record(), event_record()], trace={})
    block = engine(context_char_budget=800).render_context_block(result)
    assert "## Applicable Procedures" in block
    assert "## User Profile" in block
    assert "## Relevant History" in block
    assert result.trace["injected_ids"] == ["proc", "pref", "event"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "context_block or injection" -v`

Expected: current flat `## Retrieved Memory` output fails.

- [ ] **Step 3: Implement whole-entry budgeting**

Add `context_char_budget` to `VectorMemoryEngine`. Format sections in priority order: procedure/constraint, profile/preference, event/history. Append a complete entry only if it fits. Record `injected_ids`, `omitted_ids`, and `injection_char_count` in the existing trace dict.

- [ ] **Step 4: Run focused tests**

Run: `uv run --extra dev pytest tests/test_vector_memory.py -k "context_block or injection" -v`

Expected: all structured injection tests pass.

### Task 5: Mark passive intent and complete retrieval trace/failure isolation

**Files:**
- Modify: `amadeus/runtime.py`
- Modify: `amadeus/vector_memory.py`
- Test: `tests/test_runtime_vector_memory.py`
- Test: `tests/test_vector_memory.py`

- [ ] **Step 1: Add a failing runtime intent test**

Extend the recording memory fake to retain received queries:

```python
assert memory.queries[0].intent == "context"
assert memory.queries[0].context["history"] == []
```

- [ ] **Step 2: Add trace and failure-path tests**

Assert trace contains `intent`, `queries`, `lane_counts`, `fused_count`, `record_count`, `fallbacks`, and `errors`. Distinguish embedding failure from zero hits and confirm lexical results remain available.

- [ ] **Step 3: Run and confirm failure**

Run: `uv run --extra dev pytest tests/test_runtime_vector_memory.py tests/test_vector_memory.py -k "intent or trace or fails" -v`

Expected: passive intent/trace assertions fail.

- [ ] **Step 4: Implement passive query shape and trace**

Build passive queries as:

```python
MemoryQuery(
    text=user_message,
    intent="context",
    context={"history": history, "session_key": session_key},
)
```

In the engine, aggregate lane counts per query and record errors as structured strings. Do not swallow database errors inside the engine; `PassiveRuntime` remains the fail-open boundary.

- [ ] **Step 5: Run runtime and vector tests**

Run: `uv run --extra dev pytest tests/test_runtime_vector_memory.py tests/test_vector_memory.py -v`

Expected: all tests pass.

### Task 6: Joint passive/tool verification and regression suite

**Files:**
- Modify: `tests/test_runtime_vector_memory.py`
- Modify: `tests/test_runtime.py`
- Test: `tests/test_session_tool_chain_history.py`

- [ ] **Step 1: Add an end-to-end fake-provider test**

The fake provider first returns a `recall_memory` tool call and then a final answer. Assert the first provider payload contains the passive structured block, the second payload retains that block and adds one `role="tool"` JSON result, and both paths can reference the same memory ID without duplicate records inside either result.

- [ ] **Step 2: Run the new test and confirm failure if wiring is incomplete**

Run: `uv run --extra dev pytest tests/test_runtime_vector_memory.py -k "passive_and_active" -v`

Expected: fail until the fake tool loop and new block headings are wired correctly.

- [ ] **Step 3: Make only the minimal wiring corrections**

Do not add cross-message deduplication. Fix only protocol-shape, tool registration or trace propagation errors exposed by the test.

- [ ] **Step 4: Run full verification**

Run:

```powershell
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy amadeus
```

Expected: all tests pass; ruff and mypy report no errors.

### Task 7: Update the formal lesson and perform the gap audit

**Files:**
- Modify: `lessons/0012-lesson-17-retrieval-quality-pipeline-part-2.html`
- Preserve unverified: `learning-records/0006-rrf-fusion-gap-dual-retrieval-mode.md`

- [ ] **Step 1: Replace provisional claims with verified evidence**

Document the actual code paths, query intent differences, hypothesis fail-open, structured injection, exact commands and observed outputs. Explicitly correct Part 1's implication that `QueryRewriter`, `SufficiencyChecker`, or `HyDEEnhancer` are wired into Akashic's production path.

- [ ] **Step 2: Add the final gap table**

Record exact destinations:

- isolated Akashic experimental modules: re-audit in Lesson 40 or when Akashic wires them;
- unified retrieval trace schema: Lesson 36;
- retrieval eval harness: Lesson 39;
- stage acceptance and eval seeds: Lesson 18.

Do not use “later optimization” as a destination.

- [ ] **Step 3: Validate the lesson artifact**

Run local link/path checks and open the HTML in a browser if available. Confirm the title is “对应总计划 Lesson 17 / Part 2” and all referenced files exist.

- [ ] **Step 4: Do not create a learning record yet**

Ask the user to explain the Akashic and Amadeus chains, RRF evidence, passive/active boundary, and failure handling. Only after a correct explanation may the existing untracked record be corrected and committed.

## Plan self-review

- Spec sections 1-10 map to Tasks 1-7.
- No standard BM25, reranker, `QueryRewriter`, `SufficiencyChecker`, or `HyDEEnhancer` production wiring is included.
- Public `MemoryEngine.query()` and `render_context_block()` remain stable.
- Every behavior-changing task starts with a failing focused test and ends with a verification command.
- Existing uncommitted RRF and lesson files are treated as provisional user work and refined in place, not discarded.
