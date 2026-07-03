# Design

## Architecture

The memory write lifecycle should expose separate verbs for separate state transitions:

- `memorize(request)` creates or reinforces a memory item.
- `supersede_many(target_ids, replacement_id=None, reason=...)` retires existing items.
- `record_replacement(...)` records the relation between old and new items.

`replace_many` currently combines all three. The refactor keeps public behavior intact while making the code path explainable in interviews and closer to Akashic's `supersede_batch` boundary.

## Contracts

### MemoryMemorizer.supersede_many

Inputs:

- `target_ids: list[str]`
- `reason: str`
- `replacement_id: str | None = None`
- `replacement_source_ref: str | None = None`

Behavior:

- Deduplicate target ids.
- Load existing target items and report missing ids.
- If no targets exist, return a non-accepted `MemoryMutationResult(status="missing")`.
- Mark found targets as `superseded`.
- Patch each target extra with `superseded_reason`, and `replacement_id` only when provided.
- If `replacement_id` is provided, record one replacement relation per found old id using `replacement_source_ref`.
- Return affected ids and trace fields that expose `superseded_ids`, `replacement_id`, and replacement relation count.

### Replacement write flow

`PostResponseMemoryWorker` handles a decision action `replace` by:

1. Building a `MemoryWriteRequest`.
2. Calling `memorizer.memorize(request)`.
3. Calling `memorizer.supersede_many(target_ids, replacement_id=..., replacement_source_ref=request.source_ref, reason=decision.reason)`.
4. Reporting `written_ids` and `superseded_ids` in the existing trace shape.

### Compatibility

`replace(target_id, request)` may stay as a convenience wrapper for tool/tests because it is clear for single-id correction and currently used in tests.

`replace_many(...)` is removed. New and existing replacement flows must use `memorize + supersede_many` directly.

## Data Flow

```text
LLM decision replace
-> PostResponseMemoryWorker
-> MemoryMemorizer.memorize(new request)
-> MemoryMemorizer.supersede_many(old ids, replacement_id, source_ref)
-> MemoryStore.mark_items_status(old ids, status=superseded)
-> MemoryStore.record_replacement(old id, new id, source_ref)
-> undo_by_source(source_ref) can restore old ids and supersede new id
```

## Tradeoffs

- We do not expand `memory_replacements` with full old/new snapshots yet. Current source-ref relation is enough for undo and existing eval evidence.
- We keep `replace(target_id, request)` for low churn. It delegates to the clearer lifecycle and does not block the interview explanation.
- We avoid changing public `MemoryEngine` protocol; this is an internal memorizer contract refinement.

## Rollback

The change is confined to `amadeus/memory/memorizer.py`, `amadeus/memory/post_response_worker.py`, and tests. Rollback is to restore the previous memorizer implementation if focused memory tests fail.
