# Complete Akashic-style dual-hypothesis retrieval implementation plan

## Preconditions

- User approves the planning artifacts.
- Task is started with `python ./.trellis/scripts/task.py start .trellis/tasks/07-03-complete-hyde-retrieval`.
- Before editing, run `trellis-before-dev` and read backend quality specs.

## Implementation Checklist

1. Add failing retriever tests for Akashic-style dual hypotheses.
   - Extend `tests/memory/test_memory_retriever.py`.
   - Use deterministic embeddings and a fake hypothesis provider.
   - Prove `event` and `general` are generated for `intent="answer"`.
   - Prove generated query texts appear in trace.
   - Prove a candidate matched by a generated query can be returned.
   - Prove `intent="context"` does not call the hypothesis provider.

2. Add failure-boundary tests.
   - One style raises or times out while the other succeeds.
   - Both styles fail/empty -> raw-only retrieval.
   - Trace includes fallback/error reasons.

3. Add lane semantics tests.
   - Prove lexical matching is raw-query-only or document the exact Amadeus fusion behavior if existing `rank_rows()` makes generated-query lexical matching unavoidable.
   - Preserve source_ref/evidence and `matched_query_indexes` on returned records.
   - Prove hypothesis trace does not get rendered into retrieved memory/context-frame text.

4. Add bootstrap/config tests.
   - Extend `tests/memory/test_bootstrap_long_term_memory.py` and/or `tests/app/test_bootstrap_tool_runtime.py`.
   - Cover default enabled behavior, explicit disable flag, timeout parsing, and optional light model wiring.

5. Harden implementation.
   - Update `HypothesisProvider` / `LLMHypothesisProvider` for timeout and optional light model as needed.
   - Update `MemoryRetriever` trace to expose hypothesis retrieval clearly.
   - Keep generated hypotheses out of persistence.
   - Avoid adding raw-first `HyDEEnhancer` unless the plan is explicitly changed.

6. Update docs and specs.
   - Update `docs/interview/resume-claim-gap-audit.md`.
   - Update `docs/interview/interview-delivery-roadmap.md`.
   - Add a dual-hypothesis retrieval scenario to `.trellis/spec/backend/quality-guidelines.md` if implementation establishes new contracts.
   - Do not add a new CLI hypothesis trace section unless the plan changes.

## Validation Commands

Run narrow checks first:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_retriever.py tests/memory/test_memory_retrieval_acceptance.py -v
```

Then run cross-boundary checks:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/memory/test_runtime_memory.py tests/app/test_bootstrap_tool_runtime.py tests/memory/test_bootstrap_long_term_memory.py -v
```

Lint touched files:

```powershell
.\.venv\Scripts\python.exe -m ruff check amadeus\memory tests\memory tests\app\test_bootstrap_tool_runtime.py
```

Known limitation before this task starts: full-repo `mypy` and `ruff check amadeus tests dev_utils` currently fail on unrelated evaluation/bootstrap files. Do not treat those as regressions unless touched by this task.

## Rollback Points

- If code changes start pulling hypotheses into passive context, stop and keep the feature limited to `intent="answer"`.
- If light model config expands too much scope, use main provider/model and keep light-provider split as future work.
- If lexical raw-only semantics require too much ranking refactor, preserve current behavior but document and test the exact fusion contract before implementation starts.
