# Memory Eval Base

This document records the first implementation slices of the Amadeus memory
evaluation base.

## Goal

Build a thin harness that lets Amadeus compare memory strategies without
rewriting one runner per dataset per strategy.

The first slice proved this loop:

```text
official benchmark sample
-> CommonEvalCase
-> MemoryStrategyAdapter
-> MemoryEvalTrace
```

The second slice added the grouped lifecycle loop:

```text
official benchmark conversation/context/haystack
-> MemoryEvalGroup(memory_artifacts, cases)
-> strategy.prepare_group(group), when supported
-> MemoryStrategyAdapter.run(case) for each question
-> MemoryEvalTrace(group_id, retrieved ids, injected context, answer)
```

This lets Amadeus ingest a shared memory state once and evaluate multiple
questions against that state. It does not yet call an answer LLM, download large
external data, or compute official aggregate scores.

## Current Code Boundary

Implementation lives under:

```text
amadeus/memory_eval/
```

Current modules:

```text
contracts.py
  CommonEvalCase, MemoryArtifact, MemoryEvalGroup, MemoryEvalDataset,
  MemoryStrategyResult, MemoryEvalTrace, MemoryStrategyAdapter.

harness.py
  run_memory_use_case(case, strategy), which captures strategy output and wraps
  it into a trace.

  run_memory_use_group(group, strategy), which calls strategy.prepare_group once
  when the strategy supports group-level preparation, then runs each case and
  records the group_id plus the artifact ids indexed for the group.

datasets/locomo.py
  Reads official LoCoMo `data/locomo10.json` and emits QA cases with dialogue
  turn artifacts. Also emits one MemoryEvalGroup per conversation sample.

datasets/personamem.py
  Reads PersonaMem `questions_*.csv` and `shared_contexts_*.jsonl` style files,
  then slices shared context by `end_index_in_shared_context`. Also groups
  questions by `(shared_context_id, end_index_in_shared_context)`, which is the
  shared context slice that should be ingested once.

datasets/longmemeval_v2.py
  Reads LongMemEval-V2 runtime JSON files: questions, haystack, trajectories.
  Also emits a conservative one-question-per-haystack MemoryEvalGroup. This can
  later be optimized if prepared data shows multiple questions share identical
  haystacks.

strategies/noop.py
  A no-op strategy adapter used to prove the harness trace shape.

strategies/lexical.py
  A group-aware lexical overlap baseline. It is not a target memory architecture;
  it is a calibration strategy for proving grouped ingestion, retrieval ids,
  injected context, and JSONL trace output.

trace_io.py
  Writes and reads MemoryEvalTrace records as JSONL, including scoring_spec and
  score_details.

scoring.py
  Computes first-pass approximate per-trace scores and aggregate score summaries.
  Current scorers cover LoCoMo-style answer F1 plus evidence recall,
  PersonaMem-style multiple-choice accuracy, and a basic answer F1 fallback.

run.py
  CLI and report builder for running grouped eval traces with a selected
  strategy. The first supported strategy is lexical. It writes scored JSONL
  traces and reports aggregate score summaries.

smoke.py
  CLI and report builder for inspecting benchmark case shape without running
  answer models or official scorers.

prepare.py
  CLI and status builder for checking whether benchmark data files are ready
  locally, and for reporting the official preparation commands when they are
  missing.
```

## Benchmark Repository State

The three public benchmark repositories are currently cloned under:

```text
memorybenchmarks/locomo
memorybenchmarks/LongMemEval-V2
memorybenchmarks/PersonaMem
```

They are nested git repositories. Amadeus currently sees `memorybenchmarks/` as
an untracked directory. Before committing, choose whether these should be local
ignored dependencies, git submodules, or vendored source.

## Native Benchmark Findings

LoCoMo:

```text
data/locomo10.json is included in the repo.
Each sample has conversation sessions and `qa` annotations.
QA scoring uses category-specific F1/selection logic and optional evidence
recall when prediction context ids are present.
```

PersonaMem:

```text
The official repo documents HuggingFace data files:
questions_{32k,128k,1M}.csv and shared_contexts_{32k,128k,1M}.jsonl.
The cloned repo itself does not include those large benchmark files.
Scoring is multiple-choice accuracy extracted from model response.
```

LongMemEval-V2:

```text
The repo includes public data download/prepare scripts, but not the prepared
dataset by default.
The harness expects runtime questions, haystack, and trajectories files.
Memory modules implement insert(trajectory) and query(question, image).
Outputs include per-run results and aggregated_metrics.json in official runs.
```

## First-Slice Tradeoff

The base intentionally uses plain Python dataclasses and standard-library
parsers. This keeps Amadeus independent from benchmark-specific dependencies
such as torch, datasets, OpenAI clients, or pandas while the adapter contract is
still forming.

The cost is that the first adapter pass only captures the minimum shape needed
for Memory Use Eval. Official scorer parity still needs a second pass.

## Group-Level Harness Tradeoff

`CommonEvalCase` remains supported because it is the simplest shape for smoke
inspection and fixed-artifact debugging.

`MemoryEvalGroup` is the serious lifecycle shape:

```text
MemoryEvalGroup
  dataset_name
  group_id
  memory_artifacts
  cases
  native_payload
```

Grouped cases intentionally do not duplicate `memory_artifacts`. The artifacts
live on the group so a strategy can index them once in `prepare_group(group)`.

The harness has a compatibility fallback:

```text
strategy has prepare_group:
  prepare_group(group)
  run(case_without_group_artifacts) for each case

strategy has only run(case):
  run(case_with_group_artifacts) for each case
```

This keeps old case-level strategies usable while making repeated ingestion
visible in traces. The tradeoff is that case-only strategies are convenient but
less lifecycle-accurate; group-aware strategies are the target for real memory
architecture comparisons.

## Scoring Boundary

The current scorer layer is intentionally approximate. It is good enough for
early local comparisons and failure analysis, but it is not yet an official
leaderboard scorer.

Current score fields:

```text
MemoryEvalTrace.score
  Primary scalar score for quick aggregation.

MemoryEvalTrace.score_details
  Extra metrics and scorer identity, for example answer_f1, exact_match,
  evidence_recall, accuracy, and scorer.
```

Current scorer semantics:

```text
LoCoMo:
  Primary score = normalized token F1 between final_answer and gold_answer.
  score_details includes exact_match and evidence_recall.

PersonaMem:
  Primary score = multiple-choice accuracy, using option-letter extraction
  similar to the official inference script.

LongMemEval-V2 and fallback:
  Primary score = basic normalized answer F1.
```

Important limitation:

```text
The current lexical baseline retrieves and injects memory but does not call an
answer model, so its final_answer is usually empty. Retrieval quality can still
be inspected via retrieved_memory_ids, retrieval_scores, injected_context, and
evidence_recall, but answer_f1 will remain low until an answer stage is added.
```

Official scorer parity remains a later phase.

## Commands

The next slice should add a CLI smoke command:

```text
python -m amadeus.memory_eval.smoke --dataset locomo --limit 3
python -m amadeus.memory_eval.smoke --dataset personamem --limit 3
python -m amadeus.memory_eval.smoke --dataset longmemeval_v2 --limit 3
```

For datasets whose official files are missing locally, the command should print
a structured "data missing" report with the official preparation command rather
than failing opaquely.

Implemented smoke command:

```text
python -m amadeus.memory_eval.smoke \
  --dataset locomo \
  --benchmark-root memorybenchmarks \
  --limit 3
```

Supported dataset names:

```text
locomo
personamem
longmemeval_v2
```

Current observed local status:

```text
locomo: ok, because data/locomo10.json is included in the clone.
personamem: missing_data until HuggingFace question/context files are present.
longmemeval_v2: missing_data until the official data preparation flow
materializes runtime question/haystack/trajectory files.
```

Data preparation status command:

```text
python -m amadeus.memory_eval.prepare \
  --dataset personamem \
  --benchmark-root memorybenchmarks
```

This command does not download data. It reports:

```text
dataset
status
ready_for_smoke
ready_for_official_run
required_paths
missing_paths
prepare_commands
notes
```

The separation is intentional:

```text
prepare.py = are the local files ready, and how do we prepare them?
smoke.py   = if ready, what case shape does the adapter emit?
run.py     = if ready, run grouped strategy eval and write JSONL traces
```

Do not hide data downloads inside smoke runs. Downloading benchmark data should
remain an explicit step because PersonaMem and LongMemEval-V2 can involve large
files and external dataset terms.

## EverOS Evaluation Framework Reference

EverOS also has an evaluation framework:

```text
https://github.com/EverMind-AI/EverOS/tree/29d555c6e94de3630f314c1f594fc1801377ff5a/methods/EverCore/evaluation
```

Notes from inspection are recorded in:

```text
dev_docs/everos_eval_framework_notes.md
```

The key takeaway is that EverOS separates conversation-level `add` from
question-level `search -> answer -> evaluate`. Amadeus's case-level smoke
harness stays, and the grouped dataset view above `CommonEvalCase` is now
implemented.

Implemented group loaders:

```text
load_locomo_groups(path, limit=None)
load_personamem_groups(questions_path, contexts_path, limit=None)
load_longmemeval_v2_groups(questions_path, haystack_path, trajectories_path, limit=None)
```

Implemented grouped trace command:

```text
python -m amadeus.memory_eval.run \
  --dataset locomo \
  --benchmark-root memorybenchmarks \
  --strategy lexical \
  --group-limit 1 \
  --output /tmp/amadeus-locomo-lexical.jsonl
```

The command report includes:

```text
dataset
strategy
status
group_count
trace_count
output_path
group_ids
scores.mean_score
scores.mean_score_details
```

Next serious lifecycle slice:

```text
1. Add an answer stage so retrieval/injection can produce final_answer.
2. Add an Amadeus golden set for user-profile + project-collaboration memory.
3. Add the first real strategy adapter behind prepare_group/run.
4. Upgrade approximate scorers toward official scorer parity.
```
