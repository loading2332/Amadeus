# Akashic 双 lane 参考核对

## 可迁移的数据流

Akashic `memory2` 的实际流程是：

```text
raw query + aux queries -> vector candidate pool
raw query               -> independent keyword candidate pool
two pools               -> weighted RRF -> final top-k
```

- `../akashic-agent/memory2/retriever.py:97-128`：raw/aux 进入向量 lane，raw 单独进入关键词 lane。
- `../akashic-agent/memory2/retriever.py:176-224`：向量 id max-pooling；关键词 limit 为 `max(30, top_k * 2)`。
- `../akashic-agent/memory2/store.py:1720-1827`：关键词查询直接扫描 eligible `memory_items`，使用参数化 OR-LIKE 与命中词比例。
- `../akashic-agent/memory2/retriever.py:520-567`：两组候选按 id 做 weighted RRF。

## Akashic term extraction 的实际合同

`../akashic-agent/memory2/retriever.py:485-517` 的 `_extract_terms()` 不是通用中文分词器，而是确定性的正则与窗口规则：

- ASCII：提取长度至少为 2 的 `[A-Za-z0-9_.-]` 连续 token；
- CJK：提取长度至少为 2 的 `[一-鿿぀-ヿ]` 连续 chunk；
- 2～4 字 CJK chunk 保留完整；超过 4 字才拆相邻 bigram；
- 应用 `_CJK_STOPWORDS`；先完成 ASCII pass，再完成 CJK pass，最后对两组 terms 的拼接序列稳定去重并截断至 20 个。这里不是跨字符类型的全局原文首次出现顺序。

所以“对齐 Akashic CJK”不等于“所有中文都 bigram”，也不等于“中文统一 trigram”。例如 `支付宝` 保留完整，`支付宝支付` 才拆为 `支付`、`付宝`、`宝支`，重复 term 只保留第一次。

## 它实际没有使用的机制

Akashic 长期记忆关键词 lane 不是 PostgreSQL FTS、`tsvector`、BM25 或 trigram，而是 SQLite：

```sql
summary LIKE '%term_1%' OR summary LIKE '%term_2%'
```

Akashic session message search 另有 SQLite FTS5 trigram/BM25，但它不属于长期记忆 `memory2`，不能混作迁移依据。

## 可迁移合同

- 两个 lane 各自从完整 eligible corpus 生成候选。
- raw query 驱动 lexical；生成式 query 只扩展 vector。
- status/type/scope/time 过滤在每个 lane 的 limit 前执行。
- 多向量 query 命中同一 id 时保留最佳 vector hit，不重复累加 RRF。
- 关键词候选量可以高于 final top-k，以免过早截断。
- vector embedding 失败不应天然消灭 lexical recall。

## 不应照搬的限制

Akashic 使用 `k=60`、vector weight `1.0`、keyword weight `0.5`。默认 `top_k=8` 时：

```text
lexical rank 1 = 0.5 / 61 = 0.00820
vector rank 8  = 1.0 / 68 = 0.01471
```

向量结果填满时，最强 lexical-only 结果仍低于最弱 vector-only 结果。因此 Akashic 证明了独立候选生成，但没有证明精确关键词能进入 final top-k。

其他不足：

- vector item 覆盖 keyword item 时会丢失 `keyword_score`；
- 注入阶段可能再按原始 `score` 排序，不能保证 RRF 顺序贯穿；
- RRF tie-break 不稳定；
- 只有 debug lane count，没有可供公共行为验证的逐 lane trace。

## Amadeus 项目特定扩展

- PostgreSQL schema/index/extension 需要 Amadeus 自己设计；Akashic 没有对应机制。
- 为满足用户可见 recall，Amadeus 需要校准 lexical RRF 权重或设置 lane-aware admission，不能机械复制 `0.5`。
- Amadeus 必须保留结构化 lane provenance、稳定 tie-break、source reference 与公开 trace。
