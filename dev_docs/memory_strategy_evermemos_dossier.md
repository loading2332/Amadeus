# EverMemOS-Inspired MemCell/MemScene Dossier

## Strategy Identity

This strategy represents the EverMemOS paper's self-organizing memory concept,
reduced to a fixed-artifact Amadeus prototype.

Primary evidence:

- Paper: `https://arxiv.org/abs/2601.02163`
- User-supplied PDF version: `https://arxiv.org/pdf/2601.02163v2`
- Paper code link: `https://github.com/EverMind-AI/EverMemOS`
- Official repository README checked live under:
  `https://github.com/EverMind-AI/EverOS`

Evidence level: B.

Reason: the paper and official README agree on the high-level design:
MemCells, MemScenes, profile updates, reconstructive recollection, EverCore,
and benchmarks such as LoCoMo, LongMemEval, and PersonaMem. This pass did not
locally inspect the EverCore source code or evaluation runner, so Amadeus should
treat the first prototype as paper-aligned rather than source-faithful.

Upgrade condition: inspect `methods/EverCore` and the evaluation CLI from the
official repo, then update this dossier to A-level if the source behavior
matches the paper abstraction.

## Original System Data Flow

Based on the paper abstract and official repository description:

```text
dialogue stream
-> episodic trace formation
-> MemCell generation
   - episode/narrative trace
   - atomic facts
   - time-bounded foresight signals
   - metadata
-> semantic consolidation
-> MemScene clustering/grouping
-> profile update
-> reconstructive recollection
-> compose necessary and sufficient context
-> downstream reasoning
```

## Core Mechanisms

1. MemCell as an episodic memory unit.

   The unit is richer than a flat fact. It should carry episode-level context,
   atomic facts, temporal/foresight signals, and metadata.

2. MemScene as thematic consolidation.

   Related MemCells are grouped into coherent scenes. A scene is not just a
   search result list; it is an organized memory structure that can support
   reconstruction.

3. Profile is updated from consolidated memory.

   Stable user state should be distilled from accumulated cells/scenes rather
   than only appended as isolated facts.

4. Reconstructive recollection.

   Retrieval should select scenes/cells/profile and compose enough context for
   reasoning. The target is not just top-k fact recall.

5. Conflict and freshness matter.

   The paper frames the system around evolving user state and conflict
   resolution. The prototype must preserve recency/freshness behavior at least
   in traceable form.

## Non-Omittable Mechanisms

The Amadeus prototype stops being EverMemOS-inspired if it omits these:

- Memory artifacts are represented as MemCells, not only flat facts.
- Related cells are grouped into MemScenes.
- Scene selection happens before or alongside cell selection.
- Profile context is a separate layer from episodic cells.
- Recollection composes a context from scenes, cells, and profile.
- Trace exposes which scenes and cells contributed to the final context.
- Freshness/conflict decisions are explicit when newer and older cells disagree.

## Omittable In The First Version

These can be deferred because this is fixed-artifact Memory Use Eval:

- Raw dialogue-to-MemCell extraction.
- Online clustering implementation identical to EverCore.
- Full foresight signal generation.
- Agentic multi-step retrieval loop exactly matching the paper.
- Production API/server behavior.
- Official benchmark runner reproduction.

These omissions are more serious here than in A-level dossiers. Every result
must be labeled as "EverMemOS-inspired, paper-aligned prototype."

## Minimal Prototype Definition

For fixed memory artifacts, the EverMemOS adapter should:

```text
1. Convert each artifact into a MemCell-like object:
   id, episode_text, atomic_facts, timestamp, metadata, source_ref.
2. Group cells into MemScenes by provided topic/person/project labels or a
   deterministic similarity proxy.
3. Build a profile layer from stable profile artifacts and scene summaries.
4. For each query, select relevant scenes first.
5. Retrieve cells within selected scenes.
6. Resolve conflicts by recency and explicit source priority rules.
7. Compose a reconstructive context with profile, scene summaries, and selected
   cells.
8. Return selected scenes, selected cells, profile fragments, and conflict trace.
```

## Fidelity Checklist

- [ ] A multi-hop answer can combine multiple cells inside the same scene.
- [ ] Scene summary alone is not treated as sufficient when cell-level evidence
      is required.
- [ ] Stable profile context is separate from episodic cell context.
- [ ] Newer conflicting cells can override or qualify older profile statements.
- [ ] The trace names selected MemScenes and selected MemCells.
- [ ] Reconstructed context includes the reason each section was selected.
- [ ] If a query crosses topics, the adapter can select multiple scenes.
- [ ] The result report labels the strategy as B-level until source inspection
      upgrades it.

## Conclusion Boundary

If this prototype performs well, Amadeus can claim that paper-aligned MemCell
and MemScene organization is promising for the evaluated tasks.

It cannot claim EverMemOS/EverCore reproduction, benchmark parity, or official
SOTA comparability until the official source and runner are inspected and the
adapter is upgraded to A-level.
