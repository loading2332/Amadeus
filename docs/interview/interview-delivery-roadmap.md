# Interview delivery roadmap

This roadmap keeps the resume goal but preserves architecture order. Do not implement upper-layer claims before their lower-layer contracts are verifiable.

## Phase 0: execution protocol

- Replace the old teaching-oriented workspace instructions with interview delivery mode.
- Keep Akashic as read-only reference.
- Maintain this roadmap and `resume-claim-gap-audit.md` as the active planning source.

Acceptance:

- Root prompts no longer default to course artifacts.
- New tasks can be mapped to a resume claim and a verification path.

## Phase 1: passive runtime confirmation

- Run a real or fake-provider smoke through `PassiveRuntime`.
- Capture prompt sections, context frame, tool schemas, session commit, and memory maintenance behavior.
- Add or update one smoke case that proves the passive chain end to end.

Acceptance:

- The user can explain input -> context -> provider/tool loop -> commit -> memory event.
- A command or test proves the flow still works.

## Phase 2: memory hardening

- Standardize retrieval trace fields.
- Make reinforcement influence ranking or injection selection.
- Add time decay only if it can be tested deterministically.
- Keep source_ref fetch and forget/supersede behavior as non-negotiable contracts.

Acceptance:

- Memory eval cases prove recall, source_ref fetch, correction, forgetting, fallback, and context-frame injection.
- Resume wording avoids unsupported claims like sqlite-vec or emotional_weight until implemented.

## Phase 3: Evaluation product slice

- Add an eval case schema and runner.
- Produce a human-readable report and machine-readable JSON result.
- Cover memory, retrieval, context isolation, tool loop, and proactive decisions.
- Use deterministic fakes for regression and optional real LLM smoke for integration.

Acceptance:

- Evaluation can be run independently from ordinary unit tests.
- Failures explain which public behavior regressed.

## Phase 4: Telegram outbound

- Define an `OutboundPort` boundary before any Telegram adapter.
- Add Telegram adapter with dry-run mode and real-send mode.
- Add a `message_push` style tool or runtime service that uses the outbound boundary.

Acceptance:

- A smoke proves a message can be prepared in dry-run mode.
- Real-send verification is available when credentials are configured.
- Core runtime does not import Telegram-specific implementation details.

## Phase 5: scheduler

- Add scheduled job model, JSON or SQLite store, fire-at parser, and tick execution.
- Keep instant jobs separate from soft jobs that need an agent/runtime entry.
- Use outbound dry-run first, then Telegram when configured.

Acceptance:

- Eval or smoke proves after/at/every behavior, cancellation, recovery, and no duplicate in-flight execution.

## Phase 6: ProactiveLoop

- Implement the minimum real pipeline: gate, DataGateway, LLM judge, resolve, outbound, ACK or dry-run trace.
- Use local fixture sources first: alert, content, and context.
- Integrate memory/context only through existing boundaries.

Acceptance:

- Proactive eval proves send, skip, duplicate suppression, no-content skip, and source-bound message evidence.
- Telegram outbound can be used without coupling ProactiveLoop to Telegram internals.

## Phase 7: DriftRunner

- Add only a minimal useful task runner after ProactiveLoop is stable.
- Start with one maintenance task such as memory audit or proactive rule review.
- Require explicit finish state and trace.

Acceptance:

- Drift can run silently or produce one outbound summary through the outbound boundary.
- If not implemented, keep resume wording as planned or future work.
