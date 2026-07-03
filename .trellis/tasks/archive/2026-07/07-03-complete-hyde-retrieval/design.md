# Complete Akashic-style dual-hypothesis retrieval design

## Resume Claim

- Claim supported: Akashic-inspired memory system with higher-quality recall.
- Public behavior proof: a `recall_memory` call can show raw query, event/general hypotheses, query-lane matches, and fallback reasons in trace.
- Akashic reference: `../akashic-agent/plugins/default_memory/engine.py::_query_answer`, `../akashic-agent/memory2/retriever.py::retrieve`.
- Verification command: focused memory retriever/acceptance/runtime tests plus bootstrap config tests.

## Architecture

Do not migrate `memory2/hyde_enhancer.py`; it is not the Akashic default-memory production path. Keep Amadeus aligned with the production default-memory behavior:

- `HypothesisProvider`
  - remains the LLM boundary;
  - generates `style="event"` and `style="general"` statements;
  - should enforce timeout/failure behavior either internally or through a small retriever-owned wrapper.
- `MemoryRetriever`
  - remains responsible for query planning, row filtering, Akashic-style vector max-pooling, vector/keyword RRF fusion, trace, and context rendering;
  - includes raw query plus generated hypotheses as vector query texts only for `intent="answer"` / explicit recall;
  - keeps passive context retrieval on the low-cost raw-query path;
  - keeps lexical matching raw-query-only by continuing to call `rank_rows()` with each query but ensuring trace and tests prove lexical hits from generated hypotheses do not introduce false literal matches, or by splitting vector/lexical lanes if needed.
- Bootstrap/config
  - wires dual-hypothesis enablement, timeout, and optional light model while preserving current long-term memory enablement behavior.

## Data Flow

```text
MemoryRecallRequest(intent="answer")
-> MemoryRetriever builds plan from raw query
-> if enabled:
   -> concurrently generate event/general hypotheses with timeout
   -> collect non-empty hypotheses as auxiliary queries
-> query_texts = dedupe(raw_query + aux_queries)
-> retrieval ranking over filtered rows
   -> vector lane considers all query_texts
   -> lexical lane should remain raw-query-oriented
   -> existing RRF/hotness ranking produces final records
-> MemoryQueryResult.records + trace
-> recall_memory / runtime trace
```

## Trace Contract

Add or normalize trace fields such as:

```python
"hypothesis_retrieval": {
    "enabled": True,
    "styles": ["event", "general"],
    "queries": {
        "event": "用户曾经...",
        "general": "用户偏好...",
    },
    "query_texts": ["raw", "event hypothesis", "general hypothesis"],
    "fallbacks": [],
    "errors": [],
}
```

Keep existing top-level fields compatible: `queries`, `fallbacks`, `errors`, `candidate_count`, `lane_counts`, `records`, and record `signals["matched_query_indexes"]`.

Trace is metadata, not prompt content. `MemoryContextResult.text`, `RuntimeContext.retrieved_memory`, and the prompt context frame must contain only rendered real memory records, never generated hypotheses or trace JSON.

CLI formatting is intentionally out of scope. Existing CLI trace should continue to work, but this task does not add a dedicated human-readable hypothesis section.

## Configuration

Extend `RuntimeConfig` and `.env.example` with:

- `AMADEUS_MEMORY_HYPOTHESIS_RETRIEVAL_ENABLED`, default true when long-term memory is enabled.
- `AMADEUS_MEMORY_HYPOTHESIS_TIMEOUT_SECONDS`, default around `2.0`.
- Optional `OPENAI_LIGHT_MODEL`, defaulting to `OPENAI_MODEL`.

Prefer neutral "hypothesis retrieval" naming over "HyDE" in env keys to avoid implying raw-first classic HyDE semantics.

## Compatibility

- Existing Amadeus partial behavior already generates `event` and `general` queries. The task should harden and make it observable rather than inventing a separate retrieval path.
- Source references and evidence stay attached to real `MemoryRecord`s; generated hypotheses never become records.
- Existing `build_query_plan(... use_hypotheses=intent == "answer")` remains the right high-level trigger.
- Passive `build_context()` calls must not generate hypotheses unless the caller explicitly uses `intent="answer"`.
- Tests should guard that hypothesis text appears in trace/tool output but not in rendered retrieved-memory blocks.

## Failure Boundaries

- A failed `event` hypothesis does not block `general`, and vice versa.
- Both failed/empty hypotheses degrade to raw-only retrieval.
- Failure details are trace data, not user-facing exceptions.
- Raw retrieval failures follow existing retrieval error handling; hypothesis retrieval should not mask baseline failures.

## Trade-offs

- This is less "classic HyDE" than raw-first append, but it matches Akashic default memory's actual production path.
- Unified fusion can reorder records based on auxiliary vector matches, unlike raw-first append. This is acceptable because Akashic default also lets auxiliary query lanes influence final RRF.
- Passive-context use is out of scope for this task because it adds per-turn LLM latency and does not match Akashic default `_query_answer()` scope.
