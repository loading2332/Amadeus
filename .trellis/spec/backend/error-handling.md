# Error Handling

> Error handling conventions observed in Amadeus backend code.

---

## Overview

Amadeus separates hard runtime failures from observable tool/eval failures.
Configuration and lifecycle failures raise exceptions. Tool execution catches
tool failures and returns structured `ToolResult` plus `ToolTrace`. Evaluation
runners should surface failed cases in reports instead of hiding judge or target
failures as passes.

Primary examples:

- App lifecycle cleanup: `amadeus/app/bootstrap.py`.
- CLI cleanup behavior: `tests/app/test_cli.py`.
- Tool execution: `amadeus/tools/executor.py`.
- Evaluation summarization: `amadeus/evaluation/evaluators.py`.
- Plugin load failure reporting: `amadeus/plugin/manager.py`.

## Error Types

- Use `ValueError` for invalid config, malformed case files, missing required fields, and unsupported modes.
- Use `RuntimeError` for lifecycle state violations, closed app usage, duplicate phase slots, or impossible runtime states.
- Use narrow domain exceptions where they improve caller behavior, e.g. `ToolExecutionDenied` and `MemoryOptimizerBusy`.
- Tool failures should usually return `ToolResult(..., is_error=True)` and a `ToolTrace.status` of `denied` or `error`.

## Error Handling Patterns

- Preserve the original operational failure when cleanup also fails. Add cleanup context as a note instead of replacing the root error.
- Catch plugin load failures at the plugin boundary and report sanitized stage/type information in `PluginLoadRecord`.
- Let configuration validation fail early. `load_runtime_config()` and eval config validation should stop before running partial behavior.
- In eval summary logic, infrastructure skips are failures unless a case explicitly models optional behavior.
- Use typed traces for expected non-fatal outcomes, such as memory retrieval fallbacks, skipped writes, denied tools, and failed eval rows.

## API / CLI Error Responses

- CLI commands print user-facing result summaries for successful runs.
- Trace output should expose stable fields such as session key, message ids, tool chain, memory trace, provider model/usage, and artifact paths.
- Do not print secrets, API keys, or raw plugin exception messages in logs or public reports.

## Common Mistakes

- Do not swallow failed judge or tool behavior as a passing evaluation.
- Do not convert async tool results to sync by awaiting implicitly in `execute()`; use `execute_async()`.
- Do not leak sensitive exception text from plugin import/initialize/terminate failures.
