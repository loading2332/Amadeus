# Amadeus Memory Evaluation Workflow

## 1. Purpose

This document records the agreed workflow for evaluating memory-layer designs in
Amadeus.

The goal is not to copy one external project wholesale. The goal is to build an
evaluation base that lets Amadeus compare memory architecture ideas, understand
their failure modes, and migrate only the parts that are justified by evidence.

Reference sources:

- Memory Systems Map:
  `/Users/didi/develop/akashic-agent/tutorial/research/memory-systems-map.md`
- EverMemOS / EverOS paper:
  `https://arxiv.org/pdf/2601.02163v2`
- Public eval datasets:
  - `https://github.com/snap-research/locomo`
  - `https://github.com/xiaowu0162/LongMemEval-V2`
  - `https://github.com/bowen-upenn/PersonaMem`

## 2. Core Principle

The project should produce multi-dimensional evidence, not a single memory
leaderboard.

The intended outcome is:

```text
memory strategy dossiers
-> evidence-backed architecture prototypes
-> unified eval cases and traces
-> multi-dimensional scores
-> Amadeus-specific architecture decisions
```

The outcome should not be:

```text
pick the highest-scoring external project
-> copy its architecture into Amadeus
```

Different systems may be strongest at different layers: extraction, schema,
freshness, retrieval, injection, correction, auditability, cost, or latency.
Amadeus should use the eval results to decide which design ideas compose into a
consistent Amadeus memory architecture.

## 3. Hard Gates Before Running Scores

No memory strategy may enter benchmark runs until it has a dossier and fidelity
checklist.

The reason is simple: an `akashic-like`, `mem0-like`, or `EverMemOS-like`
prototype is not trustworthy unless we can prove which mechanisms it preserves
and which mechanisms it omits.

Each dossier must include:

```text
1. Strategy identity
   Name, source, paper/repo/source-code locations.

2. Original system data flow
   capture -> organize -> store -> retrieve -> inject -> update/correct.

3. Core mechanisms
   Why this strategy may work.

4. Non-omittable mechanisms
   Parts that would change the strategy's identity if removed.

5. Omittable mechanisms
   Parts the first prototype can defer.

6. Minimal prototype definition
   How Amadeus will implement this strategy for eval.

7. Fidelity checklist
   Behavioral checks proving the prototype preserves the important mechanism.

8. Conclusion boundary
   What benchmark results can and cannot claim.
```

## 4. Evidence Levels

Each dossier receives an evidence level.

```text
A-level evidence:
  At least two primary evidence types agree, such as paper, official README,
  key source code, official eval runner, or local tests.
  A-level strategies may enter first-batch prototypes.

B-level evidence:
  There is a paper or official README, but the source/eval path is incomplete
  or not fully inspected.
  B-level strategies may enter prototypes only with explicit low-confidence
  boundaries.

C-level evidence:
  Only second-hand summaries, blog posts, or impressions.
  C-level strategies do not enter benchmark runs.
```

Target evidence levels for the first batch:

```text
Akashic-inspired: A
mem0-inspired: A
memU-inspired: A
EverMemOS-inspired: B until EverCore source/eval runner is locally inspected
Letta-inspired: A
```

## 5. First-Batch Strategy Dossiers

The first batch is limited to five strategies.

```text
1. Akashic-inspired
   Markdown control plane + semantic working index + provenance + prompt
   injection by change frequency.

2. mem0-inspired scoped fact store
   Self-contained scoped facts, dedup/history, and retrieval service style.

3. memU-inspired summary index
   Category or summary-as-navigation, staged retrieval, and summary-to-item
   drilldown.

4. EverMemOS-inspired MemCell/MemScene
   Episodic memory cells, thematic scenes, profile, and reconstructive recall.

5. Letta-inspired core/archival boundary
   Core memory always in prompt, archival/recall memory accessed by search or
   tool boundary.
```

Dossier index:

```text
dev_docs/memory_strategy_dossiers_index.md
```

Individual dossiers:

```text
dev_docs/memory_strategy_akashic_dossier.md
dev_docs/memory_strategy_mem0_dossier.md
dev_docs/memory_strategy_memu_dossier.md
dev_docs/memory_strategy_evermemos_dossier.md
dev_docs/memory_strategy_letta_dossier.md
```

Deferred strategies:

```text
OpenViking-inspired context database
  Deferred because it is heavier and closer to a virtual context filesystem.

TencentDB-inspired L0-L3/offload
  Deferred because it overlaps with EverMemOS in layered memory and adds
  context offload, scheduler, and gateway concerns.

Standalone workflow/procedure memory
  Treated first as an eval capability surface, especially via LongMemEval-V2.
```

## 6. Eval Scope

The first implementation phase should support fixed memory artifacts and compare
memory use, not raw-conversation extraction.

This means:

```text
fixed memory artifacts
-> strategy-specific organization/indexing
-> retrieval
-> conflict/freshness behavior
-> injection formatting
-> final answer scoring
```

It intentionally does not yet test:

```text
raw conversation
-> automatic memory extraction
-> write/consolidation lifecycle
-> long-running correction and forgetting
```

This first phase should be called Memory Use Eval rather than Retrieval Eval,
because it tests more than lookup. It tests organization, conflict/freshness,
retrieval, injection, and end-to-end use.

The full Memory Eval Suite can later add:

```text
capture/extraction
schema validity
consolidation
correction/forgetting
lifecycle/freshness lag
cost/latency/observability
offload recoverability
```

## 7. Public Dataset Roles

The public datasets should be treated as capability surfaces, not as one shared
memory score.

```text
PersonaMem
  Best first fit for user profile, dynamic preference, preference evolution,
  and personalized response quality. Main score is accuracy.

LoCoMo
  Best fit for long conversation, evidence recall, event/timeline memory, and
  multi-hop long-dialogue QA. Typical outputs include prediction, F1, and
  evidence recall.

LongMemEval-V2
  Best fit for project/workflow memory, experienced-colleague behavior,
  environment state, gotchas, premise awareness, and latency-aware scoring.

EverMemOS / EverOS
  Treated first as a strategy and runner reference. It is not the only standard
  answer for Amadeus.
```

Amadeus should also maintain an Amadeus golden set for real project constraints,
collaboration preferences, teaching style, correction cases, and workflow
memory.

## 8. Official Benchmarks And Amadeus Harness

Official benchmarks should be used, but they should not be the only execution
layer for architecture comparison.

A public benchmark contains several separable parts:

```text
dataset
task protocol
official runner
scorer
report format
```

Amadeus should reuse the dataset, task protocol, and scorer semantics where
possible. The official runner should first be used for smoke runs, not as the
final architecture comparison layer.

Official benchmark smoke runs:

```text
Run 3-5 examples from each public benchmark through the official path.
Confirm how data loads, what the runner expects, which metrics are produced,
and what output files are written.
Do not use these smoke runs to decide which Amadeus memory strategy is better.
```

Amadeus adapted harness runs:

```text
Use thin dataset adapters.
Preserve the dataset-native sample in native_payload.
Route every case through one MemoryStrategyAdapter interface.
Save Amadeus traces in addition to any official-compatible score.
```

The purpose of the Amadeus harness is to avoid an N x M glue-code explosion:

```text
without harness:
  every dataset x every memory strategy needs its own runner code

with harness:
  every dataset has one thin adapter
  every memory strategy has one strategy adapter
  the harness composes them
```

The harness must not flatten away dataset-specific information. A common eval
case should contain only the runner-required common fields and a full
`native_payload` copy of the original sample.

The recommended contract shape is:

```text
CommonEvalCase
  dataset_name
  group_id, optional
  case_id
  task_type
  query
  gold_answer, optional
  gold_evidence_ids, optional
  memory_artifacts, optional
  scoring_spec
  native_payload
```

For lifecycle runs, `CommonEvalCase` sits inside `MemoryEvalGroup`:

```text
MemoryEvalGroup
  dataset_name
  group_id
  memory_artifacts
  cases
  native_payload
```

The group owns the memory artifacts. The cases own questions, answers, scoring
specs, and native question payloads. This avoids re-ingesting the same
conversation or context for every question.

This keeps benchmark semantics intact while giving Amadeus a consistent place
to compare memory strategies and inspect failure traces.

## 9. Required Eval Trace

Every run should save traces, not only aggregate scores.

Minimum trace fields:

```text
dataset_name
group_id
case_id
task_type
query
gold_answer
gold_evidence_ids
memory_strategy
retrieved_memory_ids
retrieval_scores
injected_context
final_answer
score
score_details
latency_ms
token_count
cost_estimate
```

These traces are necessary because the important question is not only whether a
strategy wins, but why it wins or fails.

## 10. Next Step

The Strategy Dossiers phase is complete for the first batch. The current gate
is the eval base.

After the five first-batch dossiers are accepted, the next concrete task is to
build the evaluation base:

```text
1. Run official benchmark smoke runs for LoCoMo, LongMemEval-V2, and PersonaMem.
2. Record each benchmark's native input shape, runner command, metrics, and
   output files.
3. Define Amadeus CommonEvalCase, MemoryEvalGroup, and MemoryStrategyAdapter
   contracts.
4. Implement thin dataset adapters that preserve native_payload.
5. Implement grouped dataset loaders for lifecycle eval.
6. Implement one tracer-bullet memory strategy adapter.
7. Persist MemoryEvalTrace records to JSONL.
8. Add one tiny golden set.
9. Run an end-to-end smoke run through the Amadeus harness.
```

The first implementation milestone should prove the harness loop, not maximize
scores.

Current implementation note:

```text
dev_docs/memory_eval_base.md records the current harness slices.
amadeus/memory_eval/ contains the CommonEvalCase, MemoryEvalGroup, dataset
adapter, strategy adapter, approximate scorer, JSONL trace, and trace
contracts.
```

Current runnable grouped eval command:

```text
python -m amadeus.memory_eval.run \
  --dataset locomo \
  --benchmark-root memorybenchmarks \
  --strategy lexical \
  --group-limit 1 \
  --output /tmp/amadeus-locomo-lexical.jsonl
```

The current run report includes scored_count, mean_score, and mean_score_details.
These scores are approximate local harness scores, not official leaderboard
scores yet.
