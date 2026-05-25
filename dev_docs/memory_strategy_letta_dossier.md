# Letta-Inspired Core/Archival Boundary Dossier

## Strategy Identity

This strategy represents Letta's explicit boundary between core in-context
memory and external archival/recall memory.

Primary evidence:

- `/Users/didi/develop/memoryresearch/letta/letta/prompts/system_prompts/memgpt_chat.py:39`
  to `:56`
- `/Users/didi/develop/memoryresearch/letta/letta/functions/function_sets/base.py:164`
  to `:225`
- `/Users/didi/develop/memoryresearch/letta/letta/functions/function_sets/base.py:263`
  to `:280`
- `/Users/didi/develop/memoryresearch/letta/letta/functions/function_sets/base.py:311`
  to `:449`
- `/Users/didi/develop/memoryresearch/letta/letta/functions/function_sets/base.py:488`
  to `:517`
- `/Users/didi/develop/memoryresearch/letta/letta/schemas/memory.py:68`
  to `:173`
- `/Users/didi/develop/memoryresearch/letta/letta/schemas/memory.py:688`
  to `:830`
- `/Users/didi/develop/memoryresearch/letta/letta/services/agent_manager.py:1445`
  to `:1562`

Evidence level: A.

Reason: system prompt docs, memory tools, memory schema, render/compile logic,
and system prompt rebuild behavior all support the core/archival boundary.

## Original System Data Flow

```text
agent has core memory blocks
-> core blocks are compiled into the system prompt
-> core memory is always visible
-> archival memory lives outside immediate context
-> agent explicitly inserts/searches archival memory
-> recall memory searches conversation history
-> core edits update memory blocks
-> changed core memory triggers system prompt rebuild
```

## Core Mechanisms

1. Core memory is always in context.

   The system prompt states that core memory is inside the initial system
   instructions and always visible. There is no search function for core memory
   because it is already in context.

2. Archival memory is outside context.

   Archival memory is permanent and searchable, but the agent must explicitly
   search or retrieve it before it can use it.

3. Core memory is block-structured.

   Memory blocks render with labels, metadata, values, read-only markers, and
   character limits.

4. Edits are constrained tools.

   Core memory replacement requires exact content. Precise edit tools reject
   line-number artifacts and ambiguous replacements.

5. Prompt rebuild is an invariant.

   Changes to core memory should rebuild the system message; unrelated header
   changes should not flood recall storage.

## Non-Omittable Mechanisms

The Amadeus prototype stops being Letta-inspired if it omits these:

- Core memory is always injected before query-time retrieval.
- Archival memory is not automatically injected.
- Accessing archival memory requires an explicit search/retrieval step.
- Core and archival memory are trace-labeled separately.
- Core memory blocks have labels and size/permission metadata.
- Read-only blocks cannot be modified in lifecycle tests.
- A core memory edit flips a prompt-rebuild or compiled-context version marker.

## Omittable In The First Version

These can be deferred because fixed artifacts are used:

- Full agent tool loop.
- Recall memory over complete message history.
- Sleeptime/background memory editing.
- Database managers and passage services.
- Full patch parser behavior.
- Real system prompt message replacement.

## Minimal Prototype Definition

For fixed memory artifacts, the Letta adapter should:

```text
1. Partition artifacts into core blocks and archival records.
2. Always render core blocks into the injected context.
3. Keep archival records outside context until search is explicitly requested.
4. Search archival records only when the strategy's retrieval policy calls it.
5. Return core block ids, archival hit ids, and injection trace separately.
6. Support minimal edit simulation for core blocks in lifecycle tests.
```

For first-version fixed-artifact eval, the query policy can be deterministic:
for tasks marked "requires_archival_search", search archival; otherwise answer
from core plus current query. The policy choice must be recorded in the trace.

## Fidelity Checklist

- [ ] Core artifacts are present in the injected context for every case.
- [ ] Archival artifacts are absent unless an explicit search step occurs.
- [ ] A case requiring archival evidence fails or abstains if search is disabled.
- [ ] Core and archival injected ids are separated in the trace.
- [ ] Core block labels and character limits are preserved.
- [ ] Read-only blocks reject update attempts in lifecycle tests.
- [ ] Editing a core block changes a compiled-context version or rebuild flag.
- [ ] Search results return self-contained archival records with ids and
      timestamps.

## Conclusion Boundary

If this prototype performs well, Amadeus can claim that an explicit
always-visible core memory plus searched archival memory boundary is useful for
the evaluated tasks.

It cannot claim that Letta's full agent loop, database behavior, recall memory,
sleeptime editing, or production prompt rebuild implementation is validated
until those layers are added.

