# Directory Structure

> Backend organization conventions observed in Amadeus.

---

## Overview

Amadeus is a single Python package under `amadeus/`, with tests mirrored under
`tests/`. Keep changes inside the smallest module that owns the behavior, and
prefer vertical slices that expose runnable behavior, traces, tests, or evals.

Primary examples:

- CLI and app composition: `amadeus/app/cli.py`, `amadeus/app/bootstrap.py`.
- Passive runtime pipeline: `amadeus/runtime/passive.py`, `amadeus/runtime/reasoner.py`, `amadeus/runtime/before_turn.py`, `amadeus/runtime/after_turn.py`.
- Memory contracts and implementations: `amadeus/memory/engine.py`, `amadeus/memory/store.py`, `amadeus/memory/retriever.py`, `amadeus/memory/memorizer.py`, `amadeus/memory/post_response_worker.py`.
- Tools: `amadeus/tools/base.py`, `amadeus/tools/executor.py`, `amadeus/tools/defaults.py`, `amadeus/tools/recall_memory.py`, `amadeus/tools/forget_memory.py`.
- Evaluation: `amadeus/evaluation/cases.py`, `amadeus/evaluation/evaluators.py`, `amadeus/evaluation/memory_recall_runner.py`, `amadeus/evaluation/memory_quality_runner.py`.
- Plugin host: `amadeus/plugin/manager.py`, `amadeus/plugin/registry.py`, `amadeus/plugin/types.py`.

## Module Organization

- Put public app assembly and CLI entry points in `amadeus/app/`.
- Keep turn lifecycle orchestration in `amadeus/runtime/`; runtime modules should depend on typed contracts and phase modules, not directly on storage internals.
- Put memory data contracts in `amadeus/memory/engine.py`; implementations and helpers live beside the contract in `amadeus/memory/`.
- Put user-facing or model-callable tool behavior in `amadeus/tools/`; tool code should return `ToolResult` and observable `ToolTrace` through `ToolExecutor`.
- Put product evaluation schemas, sync code, evaluators, and runners in `amadeus/evaluation/`; canonical case files live under `tests/evaluation/cases/`.
- Mirror package areas in tests: `amadeus/memory/*` has focused tests under `tests/memory/`, runtime under `tests/runtime/`, tools under `tests/tools/`, evaluation under `tests/evaluation/`.

## Boundary Rules

- Proactive code must not talk directly to Telegram. It must go through an outbound boundary such as `OutboundPort`.
- Proactive code must not read memory storage directly. It must go through `MemoryEngine`, memory profile APIs, or explicit context contracts.
- Scheduler code must not become an ad hoc LLM loop. It should trigger an agent/runtime entry or an outbound boundary.
- Evaluation should verify public behavior and recorded traces before reaching into private helper details.
- Akashic is a read-only reference under `../akashic-agent`; migrate contracts and lifecycle ideas, not directory structure.

## Naming Conventions

- Use explicit nouns for boundary types: `MemoryEngine`, `MemoryWriteRequest`, `PassiveTurnResult`, `ToolTrace`.
- Use runner names that state the behavior being evaluated, such as `memory_recall_runner.py` and `memory_quality_runner.py`.
- Test files should name the public module or behavior under test: `tests/evaluation/test_memory_quality_runner.py`, `tests/memory/test_memory_post_response_worker.py`.
- Keep fixture case files versioned by behavior suite, for example `memory_recall_v1.yaml` and `memory_quality_v1.yaml`.

## Common Mistakes

- Do not add top-level feature directories when an existing package owns the behavior.
- Do not bypass the runtime or memory boundary to make a demo pass quickly.
- Do not put interview evidence only in docs; each resume claim needs code evidence plus a runnable test, smoke, or eval case.
