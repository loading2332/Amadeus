# Logging Guidelines

> Runtime logging and trace conventions for Amadeus.

---

## Overview

Amadeus uses Python `logging` sparingly for host-level diagnostics and uses
structured traces for product behavior. Prefer returning trace dictionaries,
reports, and artifacts for interview evidence; use logs for lifecycle warnings
that operators need while loading plugins or handling observers.

Primary examples:

- `amadeus/events.py` logs observer exceptions with `logger.exception`.
- `amadeus/plugin/manager.py` logs plugin duplicate/load/cleanup warnings.
- `amadeus/app/cli.py` prints explicit trace output only when `--trace` is set.
- `amadeus/evaluation/*_runner.py` writes JSON and Markdown artifacts under `runtime-artifacts/evaluation/`.

## Log Levels

- `debug`: not commonly used yet; add only for local diagnostic detail that is too noisy for normal operation.
- `info`: successful host-level lifecycle events, such as plugin loaded.
- `warning`: recoverable host failures, duplicate plugins, disabled/ignored plugin metadata, cleanup failures, or optional data ignored.
- `error` / `exception`: unexpected observer or infrastructure failure where stack context is useful and sensitive text is controlled.

## Structured Logging

- Prefer stable key/value fragments in log messages: `name=%s source=%s stage=%s exception=%s`.
- For plugin failures, log stage and exception type, plus sanitized traceback frame locations.
- Do not log raw plugin source text or exception messages that may contain secrets.

## Trace Artifacts

- Public behavior evidence should be in structured traces, not only logs:
  - `PassiveTurnResult.memory_trace`;
  - `ToolTrace.status` and tool-chain records;
  - memory `candidate_decisions`, `written_ids`, and `superseded_ids`;
  - evaluation JSON summaries and human-readable Markdown summaries.
- CLI trace formatting should stay deterministic because tests assert exact sections.

## What NOT to Log

- API keys, tokens, `.env` contents, or plugin exception messages that may include secrets.
- Full user transcripts in host-level logs. Source-backed evidence should flow through `source_ref` and `fetch_messages`.
- Large LLM payloads by default; expose narrow trace fields and artifact paths instead.
