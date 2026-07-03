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
