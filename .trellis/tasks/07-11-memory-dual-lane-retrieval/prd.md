# 实现记忆检索独立双 lane 召回

## 目标

让长期记忆检索真正拥有彼此独立的向量候选通道与关键词候选通道，再对两个候选集合做融合排序。用户用精确关键词查询时，即使目标记忆没有进入任何 pgvector 候选窗口，它仍应有机会进入最终公开 recall 结果。

该任务支持 Amadeus 的 Akashic-inspired memory system，公开证明路径是 `MemoryEngine.recall()` / `recall_memory`，而不是只证明排序 helper 能处理预先提供的 rows。

## 已确认事实

- 生产路径会对 raw/event/general 每个 query 分别调用 PostgreSQL pgvector 搜索，默认各取 `4 * max(top_k, request.limit)`，即 32 条候选，再按 memory id 合并。证据：`amadeus/memory/retriever.py:185-221`。
- PostgreSQL 搜索只按 `embedding <=> query_vector` 排序，并排除 `embedding IS NULL` 的记录；不存在独立关键词 SQL。证据：`amadeus/memory/postgres.py:350-417`。
- `rank_multi_query_rows()` 只接收上述向量候选并集，然后才在 Python 中计算 raw-query substring 分数和 RRF。证据：`amadeus/memory/ranking.py:150-205`。
- 因此，只要目标记忆不在任何向量候选窗口中，RRF 的输入就没有该 id，后续排序不可能恢复它。
- 现有 trace 的 `candidate_count` 和 `lane_counts.lexical` 都来自向量候选并集，不能证明 lexical lane 独立生成了候选。
- Akashic `memory2` 的长期记忆关键词 lane 是独立的 SQLite `summary LIKE '%term%'` 查询，不是 FTS、`tsvector`、BM25 或 trigram。证据：`../akashic-agent/memory2/retriever.py:115-128`、`../akashic-agent/memory2/store.py:1720-1827`。
- Akashic 的关键词 RRF 权重为 `0.5`。当向量结果填满 final top-k 时，lexical-only 结果通常仍无法进入最终列表；本任务不能把“独立入场”误当成“公开结果可见”。
- 历史 spec 已要求最终 RRF 融合独立 vector pool 与 raw-query lexical pool；pgvector 迁移只保留了 lexical score/trace，遗漏了独立候选生成，属于合同漂移。证据：`.trellis/spec/backend/quality-guidelines.md:306-313`。
- PostgreSQL 16 实验确认 plain `summary gin_trgm_ops` 可加速纯 ASCII/数字/标识符 `ILIKE`；当前 CJK bigram 以及包含短 CJK OR 条件的混合查询默认走 Seq Scan，索引性能不能冒充 lexical correctness。
- built-in `simple` FTS 会把无空格中文长串作为一个 token，`支付` 无法命中 `用户使用支付宝支付`，因此不满足当前 CJK substring 合同。

## 需求

- R1. 向量 lane 与 lexical lane 必须独立查询完整 eligible memory corpus；lexical lane 不得依赖记录先进入 pgvector 候选窗口。
- R2. 两个 lane 必须执行一致的 `user_id`、active status、memory type、scope 和 time 过滤，并在各自的 `LIMIT` 之前完成过滤。
- R3. lexical term extraction 对齐 Akashic：先提取全部 ASCII `[A-Za-z0-9_.-]{2,}` token，再提取中文、平假名、片假名连续块；CJK chunk 长度为 2～4 时保留完整，超过 4 时拆成相邻 bigram；应用 Akashic CJK stopwords，最后对“ASCII terms + CJK terms”的拼接序列稳定去重并最多保留 20 个 terms。该顺序不是跨字符类型的全局原文首次出现顺序。
- R4. 原始用户 query 驱动 lexical lane；event/general 等生成式假设只扩展向量 lane，不得制造 lexical-only 命中。
- R5. 融合层必须消费各 lane 的真实候选身份、原生分数和 rank。不得先合并 rows，再在 union 上重算 lane membership。
- R6. 最终结果按稳定 memory id 去重，并保留 vector-only、lexical-only 和双 lane 命中的真实 provenance。
- R7. 融合策略必须让 lexical rank-1 的高置信精确 lexical-only 命中在默认 final top-8 下具备实际可见性，而不只是进入一个随后被淘汰的 RRF 输入集合；lexical RRF weight 以 `1.0` 作为首轮确定性实验基线，最终参数由 retrieval eval 决定。
- R8. 保持现有 recall output、source references、evidence/citation、hotness、hypothesis、scope fallback 和时间过滤行为兼容。
- R9. trace 必须分别记录 vector、lexical、去重 union 和 final 的数量，并能解释每条结果的 lane rank、lane score 与融合贡献。
- R10. 两个 lane 的失败边界必须独立：lexical backend 禁用、无有效 terms 或查询失败时记录显式状态并可降级为 vector-only；vector embedding/search 失败时，lexical lane 仍可独立返回。任何降级都不得继续声称成功执行双 lane。
- R11. 通过真实 PostgreSQL 集成测试和公开 recall 行为测试证明修复，并在 canonical memory recall eval 中增加 lexical provenance 断言。

## 验收标准

- [x] 在真实 PostgreSQL 中插入至少一个位于所有 vector candidate windows 之外、但精确命中 raw query 稀有关键词的目标记忆时，`MemoryEngine.recall()` 或 `recall_memory` 的默认结果能返回该目标，并标记为 lexical-only。
- [x] term extraction 与 Akashic 一致：2～4 字 CJK chunk 保留完整，超过 4 字拆相邻 bigram；ASCII token 支持 `_`、`-`、`.`，长度至少为 2；stopword、稳定去重和 20-term 上限均有边界测试。
- [x] `支付宝` 不再沿用 Amadeus 当前的“所有长于 2 字都拆 bigram”行为，而是保留为完整 term；`支付宝支付` 则拆为相邻 bigram，并在去重后只保留首次出现的 `支付`。
- [x] `embedding IS NULL` 的 active 记忆也能通过精确关键词进入 lexical lane，证明该 lane 不依赖 embedding。
- [x] vector-only、lexical-only、双 lane 命中均可进入融合；同一 memory id 最终只出现一次。
- [x] 在默认 final top-8 的竞争 fixture 中，lexical rank-1 的高置信 lexical-only 目标实际可见；实验同时记录 `0.5` 参考行为与 `1.0` 基线行为，避免把“进入 RRF”误报为“用户可见”。
- [x] 只命中 event/general 假设文本而不命中 raw query 的记录不会成为 lexical-only 结果。
- [x] 两个 lane 的 user、status、type、scope、time 过滤测试通过，lexical lane 不会绕过隔离边界。
- [x] trace 保留现有兼容字段，并新增可验证的分 lane candidate count/status；`records[].signals["lanes"]` 反映真实候选来源，而不是 union 上的补算结果。
- [x] lexical 查询失败时仍可按设计返回 vector 结果，且 trace 包含明确的 degraded/fallback/error；禁用和无 terms 状态也可区分。
- [x] vector embedding/search 失败时，精确关键词记忆仍可通过 lexical-only 路径返回，且 trace 明确标记 vector lane 失败。
- [x] PostgreSQL 迁移可升级与回滚；关键词查询使用参数化值，并有真实中英文/标识符查询和索引存在性验证。
- [x] SQL pattern 对 `_`、`%` 和 escape character 做字面转义；`foo_bar` 不会错误命中 `fooxbar`。
- [x] 现有 source references、evidence/citation、hotness、hypothesis、scope fallback、time filter 测试保持通过。
- [x] canonical memory recall eval 断言 NULL-embedding lexical candidate 存在，且返回记录为 strict lexical-only provenance，避免以后只保留 `lexical_score` 就误报双 lane。
- [x] `.trellis/spec/backend/quality-guidelines.md` 和受影响的当前 interview claim 文档不再把共享向量候选上的关键词补算描述成独立双路召回。

## 非目标

- 不重写记忆写入、纠错、遗忘、replacement 或 consolidation 生命周期。
- 不实现 PostgreSQL 专用 BM25 扩展，也不把 PostgreSQL `ts_rank` 错称为 BM25。
- 不在本任务中把中文改成统一 trigram，也不引入额外中文分词器、`pg_bigm` 或自维护 ngram 列。
- 不在 Akashic 规则之外额外保留超过 4 字的完整 phrase；是否增加长 phrase term 由后续 recall eval 单独验证。
- 不把扩大 pgvector candidate limit 当作独立 lexical lane 的替代方案。
- 不迁移 Akashic 的 SQLite schema、全表 cosine fallback 或缺失的 trace 机制。
- 不改变 Telegram、outbound、scheduler、proactive 或 DriftRunner 边界。

## 决策状态

- 上述需求与验收标准已完成产品决策收敛，目前没有阻塞规划的开放问题。
- 任务已获得实现授权并处于 `in_progress`；实现与回归测试已经完成，正在执行最终质量门。
- 具体架构、数据库机制、融合差异与验证顺序见 `design.md`、`implement.md`。
