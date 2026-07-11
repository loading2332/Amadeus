# 记忆检索独立双 lane 技术设计

## 能力定位

- 产品/架构能力：Akashic-inspired memory retrieval correctness。
- 公开行为证明：`MemoryEngine.recall()` / `recall_memory` 能返回 vector window 外的精确 lexical-only 记忆，并提供可验证 trace。
- Akashic 参考：`../akashic-agent/memory2/retriever.py::retrieve` 与 `MemoryStore2.keyword_search_summary()` 的独立候选合同。
- Amadeus 扩展：PostgreSQL 独立参数化 ILIKE、best-effort trigram 索引、显式 lane provenance、公开 trace 和 final top-k 融合校准。

## 第一性原理约束

1. 候选生成决定“谁有资格被排序”；排序只能改变已有候选的顺序。
2. 两个 lane 若共享同一前置 shortlist，就不是两个召回通道，只是两种重打分信号。
3. provenance 必须在产生候选时记录；从 union 上重新计算分数无法还原数据库实际返回过哪个 lane。
4. 用户看到的是 final top-k；只让 lexical candidate 进入 RRF、但让它在正常输入下必然被淘汰，不满足产品目标。

## 边界与合同

### Store 边界

将生产检索能力从 `getattr(store, "search_active_items")` 的隐式 duck typing 收敛为显式 retrieval store contract。推荐签名：

```python
class MemoryRetrievalStoreProtocol(MemoryStoreProtocol, Protocol):
    def search_vector_candidates(
        self,
        *,
        query_embedding: list[float],
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        limit: int,
    ) -> list[dict[str, Any]]: ...

    def search_lexical_candidates(
        self,
        *,
        terms: tuple[str, ...],
        memory_types: tuple[str, ...] = (),
        scope_channel: str | None = None,
        scope_chat_id: str | None = None,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        limit: int,
    ) -> list[dict[str, Any]]: ...
```

`PostgresMemoryStore` 实现两个方法。仍参与单元测试的 legacy/in-memory store 应实现同一行为合同，或测试改用明确 fake；生产 retriever 不再以 `list_active_items()` 静默模拟 lexical production path。

### Lane 候选合同

融合层接收两个分离集合，而不是一份 union rows：

```python
@dataclass(frozen=True)
class MemoryCandidateLanes:
    vector_groups: tuple[tuple[dict[str, Any], ...], ...]
    lexical: tuple[dict[str, Any], ...]
    lexical_terms: tuple[str, ...]
```

- `vector_groups[index]` 与 `query_texts[index]`、`query_vectors[index]` 对齐。
- vector row 携带 `vector_distance`，其 rank 来自该 query 的真实 SQL 结果。
- lexical row 携带 `lexical_score`，其 rank 来自独立 SQL 结果。
- `row_map` 可以在融合内部按 id union，但只用于构建 `MemoryRecord`；lane membership 只能来自原始集合。

### 排序合同

用新的 lane-aware ranking 入口替代生产路径上的 `rank_multi_query_rows(rows, ...)`：

```python
rank_candidate_lanes(
    candidates: MemoryCandidateLanes,
    query_vectors: list[list[float]],
    query_texts: list[str],
    *,
    limit: int,
    threshold: float,
) -> tuple[list[MemoryRecord], RetrievalLaneTrace]
```

规则：

- 每个 vector group 只评估该 group 实际返回的 rows；同一 id 多 query 命中时保留最高 hotness-fused vector score，同时保留全部真实 matched query indexes。
- lexical score 只读取 `candidates.lexical`，不得对 vector-only rows 补算 lexical membership。
- vector 与 lexical 分别排序后，以稳定 id 做 RRF 与去重。
- `signals["lanes"]`、lane rank 和 lane contribution 均从真实 candidate set 产生。
- 保留 raw `vector_score`、`final_vector_score`、hotness 与 reinforcement 信号。

## Term extraction 决策

中文不依赖 PostgreSQL 内建分词器。应用先把 raw query 提取成有限个可检索 term，PostgreSQL lexical lane 再对这些 term 做独立 substring 查询。这里对齐 Akashic `memory2/retriever.py::_extract_terms()` 的行为合同：

```text
ASCII: [A-Za-z0-9_.-]{2,}
CJK chunk: [\u4e00-\u9fff\u3040-\u30ff]{2,}

chunk 长度 2～4  -> 保留整个 chunk
chunk 长度 > 4   -> 拆相邻 bigram
顺序                -> 先收集全部 ASCII terms，再收集全部 CJK terms
随后                -> CJK stopword 过滤、对拼接序列稳定去重、截断至 20 terms
```

这里的“稳定去重”保留的是上述拼接序列中的第一次出现，不是跨 ASCII/CJK 的全局原文顺序；这是 Akashic 两次正则 pass 的实际行为。

“CJK”在这里是 Akashic 的代码名称，精确范围是常用汉字、平假名和片假名；它不是 PostgreSQL extension，也不是把数据库文本预先切成 token。数据库仍保存原始 `summary`，查询时收到应用提取出的 terms。

示例：

| raw query 片段 | 目标 terms | 原因 |
|---|---|---|
| `支付宝` | `支付宝` | 3 字，保留完整 chunk |
| `长期记忆` | `长期记忆` | 4 字，保留完整 chunk |
| `支付宝支付` | `支付`、`付宝`、`宝支` | 5 字拆 bigram，重复的第二个 `支付` 被稳定去重 |
| `ZXQ-4917 v1.2` | `ZXQ-4917`、`v1.2` | ASCII 连续 token 支持 `_`、`-`、`.` |

Amadeus 当前 `extract_terms()` 对所有超过 2 字的中文块都拆 bigram，而且不包含平假名/片假名、ASCII `-`/`.` 和 20-term 上限。实施必须显式迁移并用边界测试锁定，不能只复用旧 helper 后把查询搬进 SQL。

本次不额外保留超过 4 字的完整 phrase，也不把中文统一改成 trigram。前者会改变 Akashic 的候选和命中比例合同，后者会削弱 2 字查询；两者若有必要，应在独立 recall eval 证据出现后再设计。

## PostgreSQL lexical lane

### 选型

采用独立的参数化 `summary ILIKE ... ESCAPE '!'` 保障 substring 召回，并在 bare `summary` 上增加 `pg_trgm` GIN 索引；不增加 `tsvector` 列。

原因：

- 目标合同以 Akashic ASCII/CJK term 的 substring 命中为基础；`ILIKE '%term%'` 直接保留该语义。
- PostgreSQL 官方说明 `gin_trgm_ops` 直接支持 bare column 上的 `ILIKE`，无需 `lower(summary)` expression index。
- PostgreSQL 默认 text search configuration 不能等价处理中文 bigram；直接使用 `tsvector` 会改变召回语义。
- BM25 需要额外扩展或搜索系统，不是 PostgreSQL 内建 `ts_rank`，超出本任务的最小机制。

迁移新增：

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE INDEX ix_memory_items_summary_trgm
ON memory_items USING gin (summary gin_trgm_ops);
```

查询采用动态生成的占位符结构与参数化 term 值：

```text
WHERE user_id/status/type/scope/time filters
  AND (summary ILIKE %pattern_1% ESCAPE '!' OR ...)
ORDER BY lexical_score DESC, reinforcement DESC, id ASC
LIMIT lexical_candidate_limit
```

pattern builder 按顺序执行 `! -> !!`、`% -> !%`、`_ -> !_`，再在两侧添加 `%`。term value 继续使用 psycopg 参数，只有由 term 数量决定的占位符结构可以动态生成。

`lexical_score = matched_term_count / total_term_count`，保持可解释性。term 上限按 Akashic 固定为 20。

真实 PostgreSQL 16 / 100,000 行临时表实验已经确认：

- `%支付宝支付%`、`%ZXQ-4917%` 和 escaped `%foo!_bar%` 使用 Bitmap GIN scan；
- `%支付%` 默认使用 Seq Scan；强制 full-index scan 反而更慢；
- 对超过 4 字的 CJK chunk，目标 extractor 仍会产生 `%支付% OR %付宝% OR %宝支%` 这类 bigram OR，并使用 Seq Scan；即使额外 OR 一个长中文 pattern，短 pattern 仍会拖回 Seq Scan；
- 纯 `%zxq% OR %4917%` 使用 BitmapOr 与两个 GIN scans；
- built-in `simple` FTS 无法用 `支付` 命中无空格长中文。

因此 trigram index 可加速 ASCII/数字/标识符，以及部分被完整保留的 3～4 字 CJK chunk；它不是超过 4 字 chunk 所产生 bigram OR 或混合 OR 查询的性能承诺。短词仍必须在 user/status/type/scope/time 预过滤后的 eligible corpus 上正确查询；不能为了索引命中退回共享 vector shortlist。完整证据见 `research/postgres-lexical-channel-options.md`。

两个搜索方法复用同一个 store 内部 filter builder，避免 user/status/type/scope/time 条件漂移。

## 候选量与融合可见性

- vector candidate limit 保持当前每 query `4 * max(top_k, request.limit)`，本任务不借扩大窗口掩盖问题。
- lexical candidate limit 采用 Akashic 合同 `max(30, final_limit * 2)`。
- RRF `k=60` 保持不变。
- lexical lane 的首轮运行与确定性 eval 基线从 `0.5` 调整为 `1.0`，恢复标准 equal-weight RRF，使默认 top-8 下 rank-1 精确 lexical-only 候选具备实际入选能力；这是有意的 Amadeus 扩展，不声称来自 Akashic，也不把 `1.0` 视为无需评测的永久参数。
- ranking 边界必须集中管理 lexical weight，使本地 retrieval eval 可以显式覆盖实验值；只有独立候选正确性、provenance 与默认可见性验收通过后，才比较 weight、candidate window、RRF `k` 与 final K。
- 使用稀有标识符 fixture 锁定 final top-k 行为。若 eval 暴露泛词误召回，优先收紧 term/lexical candidate quality，不得通过恢复共享 shortlist 来降低噪声。

此策略不承诺任意 lexical hit 必然入选；它承诺独立入场，并证明高置信 rank-1 lexical-only 结果在默认路径可见。

权重下界、32 个 vector decoys 下的确定性排名与标准 RRF 参考见 `research/rrf-final-visibility.md`。

## 数据流

```text
MemoryRecallRequest
-> build_query_plan(raw + optional event/general)
-> embed vector query texts
-> search_vector_candidates() per query
-> extract_terms(raw query)
-> search_lexical_candidates() once
-> MemoryCandidateLanes
-> rank_candidate_lanes()
   -> vector max-pool + hotness
   -> lexical native score/rank
   -> weighted RRF + stable-id dedupe
-> MemoryQueryResult(records, trace)
-> recall_memory / context injection / eval
```

scope fallback 仍按现有语义工作：先让两个 lane 使用 scoped filters；只有融合结果为空时，两个 lane 一起以 global scope 重试。不得只对其中一个 lane 放宽 scope。

## Trace 兼容与新增字段

保留 `intent`、`queries`、`scope`、`scope_mode`、`time_filters`、`candidate_count`、`lane_counts`、`record_count`、`records`、`fallbacks`、`errors` 和 `hypothesis_retrieval`。

新增或收敛：

```python
"candidate_counts": {
    "vector": 32,
    "lexical": 3,
    "union": 34,
    "final": 8,
},
"lane_status": {
    "vector": "ok",   # degraded | error
    "lexical": "ok",  # degraded | disabled | no_terms | error
},
"lexical_query": {
    "terms": ["zxq-4917"],
},
```

`candidate_count` 为兼容保留，语义明确为 union count。`lane_counts` 保留每个 query 的 shape，但数值改为真实候选/阈值命中，不再来自 union 补算。

每条 record signals 新增真实的 `vector_rank`、`lexical_rank`、`vector_rrf_contribution`、`lexical_rrf_contribution`；现有 `lanes`、`matched_query_indexes`、score/hotness 字段继续存在。

## 失败与降级

- raw query 无有效 terms：跳过 lexical SQL，`lane_status.lexical = "no_terms"`。
- lexical kill switch 关闭：vector-only，trace 为 `disabled`。
- lexical SQL 运行时失败：保留 vector 结果，追加 `lexical_retrieval_failed` fallback 与结构化 error；不得把 union 上的 substring 当作替代。
- scoped 尝试失败而 global fallback 成功时，保留最终候选，但对应 lane 的聚合状态必须是 `degraded`，不得用第二次成功把第一次失败重标为 `ok`。
- `pg_trgm` extension/DDL 不可用：Alembic upgrade 失败，部署不得假装迁移成功。
- vector 无候选或 embedding 失败但 lexical 正常：lexical-only 仍可返回；不要让 embedding availability 成为关键词召回前置条件。

建议增加 `AMADEUS_MEMORY_LEXICAL_RETRIEVAL_ENABLED`，默认开启，作为查询级回滚开关；DDL 保留不会影响 vector-only 路径。

## 兼容、发布与回滚

- 无需改变 `MemoryRecallRequest`、`MemoryQueryResult`、tool output 或 source/evidence contract。
- migration 先创建 extension/plain-column index，再发布调用新 store method 的代码。
- 代码回滚可通过 kill switch 切回 vector-only；trace 必须显示 disabled，不能显示双 lane。
- migration downgrade 删除 task-owned GIN index；不要无条件删除可能被其他模块共享的 `pg_trgm` extension。
- 当前 interview 文档在实现完成前应明确这是缺口；完成后再恢复“独立双路”的 claim。

## 取舍

- 不选择默认 PostgreSQL FTS：真实 PostgreSQL 16 实验证明无空格中文 substring 不匹配。
- 不选择 `pg_bigm`：它能加速 2 字 CJK，但需要自编译 extension、custom PostgreSQL image 与 preload 配置，超出当前切片。
- 不声称 `pg_trgm` 加速 2 字 CJK bigram 或包含短 CJK 的混合 OR 查询：这些场景默认 Seq Scan，索引只对可提取 trigram 的查询做 best-effort 优化。
- 不把中文统一改成 trigram：term extraction 继续对齐 Akashic 的 2～4 字完整 chunk / 超过 4 字 bigram 合同。
- 不只增加 lexical SQL 再 union：会伪造 provenance。
- 不只测试 store method：无法证明 final public behavior。
- 不复制 Akashic `0.5` 权重：它不能满足本任务的 final top-k 目标。
- 不引入专用搜索服务/BM25 extension：当前 corpus 与需求不需要该运维复杂度。
