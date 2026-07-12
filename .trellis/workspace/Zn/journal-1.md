# Journal - Zn (Part 1)

> AI development session journal
> Started: 2026-07-03

---



## Session 1: Clarify memory supersede lifecycle

**Date**: 2026-07-03
**Task**: Clarify memory supersede lifecycle
**Branch**: `main`

### Summary

Reworked Amadeus memory replacement flow so post-response corrections write new memories via memorize and retire old memories through explicit supersede_many with replacement relation records. Added focused memory tests and backend code-spec guidance.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `82e1da3` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Memory quality eval and Trellis bootstrap

**Date**: 2026-07-03
**Task**: Memory quality eval and Trellis bootstrap
**Branch**: `main`

### Summary

Added productized memory-quality evaluation evidence, fixed skipped eval semantics, and completed Trellis backend guideline bootstrap.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f5052c3` | (see git log) |
| `c111318` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: Memory hotness ranking

**Date**: 2026-07-03
**Task**: Memory hotness ranking
**Branch**: `main`

### Summary

Implemented Akashic-style hotness fusion for memory ranking, exposed scoring signals in retrieval trace, updated interview docs and backend quality spec, and verified focused memory/runtime tests.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `6bc42c9` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Akashic-style hypothesis retrieval

**Date**: 2026-07-03
**Task**: Akashic-style hypothesis retrieval
**Branch**: `main`

### Summary

Implemented Akashic-style explicit memory retrieval with event/general hypothesis queries, raw-only lexical retrieval, best-vector-hit pooling, structured trace, config wiring, tests, and interview documentation.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `d977565` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: FastAPI web turn runtime

**Date**: 2026-07-04
**Task**: FastAPI web turn runtime
**Branch**: `codex/delivery-runtime`

### Summary

Implemented FastAPI web chat entrypoint with turn queue, SSE status tracking, independent worker, APIRouter structure, focused tests, and task documentation for the delivery runtime branch.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8fd146c` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: PostgreSQL worker runtime migration

**Date**: 2026-07-04
**Task**: PostgreSQL worker runtime migration
**Branch**: `codex/delivery-runtime`

### Summary

Completed PostgreSQL foundation, Postgres web turn/session runtime, pgvector memory store, Markdown memory PostgreSQL write state, Docker runtime cleanup, real WSL Docker health smoke, and archived the parent Trellis task.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `9e4cad0` | (see git log) |
| `2f75ab8` | (see git log) |
| `198f587` | (see git log) |
| `a5f8424` | (see git log) |
| `2e9155d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: Remove SQLite Runtime Stores

**Date**: 2026-07-05
**Task**: Remove SQLite Runtime Stores
**Branch**: `codex/delivery-runtime`

### Summary

Removed SQLite-backed runtime store paths, tightened structured session contracts around SessionRef, ported coverage to PostgreSQL-backed tests, and documented breaking surface for CLI/web/memory APIs.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `5836e63` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: 完成本地 MCP Host 与统一工具链路

**Date**: 2026-07-11
**Task**: 完成本地 MCP Host 与统一工具链路
**Branch**: `codex/tool-registry-mcp`

### Summary

完成 local_trusted stdio MCP Host、统一 ToolRegistry/ToolExecutor/deferred 数据流、生命周期与回滚处理；补齐端到端和资源回收验证，并更新中文任务文档及 backend spec。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `ff4d1a2` | (see git log) |
| `7bde6ee` | (see git log) |
| `f0aa7fb` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 9: 完成记忆检索独立双 lane 召回

**Date**: 2026-07-11
**Task**: 完成记忆检索独立双 lane 召回
**Branch**: `codex/delivery-runtime`

### Summary

实现 PostgreSQL pgvector 与独立 lexical 候选通道，按 Akashic 规则提取 ASCII/CJK terms，以参数化 ILIKE、pg_trgm GIN、lane-aware RRF、独立失败降级和公开评测证明 lexical-only 记忆可进入最终结果。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f05f43b` | (see git log) |
| `4ab3e52` | (see git log) |
| `0afca18` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: 长期记忆检索参数评估与 holdout 决策

**Date**: 2026-07-12
**Task**: 长期记忆检索参数评估与 holdout 决策
**Branch**: `codex/delivery-runtime`

### Summary

完成可注入 retrieval 参数合同、60-family Gold Set、本地真实 PostgreSQL 分阶段 sweep、holdout-only qrels rebase 与逐 family bootstrap；三组 holdout Recall@8 均为 1.0，因探索组 development lexical-only 退化且保守组无质量收益，决定保留生产 baseline。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `51e1a0d` | (see git log) |
| `093a342` | (see git log) |
| `e02774f` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
