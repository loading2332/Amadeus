# EverOS Evaluation Framework Notes

Source inspected:

```text
https://github.com/EverMind-AI/EverOS/tree/29d555c6e94de3630f314c1f594fc1801377ff5a/methods/EverCore/evaluation
```

## Why It Matters

EverOS includes an evaluation framework for memory systems. It is directly
relevant to Amadeus because it evaluates LoCoMo, LongMemEval, and PersonaMem
through one modular pipeline.

The important lesson is not to copy the code. The useful design signal is its
stage boundary:

```text
dataset converter
-> standard conversation + QA model
-> add
-> search
-> answer
-> evaluate
```

## Core Shape

EverOS standardizes data into:

```text
Message
Conversation
QAPair
Dataset
SearchResult
AnswerResult
EvaluationResult
```

The pipeline is four stages:

```text
1. Add
   Ingest conversations and build memory/index state.

2. Search
   For each QAPair, retrieve relevant memory.

3. Answer
   Build context from search results and call answer model.

4. Evaluate
   Score answers with exact match, LLM judge, or hybrid evaluator.
```

This is stronger than a flat "run each case independently" harness because
memory systems usually ingest a conversation once and answer many questions
against that same memory state.

## Dataset Conversion

EverOS keeps LoCoMo as the canonical internal shape.

```text
LoCoMo
  Native format, no conversion.

LongMemEval
  Converted into LoCoMo-style conversation + QA entries.

PersonaMem
  Converted into LoCoMo-style conversation + QA entries.
```

The PersonaMem converter groups questions by:

```text
(shared_context_id, end_index_in_shared_context)
```

That avoids rebuilding the same long context repeatedly for every question.

## Adapter Interface

EverOS adapters expose:

```text
prepare(conversations)
add(conversations) -> index
search(query, conversation_id, index) -> SearchResult
answer(query, context, conversation_id) -> str
build_lazy_index(conversations, output_dir)
```

This is different from Amadeus's current first slice:

```text
CommonEvalCase
-> strategy.run(case)
-> MemoryEvalTrace
```

The Amadeus shape is good for first fixed-artifact smoke tests, but it is too
case-centric for full lifecycle evaluation.

## Evaluators

EverOS supports:

```text
exact_match
  Useful for PersonaMem multiple-choice answers.

llm_judge
  Useful for open-ended LoCoMo and LongMemEval answers.

hybrid
  Routes multiple-choice questions to exact match and open-ended questions to
  LLM judge.
```

This matches Amadeus's earlier concern that public benchmarks do not emit one
universal score. Scoring must depend on task type.

## What Amadeus Should Borrow

Borrow:

- Conversation-level add stage.
- Question-level search/answer/evaluate stages.
- Dataset conversion or grouping before strategy execution.
- Checkpointable stage outputs.
- Separate evaluator registry by task type.
- Hybrid evaluation for PersonaMem-style multiple choice and open QA.

Do not blindly borrow:

- Online API adapter assumptions.
- EverCore-specific MemCell extraction implementation.
- OpenRouter/GPT-4.1-mini answer model default.
- Its exact config directory layout.
- Its assumption that all non-LoCoMo datasets should be converted to LoCoMo
  before Amadeus sees them.

## Impact On Current Amadeus Harness

Current Amadeus implementation:

```text
official sample
-> CommonEvalCase
-> MemoryStrategyAdapter.run(case)
-> MemoryEvalTrace
```

This is acceptable for fixed-artifact Memory Use Eval smoke tests.

Amadeus now has a grouped dataset view:

```text
MemoryEvalDataset
  dataset_name
  groups: tuple[MemoryEvalGroup, ...]

MemoryEvalGroup
  group_id
  memory_artifacts
  cases: tuple[CommonEvalCase, ...]
  native_payload
```

The current strategy execution path is:

```text
strategy.prepare_group(group)
strategy.run(case)
MemoryEvalTrace(...)
```

This preserves the current case trace while avoiding repeated ingestion of the
same conversation/context. A later scorer/answer-model slice can split
`strategy.run(case)` into explicit retrieve, inject, answer, and evaluate
stages if that improves traceability.

## Recommendation

Keep the current Amadeus first slice. It is useful and already tested.

The EverOS comparison changed Amadeus in one specific way: it added a grouping
layer above `CommonEvalCase` so Amadeus can support both:

```text
case-level smoke inspection
conversation/group-level memory lifecycle evaluation
```
