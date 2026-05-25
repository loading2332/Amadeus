# mem0-Inspired Scoped Fact Store Dossier

## Strategy Identity

This strategy represents mem0 as a productized memory service: scoped,
self-contained facts with vector storage, history, deduplication, optional
entity indexing, hybrid scoring, and explicit search APIs.

Primary evidence:

- `/Users/didi/develop/memoryresearch/mem0/mem0/memory/main.py:331`
  to `:358`
- `/Users/didi/develop/memoryresearch/mem0/mem0/memory/main.py:389`
  to `:456`
- `/Users/didi/develop/memoryresearch/mem0/mem0/memory/main.py:573`
  to `:705`
- `/Users/didi/develop/memoryresearch/mem0/mem0/memory/main.py:1126`
  to `:1237`
- `/Users/didi/develop/memoryresearch/mem0/mem0/memory/main.py:1343`
  to `:1499`
- `/Users/didi/develop/memoryresearch/mem0/mem0/utils/scoring.py:1`
  to `:121`
- `/Users/didi/develop/memoryresearch/mem0/mem0/configs/prompts.py:468`
  to `:535`

Evidence level: A.

Reason: source code shows the service composition, scope contract, add/search
flow, entity store behavior, hybrid scoring, and extraction prompt constraints.

## Original System Data Flow

```text
add(messages, user_id/agent_id/run_id)
-> validate scope
-> parse messages
-> optional LLM extraction into self-contained facts
-> dedup/link against recent and existing memories
-> embed facts
-> insert vector payloads
-> write history
-> upsert linked entities

search(query, filters)
-> validate scope filters
-> embed query
-> semantic overfetch
-> optional keyword search
-> optional entity boost
-> semantic-threshold gate
-> additive scoring
-> optional rerank
-> formatted facts
```

## Core Mechanisms

1. Scope is mandatory.

   Search requires at least one of `user_id`, `agent_id`, or `run_id`. This is
   not just metadata; it is the isolation boundary that prevents cross-user or
   cross-run leakage.

2. Memories are self-contained facts.

   The ADD extraction prompt asks for standalone, contextual factual statements
   and grounds relative dates to the observation date.

3. Existing memories guide dedup/linking.

   Existing memories are not used as extraction input. They are used for
   deduplication and linking, especially for related updates or continuations.

4. Vector payload plus side databases.

   The main memory is a vector payload. SQLite records history. Entity storage
   links extracted entities back to memory ids.

5. Hybrid scoring is additive but semantically gated.

   mem0 computes semantic scores, normalized BM25 scores, and entity boosts.
   However, candidates below the semantic threshold are excluded before the
   boosts are combined.

## Non-Omittable Mechanisms

The Amadeus prototype stops being mem0-inspired if it omits these:

- Every add/search operation is scoped by user/agent/run.
- Stored records are self-contained facts, not raw chat fragments.
- Records have ids, hashes or dedup keys, and history metadata.
- Retrieval starts from semantic candidates.
- BM25/entity/rerank signals are ranking signals, but low semantic-score
  candidates do not pass only because of keyword/entity boost.
- Search returns flat fact records, not a compiled prompt memory block.

## Omittable In The First Version

These can be deferred because fixed artifacts are already extracted:

- LLM extraction from raw messages.
- Full update/delete lifecycle.
- Provider-specific vector store integrations.
- Reranker provider implementation.
- Hosted platform API behavior.
- Entity extraction with an LLM, if deterministic entity tags are present in
  test artifacts.

## Minimal Prototype Definition

For fixed memory artifacts, the mem0 adapter should:

```text
1. Accept artifacts as already extracted fact candidates.
2. Require a scope field for indexing and search.
3. Normalize each fact into a self-contained text record.
4. Compute a hash/dedup key and preserve id/history metadata.
5. Build semantic candidates under the requested scope.
6. Apply optional BM25 and entity boosts only to semantic candidates.
7. Return ranked fact records plus scoring trace.
```

## Fidelity Checklist

- [ ] A query for user A never retrieves user B artifacts with the same text.
- [ ] Duplicate facts collapse or are linked through the dedup/history trace.
- [ ] Facts remain understandable without the original conversation turn.
- [ ] A low semantic-score candidate is filtered even when a keyword/entity
      boost exists.
- [ ] Entity boosts can reorder candidates that already passed semantic gating.
- [ ] Search output is a flat list of fact records with ids, scores, and
      metadata.
- [ ] The trace identifies scope filters, semantic scores, BM25 scores, entity
      boosts, and final score.

## Conclusion Boundary

If this prototype performs well, Amadeus can claim that scoped, self-contained
fact memory with semantic-first hybrid ranking is useful for the evaluated
tasks.

It cannot claim that mem0's extraction quality, provider integrations, hosted
service behavior, update/delete semantics, or reranker implementation are
validated until those lifecycle stages are added.

