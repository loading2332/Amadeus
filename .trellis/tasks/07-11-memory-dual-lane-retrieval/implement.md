# 记忆检索独立双 lane 实施计划

## 实施顺序

### 1. 先写回归测试，锁定真实缺口

- [x] 在 `tests/memory/test_memory_ranking.py` 增加 Akashic-compatible extractor 参数化测试：2/3/4 字 CJK chunk、超过 4 字的相邻 bigram、平假名/片假名、ASCII `_-.`、长度下界、CJK stopword、稳定去重和 20-term 截断。
- [x] 修改当前 extractor 测试，使用独立 query `仁王机制` 或带分隔符的 `讨论 仁王机制`，明确 4 字 chunk 应保留完整；不得用连续 6 字的 `讨论仁王机制` 证明该行为，因为它按 Akashic 合同仍应拆 bigram。
- [x] 在 `tests/memory/test_postgres_memory_store.py` 增加独立 lexical SQL 测试：中英文、稀有标识符、`embedding IS NULL`、稳定排序和 LIKE wildcard 字面转义。
- [x] 在 `tests/memory/test_memory_retriever.py` 或 `test_memory_retrieval_acceptance.py` 构造超过单 query vector window 的 decoys，证明目标不在任何 vector candidates 中，但公开 recall 最终返回 lexical-only 目标。
- [x] 增加一个会在“vector/lexical rows union 后重算”实现下失败的 provenance 测试。
- [x] 保留并扩展 generated hypothesis 不制造 lexical hit 的现有测试。

第一轮红灯应说明：当前生产 store 没有独立 lexical 查询，目标 id 从未进入 RRF。不要用调低 threshold 或扩大 vector limit 让测试变绿。

### 2. 增加 PostgreSQL schema 与 store 合同

- [x] 将 `amadeus.memory.ranking.extract_terms()` 对齐 Akashic 合同：ASCII `[A-Za-z0-9_.-]{2,}`；CJK 2～4 字保留完整、超过 4 字拆 bigram；迁移 Akashic CJK stopwords；稳定去重并最多返回 20 terms。
- [x] 新增 Alembic revision，创建 `pg_trgm` extension 与 bare `summary gin_trgm_ops` 的 `ix_memory_items_summary_trgm` GIN index；实现可重复 upgrade 与安全 downgrade。
- [x] 在 memory engine/store typing 中定义显式 `MemoryRetrievalStoreProtocol`，包含 vector 与 lexical candidate 方法。
- [x] 将 `PostgresMemoryStore.search_active_items()` 收敛/迁移为含义明确的 `search_vector_candidates()`。
- [x] 实现 `search_lexical_candidates()`：参数化 OR-ILIKE、显式 `ESCAPE '!'`、term hit ratio、稳定排序、limit。
- [x] 提取并复用 active candidate filter builder，保证两个 lane 的 user/status/type/scope/time 过滤一致。
- [x] 为仍需参与检索单元测试的 legacy/fake store 补齐显式合同，移除生产 `getattr()` fallback。

审查点：使用真实 PostgreSQL 验证 `pg_trgm` extension/index 存在；对纯 ASCII/标识符、CJK bigram OR、CJK + ASCII 混合 OR 和 escaped wildcard 运行 `EXPLAIN`。CJK short-pattern 查询允许诚实的 scoped Seq Scan，不得写出虚假的 index-usage 断言。

### 3. 重构 retriever 与 lane-aware ranking

- [x] 在 retriever 中分别加载 per-query vector groups 与一次 raw-query lexical candidates。
- [x] 隔离 vector embedding/search 与 lexical query 的失败边界，避免 embedding 异常在 lexical 查询前终止整次 recall。
- [x] 引入 `MemoryCandidateLanes` 或等价 typed contract，保留 query-index 对齐和原始 lane 集合。
- [x] 新增 `rank_candidate_lanes()`；只在真实 vector groups 上计算 vector/hotness，只在真实 lexical rows 上读取 lexical score。
- [x] 同 id 多 vector query 命中时保留最佳 vector score，并记录真实 `matched_query_indexes`。
- [x] 以稳定 id 去重并执行 weighted RRF；保持 `k=60`，将 lexical weight `1.0` 作为首轮运行/确定性 eval 基线，并集中暴露可覆盖的实验参数，避免把该数值散落成永久 magic number。
- [x] 保持 source_ref、evidence、hotness、reinforcement 与 record ordering 的兼容字段。
- [x] 保持 scoped -> global fallback 时两个 lane 同步重试，并把跨尝试的部分失败聚合为 `degraded`。

审查点：删除或隔离生产路径对旧 `rank_multi_query_rows(rows, ...)` 的使用；旧 helper 若为单元测试兼容保留，文档必须说明它不代表生产候选召回。

### 4. 配置、降级与 trace

- [x] 增加 `AMADEUS_MEMORY_LEXICAL_RETRIEVAL_ENABLED`，默认开启，并接入 `RuntimeConfig`、bootstrap 与 `.env.example`。
- [x] 实现 vector 的 `ok/degraded/error` 与 lexical 的 `ok/degraded/disabled/no_terms/error` lane status。
- [x] lexical 查询异常时返回 vector-only，并在 `fallbacks/errors` 中留下明确证据。
- [x] vector embedding/search 异常时允许 lexical-only 返回，并记录 vector lane error/fallback。
- [x] 增加 `candidate_counts`、`lane_status`、`lexical_query.terms` 与逐 record lane rank/contribution。
- [x] 保留现有 trace 顶层字段和 tool/runtime consumers。

### 5. 公共行为与 eval

- [x] 扩展 `test_memory_retrieval_acceptance.py`，从 `RecallMemoryTool` 或 `MemoryEngine.recall()` 断言 vector-window 外 lexical-only 结果、source_ref 与 citation contract。
- [x] 为 user/status/type/scope/time 过滤增加跨 lane 集成矩阵。
- [x] 扩展 memory recall eval case/expect/evaluator；canonical case 通过 NULL-embedding fixture 断言 lexical candidate count、strict lexical-only provenance、rank 与 contribution。
- [x] 增加稀有标识符竞争 fixture，避免只用单条可进入 vector shortlist 的记忆形成 tautological eval。
- [x] 独立候选正确性通过后完成本地确定性参数实验，对照 Akashic `0.5` 与 equal-weight `1.0` 的默认 final top-8 可见性；候选机制收敛前未使用 LangSmith 调参。
- [x] 确认 context injection 使用最终融合顺序，不会重新按无关 score 破坏结果。

### 6. 规格与当前文档收敛

- [x] 用 `trellis-update-spec` 更新 `.trellis/spec/backend/quality-guidelines.md`：独立候选、lane provenance、final top-k 和必需回归 fixture。
- [x] 更新 `docs/interview/resume-claim-gap-audit.md` 与 `docs/interview/interview-delivery-roadmap.md`，使 claim 与实际实现一致。
- [x] 运行 `rg` 确认没有把长期记忆 lexical lane 描述成未使用的 BM25/FTS。

## 验证命令

数据库前置：

```powershell
docker compose up -d postgres
uv run alembic upgrade head
```

窄检查：

```powershell
uv run pytest -q tests/memory/test_postgres_memory_store.py
uv run pytest -q tests/memory/test_memory_retriever.py tests/memory/test_memory_ranking.py
uv run pytest -q tests/memory/test_memory_retrieval_acceptance.py
uv run pytest -q tests/evaluation/test_memory_recall_runner.py tests/evaluation/test_evaluators.py
```

迁移与静态检查：

```powershell
uv run alembic downgrade -1
uv run alembic upgrade head
uv run ruff check amadeus/memory amadeus/evaluation tests/memory tests/evaluation migrations
uv run mypy amadeus
```

广检查：

```powershell
uv run pytest -q tests/memory tests/evaluation tests/db
```

检索声明检查：

```powershell
rg -n "dual.?lane|双.?lane|lexical|keyword|BM25|tsvector|pg_trgm" .trellis/spec docs/interview amadeus/memory tests/memory tests/evaluation
```

## 风险文件与回滚点

- `migrations/versions/*memory*lexical*.py`：extension/index DDL；先单独验证 upgrade/downgrade。
- `amadeus/memory/postgres.py`：两个 lane 的过滤一致性与 SQL 参数顺序。
- `amadeus/memory/retriever.py`：scope fallback、candidate count 和异常降级。
- `amadeus/memory/ranking.py`：provenance、RRF、hotness 与稳定排序。
- `amadeus/evaluation/cases.py` / evaluators：新增 expectation 必须向后兼容已有 YAML。

若新 lexical 查询造成性能或错误回归，先通过 kill switch 明确降级为 vector-only；不得恢复“共享 vector rows 后标 lexical”的伪双 lane。若迁移失败，回滚应用并执行 migration downgrade 删除 task-owned index。

## 启动前审查门

- [x] 用户确认 lexical rank-1 的高置信 lexical-only 结果必须能进入默认 final top-8，而不只是进入 RRF 候选；lexical weight `1.0` 为首轮实验基线，最终参数由 eval 决定。
- [x] 用户确认 tokenizer 对齐 Akashic；lexical 使用独立、参数化且字面转义的 `ILIKE` 保证 substring 正确性，并以 plain `pg_trgm` GIN 作为首版 best-effort 加速。超过 4 字产生的 CJK bigram 查询允许在 eligible corpus 上 scoped scan。
- [x] `prd.md`、`design.md`、`implement.md` 已审阅。
- [x] 获得实现授权后已运行 `python ./.trellis/scripts/task.py start .trellis/tasks/07-11-memory-dual-lane-retrieval`。

## 最终质量结果

- `uv run pytest -q tests/memory tests/evaluation tests/db`：`145 passed`。
- `uv run pytest -q`：`550 passed`，另有 1 条既有 Starlette deprecation warning。
- `uv run mypy amadeus`：99 个 source files 无错误。
- 任务 Python 文件 Ruff lint/format：通过。
- Alembic `downgrade -1 -> upgrade head`：通过；downgrade 后 `pg_trgm` 保留且任务索引删除，upgrade 后索引恢复，当前为 `20260711_0004 (head)`。
