# Resume claim gap audit

This audit maps the current resume description to Amadeus code evidence and the work still needed before the claim is safe in an interview.

## Current safe claims

| Resume claim | Current evidence | Interview wording |
| --- | --- | --- |
| AgentCore passive flow prepares context, renders prompt, reasons, and commits state | `amadeus/runtime.py`, `amadeus/before_turn.py`, `amadeus/prompt_render.py`, `amadeus/after_reasoning.py` | "I implemented the passive runtime as a staged pipeline around context preparation, prompt rendering, provider/tool execution, and commit." |
| Prompt and dynamic context are separated | `amadeus/context.py`, `amadeus/prompting/assembler.py`, context-frame tests | "Dynamic memory and retrieval material enter a context frame instead of overwriting the stable system prompt." |
| Markdown plus SQLite memory foundation exists | `amadeus/memory.py`, `amadeus/vector_memory.py` | "Readable memory and machine-retrievable memory are separated: Markdown is for profile/history, SQLite stores retrieval items." |
| Retrieval has vector, lexical, RRF, evidence, and forget support | `amadeus/vector_memory.py`, `amadeus/tools/recall_memory.py`, `amadeus/tools/forget_memory.py` | "The current retrieval layer supports dense and lexical lanes with RRF fusion and source references; it still needs stronger scoring and eval coverage." |
| Tool loop and tool registry exist | `amadeus/tools/`, `amadeus/runtime.py` | "The runtime exposes tools through a registry and executes model tool calls through an executor boundary." |
| Plugin/phase extension exists | `amadeus/phase.py`, `amadeus/plugin/`, phase tests | "Plugins contribute phase modules through a managed ownership and rollback path instead of patching the main loop directly." |

## Claims that need implementation before strong wording

| Resume claim | Current status | Required work | Safer wording until done |
| --- | --- | --- | --- |
| ProactiveLoop active pipeline | Not implemented in Amadeus | Add gate, DataGateway, judge, resolve, outbound, ACK or dry-run trace, and proactive eval | "Designed against Akashic; implementation is the next vertical slice." |
| DriftRunner autonomous exploration | Not implemented in Amadeus | Add a minimal task runner with scan, prepare, execute, finish, and one useful maintenance task | "Planned DriftRunner boundary, not yet a core delivered feature." |
| Telegram/QQ Bot | Not implemented | Add Telegram outbound first; defer QQ | "Telegram-first outbound; QQ is future adapter work." |
| MCP extension | Not implemented as a product path | Keep interfaces MCP-ready or add one real MCP-backed fixture later | "MCP-ready boundary" unless a real integration exists. |
| SQLite/sqlite-vec | Current embeddings are JSON in SQLite | Either migrate to sqlite-vec or change resume wording to SQLite vector store | "SQLite-backed vector memory store" |
| DashScope Embedding | Current provider is OpenAI-compatible embedding config | Add DashScope-compatible provider or use neutral wording | "pluggable embedding provider" |
| AnyActionGate / online / busy / cooldown | Not implemented | Add cooldown, busy guard, simple quota/presence gate | "cooldown and busy gating" until full AnyActionGate exists |
| emotional_weight and time decay | Not implemented | Add scoring fields and ranking influence with eval cases | Remove or call it future scoring work |
| memory retire / merge lifecycle | Superseded exists; merge and lifecycle scoring are incomplete | Add explicit memory lifecycle operations and traces | "forget/supersede with source_ref verification" |
| productized Evaluation | No unified runner yet | Add case schema, runner, report, deterministic tests, and real LLM smoke path | "focused tests and planned eval harness" until built |

## Highest priority evidence to create

1. Evaluation runner that can produce a report for memory recall, source_ref fetch, context isolation, tool loop, and proactive send/skip cases.
2. Real LLM passive smoke with session commit and memory maintenance evidence.
3. Telegram outbound adapter with dry-run and real-send modes.
4. Minimal ProactiveLoop using local alert/content/context fixtures, memory/context injection, send/skip decision, and eval cases.
5. Memory scoring hardening: reinforcement, time decay, retrieval trace, and source-backed correction.

## Interview guardrails

- If asked about Akashic, describe it as the reference design, not copied code.
- If asked about ProactiveLoop before implementation, say the current work is aligning the architecture and that the passive/memory/plugin layers are already in place.
- If asked how behavior is proven, point to Evaluation cases and trace outputs, not only unit tests.
- If asked about Telegram/QQ, state Telegram is the first production adapter and QQ is intentionally deferred.
