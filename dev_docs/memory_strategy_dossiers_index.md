# Memory Strategy Dossiers Index

This index records the first batch of memory strategies that are allowed to
enter Amadeus memory evaluation work.

The goal of a dossier is not to describe a project in general. The goal is to
define what Amadeus will actually prototype and test, with enough evidence that
the prototype is not just a vague impression of the source system.

## Gate Table

| Strategy | Dossier | Evidence | First eval status | Prototype identity |
| --- | --- | --- | --- | --- |
| Akashic-inspired | `memory_strategy_akashic_dossier.md` | A | Admit | Markdown control plane plus semantic working index, provenance, typed injection |
| mem0-inspired scoped fact store | `memory_strategy_mem0_dossier.md` | A | Admit | Scoped self-contained facts, history/dedup, hybrid ranking |
| memU-inspired summary index | `memory_strategy_memu_dossier.md` | A | Admit | Resource -> item -> category, summary navigation, staged retrieval |
| EverMemOS-inspired MemCell/MemScene | `memory_strategy_evermemos_dossier.md` | B | Admit as paper-aligned exploratory prototype | MemCells, MemScenes, profile update, reconstructive recollection |
| Letta-inspired core/archival boundary | `memory_strategy_letta_dossier.md` | A | Admit | Core memory always in prompt, archival memory only via explicit search |

## Evidence Rule

A strategy can enter benchmark implementation only when the dossier names:

```text
source evidence
core mechanisms
non-omittable mechanisms
first-version omissions
minimal fixed-artifact prototype
fidelity checklist
conclusion boundary
```

This prevents a later eval run from saying "mem0 wins" or "Akashic loses" when
the implemented adapter only represented a loose caricature of the source
system.

## Shared First-Version Eval Contract

All five dossiers target the same first-version evaluation shape:

```text
fixed memory artifacts
-> strategy-specific organization/indexing
-> retrieval
-> conflict/freshness behavior
-> injection formatting
-> final answer scoring
```

This is Memory Use Eval, not full lifecycle eval. The first version does not
judge raw conversation extraction, background consolidation, or forgetting
unless a fidelity checklist explicitly marks that behavior as required for the
strategy's identity.

## Strategy Adapter Trace Requirements

Every strategy adapter must produce a comparable trace:

```text
strategy_name
evidence_level
artifact_ids_seen
artifact_ids_indexed
retrieval_stages
retrieved_memory_ids
injected_memory_ids
injected_context
freshness_or_conflict_decisions
omitted_capabilities
```

The trace is part of the benchmark output. Without it, a score cannot explain
whether a failure came from organization, retrieval, injection, or final answer
use.

## Upgrade Conditions

EverMemOS starts at B-level because this pass inspected the arXiv abstract and
official repo README, but did not locally inspect the EverCore source and
evaluation runner. It can be upgraded to A-level after a dedicated source pass
confirms the implementation and benchmark runner details.

Deferred strategies remain outside the first batch until they get their own
dossiers:

```text
OpenViking-inspired context database
TencentDB-inspired L0-L3/offload
Standalone workflow/procedure memory prototype
```
