# Amadeus resources

This file is the active resource index for interview delivery. Akashic remains the reference implementation; Amadeus should only migrate designs that support a runnable, verifiable resume project.

## Akashic reference entry points

- `../akashic-agent/agent/core/passive_turn.py`
  Passive pipeline, reasoner loop, context preparation, tool execution, commit, and outbound dispatch.

- `../akashic-agent/agent/core/proactive_turn.py`
  ProactiveTurnPipeline: gate, fetch, judge, resolve, deliver, ACK, and tick trace.

- `../akashic-agent/agent/core/drift_turn.py`
  DriftRunner design: scan, prepare, execute, finish, skill-driven background work.

- `../akashic-agent/proactive_v2/gateway.py`
  DataGateway design for alert/content/context prefetch.

- `../akashic-agent/proactive_v2/loop.py`
  Runtime composition for proactive loop, adaptive tick, presence, state, and outbound orchestration.

- `../akashic-agent/agent/scheduler.py` and `../akashic-agent/agent/tools/schedule.py`
  Scheduler job model, time parsing, persistent store, and schedule/list/cancel tools.

- `../akashic-agent/memory2/retriever.py`
  Retrieval quality reference: vector lane, keyword lane, RRF, injection budget, source tags, hotness.

- `../akashic-agent/eval/personamem/qa_runner.py` and `../akashic-agent/eval/longmemeval/qa_runner.py`
  Evaluation runner references for behavior cases, tool trace capture, timeout handling, and report payloads.

## Amadeus current code anchors

- `amadeus/runtime/passive.py`
  PassiveRuntime, phase execution, prompt render, provider call, tool loop, commit, and after-turn hook.

- `amadeus/app/bootstrap.py`
  App composition, real provider config, long-term memory setup, tool registry, plugin manager, and lifecycle start/close.

- `amadeus/memory/markdown.py`, `amadeus/memory/akashic.py`, `amadeus/memory/retriever.py`, and `amadeus/memory/ranking.py`
  Markdown memory, optimizer, long-term memory store, retrieval, RRF, source_ref evidence, and forgetting.

- `amadeus/context.py` and `amadeus/prompting/assembler.py`
  Prompt sections, context frame, dynamic context isolation, section disabling, and message envelope.

- `amadeus/tools/`
  Tool registry, executor, read-only file/message tools, recall_memory, and forget_memory.

- `amadeus/plugin/` and `amadeus/phase.py`
  Plugin loading, phase module ownership, sorting, rollback, and extension boundaries.

## Active delivery documents

- `docs/interview/resume-claim-gap-audit.md`
  Claim-by-claim map from resume wording to current evidence, gaps, and interview answer boundaries.

- `docs/interview/interview-delivery-roadmap.md`
  Dependency-ordered implementation route for passive confirmation, memory hardening, Evaluation, Telegram, scheduler, ProactiveLoop, and DriftRunner.

## External concepts worth using

- Evaluation should measure behavior: correct recall, correct source use, no context contamination, tool-loop stability, and proactive send/skip decisions.
- Outbound adapters should be replaceable: Telegram first, QQ later.
- Retrieval summaries are candidates, not original evidence. Source references must be fetchable when a factual answer depends on history.
