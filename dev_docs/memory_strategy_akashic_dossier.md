# Akashic-Inspired Memory Strategy Dossier

## Strategy Identity

This strategy represents the local Akashic reference design, reduced to a
testable Amadeus memory prototype.

Primary evidence:

- `/Users/didi/develop/akashic-agent/tutorial/research/memory-systems-map.md:184`
  to `:200`
- `/Users/didi/develop/akashic-agent/agent/memory.py:29` to `:37`
- `/Users/didi/develop/akashic-agent/core/memory/runtime.py:29` to `:63`
- `/Users/didi/develop/akashic-agent/core/memory/engine.py:10` to `:119`
- `/Users/didi/develop/akashic-agent/core/memory/markdown.py:956` to `:1111`
- `/Users/didi/develop/akashic-agent/plugins/default_memory/engine.py:524`
  to `:783`
- `/Users/didi/develop/akashic-agent/memory2/models.py:4` to `:17`
- `/Users/didi/develop/akashic-agent/memory2/retriever.py:83` to `:138`
  and `:279` to `:385`

Evidence level: A.

Reason: local tutorial analysis, core runtime interfaces, markdown lifecycle,
engine implementation, typed memory model, and retriever implementation all
agree on the same architecture boundary.

## Original System Data Flow

```text
turn committed
-> markdown maintenance queue
-> consolidate old turns or refresh recent context
-> append HISTORY/PENDING/journal with source_ref
-> emit ConsolidationCommitted
-> semantic engine extracts/stores typed MemoryItem records
-> query runtime delegates to memory engine
-> vector lane + keyword lane retrieval
-> RRF fusion
-> typed injection block
-> low-frequency optimizer merges PENDING into MEMORY/SELF
```

The important shape is not "markdown instead of database." The important shape
is a split between:

```text
low-frequency, auditable prompt assets
high-frequency, query-time semantic working index
source_ref/provenance connecting both sides
```

## Core Mechanisms

1. Markdown control plane.

   `MEMORY.md`, `SELF.md`, `PENDING.md`, `HISTORY.md`,
   `RECENT_CONTEXT.md`, and journal files are separate assets with different
   update frequencies and responsibilities. Stable profile/self context is not
   mixed with append-only history.

2. Runtime boundary.

   `MemoryRuntime` reads markdown prompt assets but delegates query and mutation
   to a `MemoryEngine`. This lets Amadeus test a strategy adapter without
   pretending the markdown files themselves are the whole memory system.

3. Provenance.

   `source_ref` appears in markdown append paths and semantic memory records.
   This is the basis for traceability, idempotence, recall evidence, and later
   correction/forget flows.

4. Typed semantic records.

   Semantic memory items distinguish `procedure`, `preference`, `event`, and
   `profile`. The injection layer treats these types differently.

5. Retrieval fusion.

   Akashic uses vector lanes and a keyword lane, then fuses results with RRF.
   Keyword recall is an independent recall path, not only a score decoration.

6. Injection by type and change frequency.

   Forced procedures can be injected even when normal score thresholds would
   filter them out. Procedures/preferences and event/profile memories have
   separate budgets and formatting.

## Non-Omittable Mechanisms

The Amadeus prototype stops being Akashic-inspired if it omits these:

- Stable prompt assets are separated from query-time retrieved memories.
- Dynamic retrieval output does not dump all history or all pending facts.
- Every memory artifact keeps provenance/source_ref in the trace.
- Retrieved records have memory type labels.
- Keyword and vector retrieval are separate lanes before fusion.
- Injection formatting distinguishes forced procedures, procedures/preferences,
  and event/profile memories.

## Omittable In The First Version

These can be deferred because first-version eval uses fixed artifacts:

- Raw conversation extraction.
- Background post-response worker.
- Actual markdown file writes during the benchmark.
- Snapshot/rollback transaction implementation.
- Memory optimizer that merges `PENDING.md` into `MEMORY.md` and `SELF.md`.
- Tool-requirement enforcement beyond representing forced procedure injection.

These omissions must be visible in the trace under `omitted_capabilities`.

## Minimal Prototype Definition

For fixed memory artifacts, the Akashic adapter should:

```text
1. Accept artifacts with id, text, type, timestamp, scope, and source_ref.
2. Split stable profile/self artifacts from dynamic semantic artifacts.
3. Index dynamic artifacts into typed records.
4. Run vector retrieval and keyword retrieval as independent lanes.
5. Fuse results.
6. Build an injection block with Akashic-like sections and budgets.
7. Return records, injected ids, source_refs, and lane-level trace.
```

The adapter does not need to use Akashic's directory layout. It needs to preserve
the control-plane/working-index/provenance behavior.

## Fidelity Checklist

- [ ] Stable profile/self artifacts are injected even when no retrieval hit
      matches the query.
- [ ] Query-time retrieval injects selected records only, not the full history
      or all pending artifacts.
- [ ] `source_ref` survives from artifact ingestion through final trace.
- [ ] The same query can produce separate vector and keyword lane hits before
      fusion.
- [ ] A lexical-only hit can be recovered by the keyword lane.
- [ ] Procedure/preference and event/profile items use different injection
      budgets or sections.
- [ ] A forced procedure can be injected despite lower normal relevance.
- [ ] The final answer trace can show which injected memory ids were used.

## Conclusion Boundary

If this prototype performs well, Amadeus can claim that Akashic-style separation
of stable prompt assets, typed semantic retrieval, provenance, and typed
injection is useful for the evaluated tasks.

It cannot claim that Akashic's full lifecycle is validated until extraction,
background consolidation, optimizer merge, snapshot/rollback, update, and
forgetting are added to the eval suite.

