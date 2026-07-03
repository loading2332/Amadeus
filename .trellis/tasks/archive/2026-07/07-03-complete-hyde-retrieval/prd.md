# Complete Akashic-style dual-hypothesis retrieval

## Goal

Implement Akashic default-memory style dual-hypothesis retrieval in Amadeus so the resume claim "Akashic-inspired memory system" can include the same practical retrieval-quality mechanism Akashic actually runs in its default memory plugin.

This is not the raw-first `HyDEEnhancer` helper path. The target is Akashic's production default pattern: for answer/recall-style retrieval, generate two memory-shaped auxiliary queries (`event` and `general`), send raw query plus both hypotheses through vector lanes, keep lexical matching on the raw query, and fuse results through the existing ranking path.

## Confirmed Facts

- Akashic has a standalone raw-first helper in `../akashic-agent/memory2/hyde_enhancer.py`, but static call-chain inspection found no production instantiation from `plugins/default_memory`.
- Akashic's default memory engine actually runs hypothesis expansion in `../akashic-agent/plugins/default_memory/engine.py::_query_answer`: it concurrently calls `_gen_hypothesis(request.text, style="event")` and `_gen_hypothesis(request.text, style="general")`, then passes the non-empty results as `aux_queries`.
- Akashic's `../akashic-agent/memory2/retriever.py::retrieve` dedupes `[query, *aux_queries]`, sends all query texts into vector lanes, uses the original query only for keyword retrieval, and performs one final RRF merge.
- Akashic labels these outputs as `hyde_hypotheses` in trace, but the behavior is more accurately "memory-type-aware MultiQuery / dual-hypothesis query expansion" than classic raw-first HyDE.
- Amadeus uses `MemoryRetriever.recall()` with `LLMHypothesisProvider` for `event` and `general`, appends those strings to `queries`, runs every query through vector scoring, keeps only the best vector hit per memory id, then merges that vector pool with raw-query lexical hits through RRF. Evidence: `amadeus/memory/retriever.py`, `amadeus/memory/providers.py`, `amadeus/memory/ranking.py`.
- Amadeus is missing the Akashic-equivalent production proof: explicit trace fields for generated hypotheses, lane-level query accounting, failure/timeout behavior, config wiring, and tests that prove dual-hypothesis retrieval improves recall without breaking raw lexical/source/evidence behavior.

## Requirements

- Keep the Akashic default-memory semantics:
  - generate at most two auxiliary memory-shaped queries: `event` and `general`;
  - raw query always participates;
  - vector retrieval considers raw + generated auxiliary queries;
  - lexical retrieval remains based on raw query only;
  - final ordering uses the existing Amadeus ranking/fusion path rather than a raw-first append helper.
- Add an explicit production boundary for hypothesis generation behavior:
  - timeout/exception/empty output must degrade to raw-only retrieval;
  - failures must be visible in trace but must not break passive turns or recall tools;
  - generated hypotheses must never be persisted as memory records.
- Expose interview-grade trace fields:
  - whether dual-hypothesis retrieval was enabled;
  - generated `event` and `general` hypothesis texts when available;
  - which query indexes matched each returned record;
  - per-query vector/lexical lane counts already available from the retriever;
  - fallback/error reasons for failed hypothesis generation.
- Keep trace out of model context:
  - generated hypotheses and trace metadata must not be rendered into `retrieved_memory` or the prompt context frame;
  - only real retrieved memory summaries may enter context.
- Preserve existing retrieval contracts:
  - source references and evidence must be preserved;
  - scope fallback, time filters, memory type filters, context rendering, and hotness scoring must keep working;
  - runtime/proactive code must continue to go through `MemoryEngine` or explicit context contracts.
- Trigger dual-hypothesis retrieval only for explicit answer / recall-memory paths. Passive context retrieval must stay raw-query-first and must not spend an LLM call on every turn.
- Add configuration only where it creates real operational behavior:
  - enable/disable flag for dual-hypothesis retrieval;
  - timeout seconds;
  - optional light model selection, defaulting to the main provider/model if absent.
- Update interview docs so the claim says "Akashic-style dual-hypothesis retrieval" or equivalent, not "classic HyDE" or raw-first HyDE.

## Acceptance Criteria

- [x] Tests prove `answer`/recall-style retrieval generates `event` and `general` auxiliary queries and includes them in vector retrieval.
- [x] Tests prove lexical lane remains raw-query-only.
- [x] Tests prove hypothesis timeout/exception/empty output falls back to raw-only retrieval and records trace fallbacks/errors.
- [x] Tests prove generated hypotheses are exposed in trace but are not persisted as memory records.
- [x] Tests prove generated hypotheses do not enter rendered context unless the same text is an actual stored memory summary.
- [x] Tests prove dual-hypothesis retrieval can recall a relevant candidate that raw wording alone misses.
- [x] Bootstrap/config tests prove the feature can be disabled and timeout/light model config is wired deterministically.
- [x] Existing focused memory/runtime tests still pass.
- [x] Documentation under `docs/interview/` maps this claim to code evidence and keeps raw-first `HyDEEnhancer` out of the claim.

## Verification

- `.\.venv\Scripts\python.exe -m ruff check amadeus/memory/retriever.py amadeus/memory/ranking.py amadeus/app/bootstrap.py tests/memory/test_memory_retriever.py tests/memory/test_bootstrap_long_term_memory.py` -> passed.
- `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_retriever.py tests/memory/test_bootstrap_long_term_memory.py -v` -> 15 passed.
- `.\.venv\Scripts\python.exe -m pytest tests/memory/test_memory_ranking.py tests/memory/test_session_memory_runtime.py tests/memory/test_memory_retrieval_acceptance.py tests/memory/test_runtime_memory.py tests/memory/test_memory_retriever.py tests/memory/test_bootstrap_long_term_memory.py tests/app/test_cli.py tests/app/test_bootstrap_tool_runtime.py -v` -> 59 passed.

## Out of Scope

- Do not implement or wire Akashic's raw-first `memory2/hyde_enhancer.py` helper in this task.
- Do not migrate sqlite-vec.
- Do not add a dashboard or memory inspector UI.
- Do not implement broad query-rewrite gates, route classifiers, or LongMemEval benchmark integration.
- Do not make real LLM smoke tests mandatory unless configuration is available.

## Resolved Decisions

- Adopt Akashic default-memory dual query expansion rather than raw-first `HyDEEnhancer`.
- Dual-hypothesis retrieval applies only to explicit answer / `recall_memory` retrieval, matching Akashic `_query_answer()`. Passive context retrieval remains the low-cost raw-query path.
- Hypothesis trace is runtime/debug metadata only. It must remain outside `retrieved_memory` and the model context frame.
- Do not add a new CLI `--trace` hypothesis summary in this task. Structured trace and tool output are sufficient for verification.
- Dual-hypothesis retrieval is enabled by default when long-term memory and a hypothesis provider are available, matching Akashic default behavior. `AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED=0` is the kill switch.

## Open Question

- None.
