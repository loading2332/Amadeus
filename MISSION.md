# Mission: Amadeus as an interview-ready agent project

## Why

Amadeus exists to become a credible resume project for AI agent development. It should be grounded in Akashic's real design, but the near-term target is not to complete a long training track. The near-term target is to build a runnable, verifiable agent system whose core claims can survive interview follow-up.

## Success looks like

- Real LLM turns can run through the passive runtime and persist useful session state.
- The memory system supports readable long-term memory, vector/keyword retrieval, source references, correction, forgetting, and traceable evidence.
- Evaluation exists as a product capability: cases, runner, report, and regression checks for memory, context, tools, and proactive decisions.
- Telegram-first outbound and proactive behavior can be demonstrated end to end.
- The user can explain the main code paths, tradeoffs, failure modes, and verification evidence behind each resume claim.

## Current priorities

1. Align documentation and working prompts with interview delivery.
2. Confirm and harden the existing passive runtime, context, tool loop, phase, plugin, and memory behavior.
3. Build productized Evaluation before expanding proactive behavior.
4. Add Telegram outbound and scheduler support.
5. Implement a minimal but real ProactiveLoop.
6. Add DriftRunner only after the proactive foundation is demonstrable.

## Constraints

- Akashic is a reference implementation, not a base class.
- Amadeus should preserve clean boundaries: `MemoryEngine`, public runtime behavior, eval runner, outbound adapter, scheduler, proactive pipeline.
- Do not add impressive resume terms unless the repository has code and verification evidence to support them.
- Do not use fake production mechanisms to make a demo look complete. Deterministic fakes are acceptable in tests and eval fixtures.

## Out of scope for the default mode

- Generating formal study artifacts.
- Completing every Akashic subsystem before interview delivery.
- Adding QQ Bot, full MCP integration, dashboard UI, or advanced Drift behavior before Telegram, Evaluation, and ProactiveLoop have a stable vertical slice.
