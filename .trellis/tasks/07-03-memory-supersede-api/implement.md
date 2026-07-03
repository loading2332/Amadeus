# Implementation Plan

## Checklist

1. Add focused tests in `tests/memory/test_memory_memorizer.py` for `supersede_many`:
   - marks multiple existing ids superseded;
   - records replacement relations when `replacement_id` and source_ref are provided;
   - reports missing ids without failing existing ids.
2. Update existing replace/undo tests to prove `replace` delegates to the new supersede lifecycle and preserves undo behavior.
3. Implement `MemoryMemorizer.supersede_many(...)`.
4. Refactor `MemoryMemorizer.replace(...)` to call `supersede_many` and remove `replace_many(...)`.
5. Refactor `PostResponseMemoryWorker` replace action to call `memorize` then `supersede_many`, not `replace_many`.
6. Search for stale production `replace_many` references.
7. Run focused validation.

## Validation Commands

```bash
uv run ruff check amadeus/memory/memorizer.py amadeus/memory/post_response_worker.py tests/memory/test_memory_memorizer.py tests/memory/test_memory_post_response_worker.py
uv run pytest tests/memory/test_memory_memorizer.py tests/memory/test_memory_post_response_worker.py tests/memory/test_memory_store.py tests/tools/test_undo_memory_by_source_tool.py tests/memory/test_forget_memory_tool.py
uv run pytest tests/memory tests/evaluation/test_memory_quality_runner.py
rg -n "replace_many" amadeus tests
```

## Risk Points

- `undo_by_source` depends on `memory_replacements.source_ref`; replacement flow must pass the new memory source_ref.
- `MemoryMutationResult.trace["replacement_id"]` is consumed by `PostResponseMemoryWorker`; preserve equivalent trace.
- Existing dirty worktree includes unrelated evaluation changes; do not stage, revert, or edit unrelated files.

## Review Gate

Before `task.py start`, confirm the plan is approved for implementation.
