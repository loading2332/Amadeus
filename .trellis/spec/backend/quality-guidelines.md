# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)

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
