# Amadeus 当前检索缺口核对

## 一句话结论

当前生产实现只有 pgvector 候选生成；所谓 lexical lane 是在有限向量候选并集上的二次打分，不是独立召回通道。

## 当前数据流

```text
raw/event/general query
-> 每个 query 做 embedding
-> 每个 query 通过 pgvector 各取默认 32 条候选
-> 按 memory id 合并
-> 仅在该并集上计算 raw-query lexical score
-> vector/lexical RRF
-> 默认返回 8 条
```

最终 `limit` 与前置 vector candidate window 是不同概念。默认 `top_k=8`，但 `_candidate_rows()` 对每个 query 过采样到 32；无论窗口多大，它仍是有限向量集合。

## 代码证据

### 数据库候选

- `migrations/versions/20260704_0001_postgres_foundation.py:23` 只创建 `vector` extension。
- `migrations/versions/20260704_0001_postgres_foundation.py:101-121` 中 `summary` 只是 `TEXT`；检索索引只有 user/status、source_ref 与 HNSW embedding。
- `amadeus/memory/postgres.py:350-417` 的 `search_active_items()` 要求 `embedding IS NOT NULL`，按 `<=>` 排序并 `LIMIT`，没有 query text 或关键词谓词。

### Retriever 候选编排

- `amadeus/memory/retriever.py:185-228` 对每个 query vector 调用同一个 pgvector 搜索。
- `amadeus/memory/retriever.py:213-218` 把单 query limit 设置为 `4 * max(top_k, request.limit)`。
- `amadeus/memory/retriever.py:219-221` 只按 id 合并向量结果。
- `list_active_items()` fallback 只服务没有 `search_active_items` 的 store；生产 `PostgresMemoryStore` 不走该路径。

### 排序与 trace

- `amadeus/memory/ranking.py:150-205` 只接收一份 rows，在同一集合内计算关键词与向量分数后交给 RRF。
- `amadeus/memory/ranking.py:161-181` 保证 lexical 只读取 raw query，但不能引入 rows 外的记录。
- `amadeus/memory/ranking.py:332-380` 的 RRF 只融合传入 id 的并集。
- `amadeus/memory/retriever.py:75-94` 的 `candidate_count` 和 `lane_counts` 因此无法证明独立 lane。

## 迁移回归

在 pgvector 迁移前，SQLite store 的 `list_active_items()` 会把完整 eligible rows 交给 ranking。虽然没有独立 lexical SQL，但 vector threshold 外的记录仍可凭关键词进入 RRF。

commit `198f587b5d3eb98d250a5a45fbcaf2beb6396ccb` 把生产候选收窄为 pgvector window。归档任务 `.trellis/tasks/archive/2026-07/07-04-memory-postgres-pgvector/prd.md:37-39,71,106` 当时要求保留 lexical signal，却明确不重做 ranking，因此遗漏了候选生成语义。

这不是当时显式接受的 limitation，而是后来发现的合同漂移。

## 现有测试为什么没有发现

- `tests/memory/test_postgres_memory_store.py:194` 只证明两条记录按 `<=>` 排序。
- `tests/memory/test_memory_ranking.py:35` 手工把所有 rows 传给 ranking，只证明“已经入场后”可以 lexical-only。
- `tests/memory/test_memory_retriever.py:127` 附近的场景没有超过单 query 默认 32 条 vector window。
- `tests/memory/test_memory_retriever.py:184` 正确证明 hypothesis 不制造 lexical hit，应保留。
- `tests/evaluation/cases/memory_recall_v1.yaml` 每个 case 只 seed 一条长期记忆，无法触发候选截断。

## 设计警告

不能把 vector rows 与 lexical rows 做 union 后继续调用当前 `rank_multi_query_rows()`：

- lexical-only row 会在 union 上重算 cosine，可能被伪标为 vector 命中；
- vector-only row 会在 union 上重算 substring，可能被伪标为 lexical 命中；
- 每个 lane 的数据库 rank 与真实 candidate membership 会丢失。

融合层必须从两个原始候选集合消费 provenance，union 只用于最终记录 hydration 与去重。
