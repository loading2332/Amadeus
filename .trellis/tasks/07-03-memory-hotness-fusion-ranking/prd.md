# Implement memory hotness fusion ranking

## Goal

Implement real memory hotness fusion in Amadeus retrieval ranking so the interview claim "combines reinforcement, time decay, and emotional_weight" is backed by production behavior and focused verification.

This supports the resume claim for an Akashic-inspired memory system by making ranking explainable beyond semantic/lexical match: frequently reinforced, recent, emotionally salient memories should receive a bounded hotness signal that can influence ordering when relevance is otherwise comparable.

## Confirmed Facts

- Current Amadeus ranking uses vector score, lexical score, RRF, and a tiny `reinforcement_boost` tie-break. It does not combine reinforcement, time decay, and emotional_weight into the main score. Evidence: `amadeus/memory/ranking.py`.
- `MemoryStore` already persists `reinforcement`, `emotional_weight`, `created_at`, and `updated_at`, but retrieval rows do not currently use `emotional_weight` or age-based decay as a scored signal. Evidence: `amadeus/memory/store.py`.
- Existing interview docs explicitly say `emotional_weight` and time decay are not implemented and must not be claimed yet. Evidence: `docs/interview/resume-claim-gap-audit.md`.
- Akashic reference has a hotness-style design using reinforcement, updated_at age, half-life, and emotional_weight to produce a bounded score blended with semantic relevance. Amadeus should migrate the design idea, not copy Akashic's full store or sqlite-vec structure.
- Akashic computes hotness as frequency times exponential time decay. `emotional_weight` increases the effective half-life, so emotionally important memories decay more slowly. Evidence: `../akashic-agent/memory2/store.py::_hotness_score`.
- Akashic blends hotness into vector retrieval scores with `final = (1 - hotness_alpha) * semantic + hotness_alpha * hotness`; default wiring uses `hotness_alpha=0.20`. Evidence: `../akashic-agent/memory2/store.py::vector_search` and `../akashic-agent/plugins/default_memory/engine.py`.
- Akashic exposes `_score_debug` with semantic, hotness, and final score, and stores `_reinforcement`, `_updated_at`, and `_emotional_weight` inside result metadata. Amadeus should expose equivalent trace fields through `MemoryRecord.signals`.
- Product decision: Amadeus should follow the Akashic default for RAG/vector retrieval: final vector-lane relevance is `0.8 * semantic + 0.2 * hotness`, while still requiring the semantic score to pass the existing relevance threshold before hotness can influence ranking.

## Requirements

- Add a production ranking signal that combines:
  - reinforcement frequency;
  - time decay based on item recency, preferably `updated_at`;
  - emotional_weight as a bounded modifier of decay or salience.
- Blend hotness with retrieval relevance in a bounded, explainable way. Stronger direct semantic/lexical matches must not be overwhelmed by hotness alone.
- Use Akashic's default blend for vector-lane scoring: `final = 0.8 * semantic + 0.2 * hotness`.
- Apply the existing vector relevance threshold before hotness fusion so unrelated memories cannot enter retrieval only because they are hot.
- Preserve existing retrieval behavior for source references, memory types, time filters, scope fallback, and context injection.
- Expose the hotness components in `MemoryRecord.signals` / trace so interview evidence can show why an item ranked higher.
- Add focused tests proving:
  - reinforcement still matters;
  - recent items receive higher hotness than stale comparable items;
  - higher emotional_weight affects ranking or hotness under otherwise comparable conditions;
  - unrelated but "hot" memories do not outrank clearly relevant memories;
  - trace output includes hotness component values.
- Update interview documentation to remove the current gap once implementation and verification pass.

## Acceptance Criteria

- [x] A deterministic unit test proves hotness fusion can change ordering between otherwise comparable memories.
- [x] A deterministic unit test proves semantic/lexical relevance remains the primary guardrail.
- [x] Retrieval trace includes reinforcement, recency/time-decay, emotional_weight, hotness score, and final ranking score or equivalent fields.
- [x] Existing focused memory tests still pass.
- [x] Documentation under `docs/interview/` reflects the new implemented status and keeps any remaining limitations explicit.

## Out of Scope

- Do not migrate sqlite-vec as part of this task.
- Do not build a memory dashboard or memory audit report UI.
- Do not change LLM extraction prompts unless required to preserve or populate emotional_weight correctly.

## Resolved Decisions

- Hotness fusion should affect normal RAG/vector retrieval in Amadeus using the Akashic-style `0.8 * semantic + 0.2 * hotness` blend.
