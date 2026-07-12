# Akashic 检索与评测机制研究

## 研究目的

本文件只回答两个问题：

1. Akashic 当前真正运行的长期记忆检索流程是什么；
2. 哪些设计合同值得迁移，哪些参数只是未经验证的默认值，不能原样照抄。

研究日期：2026-07-11。Akashic 仓库位于 `../akashic-agent`，本次只读检查源码与测试，没有修改该仓库。

## 结论摘要

Akashic 已经具备独立的 vector 候选通道和 keyword 候选通道，但它不是一个已经完成参数验证的“双 lane 最优实现”。公开 `answer` 检索的实际流程是：

```text
raw query + event hypothesis + general hypothesis
-> 每条 query 各取 vector top-15
-> 按 memory id 合并，保留最高 vector score

raw query
-> Akashic tokenizer
-> keyword top-30

vector union + keyword candidates
-> weighted RRF，k=60，keyword weight=0.5
-> RRF top-15
-> final top-8
```

值得迁移的是独立候选通道、raw query 保留、扩展 query 只影响 vector、两 lane 对称过滤、独立失败降级和 rank-based fusion。不能照抄的是 `15/30/0.5/60/0.35/0.20/14d` 这些数字，因为 Akashic 没有 retrieval Gold Set、参数 sweep 或 holdout 证据。

更关键的是，`keyword_weight=0.5` 在 vector top-15 填满时会让 lexical-only 候选完全没有进入 RRF top-15 的机会。Akashic 有独立 keyword candidate lane，但默认权重使它无法稳定完成“vector 漏召回时由关键词补回”的产品目标。

## 证据优先级

本研究按以下顺序判断事实：

1. Akashic 当前运行源码；
2. 与源码对应的测试；
3. Akashic eval harness；
4. README 或历史设计文档。

若文档声称存在 BM25，而运行代码实际使用 SQLite `LIKE`，以代码为准。

## 1. 真正生效的 query 路径

### 1.1 `answer` 主动召回路径

`plugins/default_memory/engine.py:1131` 的 `_query_answer()` 并发生成两条辅助查询：

- `event` hypothesis：把问题改写成可能发生过的事件描述；
- `general` hypothesis：把问题改写成更一般的语义描述。

随后：

- raw query 与两条 hypothesis 都进入 vector lane；
- keyword lane 只使用 raw query；
- vector 的实际候选窗口是 `max(request.limit, 15)`；
- semantic threshold 固定为 `0.35`；
- 工具默认最终 `limit=8`。

源码证据：

- `../akashic-agent/plugins/default_memory/engine.py:55`
- `../akashic-agent/plugins/default_memory/engine.py:57`
- `../akashic-agent/plugins/default_memory/engine.py:1131`
- `../akashic-agent/plugins/default_memory/engine.py:1141`
- `../akashic-agent/agent/tools/recall_memory.py:48`

### 1.2 多条 vector query 如何合并

每条 query 都独立做一次 top-k vector search。相同 memory 若被多条 query 找到，只保留最高的 vector score，再参与后续排序。

这意味着 `top-15` 是“每条 vector query 的窗口”，不是三条 query 合计只取 15 条。三个 lane 的并集可能大于 15，最后才由 RRF 截断。

源码证据：

- `../akashic-agent/memory2/retriever.py:145`
- `../akashic-agent/memory2/retriever.py:158`
- `../akashic-agent/memory2/retriever.py:463`

### 1.3 不能把两个 QueryRewriter 概念混在一起

Akashic 还有 `memory2/query_rewriter.py`，它会生成 episodic query 与 procedure query。但全仓引用显示，它目前只被测试使用，默认生产 pipeline 没有实例化它。

因此，当前真正生效的“双改写”是 `answer` 路径中的 `event/general hypothesis`，不是 `QueryRewriter` 类。Amadeus 在迁移和评测时必须以实际调用图为准，不能把“仓库里存在的类”误写成“生产中正在运行的机制”。

### 1.4 被动 context 路径并不完全相同

默认被动 context pipeline 主要把原始用户消息交给 memory query，默认 `limit=8`，并不会自动执行 `answer` 路径的两条 hypothesis。

源码证据：

- `../akashic-agent/agent/retrieval/default_pipeline.py:31`
- `../akashic-agent/core/memory/engine.py:104`

所以评测必须明确自己测的是哪个公开行为。不能把主动 `recall_memory(intent=answer)` 的结果直接当作被动 context injection 的结果。

## 2. Keyword lane 的真实实现

### 2.1 Tokenizer

`memory2/retriever.py:494` 的 `_extract_terms()` 使用以下规则：

- ASCII token：正则 `[A-Za-z0-9_.-]{2,}`；
- CJK 片段长度 2 到 4：保留整个片段；
- CJK 片段长度大于 4：拆成相邻 bigram；
- 过滤一组 CJK stopwords；
- 稳定去重；
- 最多保留 20 个 term。

这正是 Amadeus 已决定迁移的 Akashic tokenizer 合同。它兼顾：

- 稀有标识符和版本号的精确命中；
- 短中文 phrase 的整体匹配；
- 长中文片段通过 bigram 获得局部匹配能力。

### 2.2 存储查询不是 FTS 或 BM25

Akashic 的 `keyword_search_summary()` 对每个 term 生成：

```sql
summary LIKE '%term%'
```

多个 term 用 OR 连接，然后按以下顺序排序：

```text
命中的 term 数量 DESC
-> reinforcement DESC
-> id ASC
```

源码证据：

- `../akashic-agent/memory2/store.py:1720`
- `../akashic-agent/memory2/store.py:1755`
- `../akashic-agent/memory2/store.py:1776`

它没有独立的 PostgreSQL FTS、`tsvector`、BM25、trigram candidate channel，也没有对应的 summary 搜索索引。因此 Amadeus 使用 PostgreSQL `ILIKE + pg_trgm GIN` 是“保留 Akashic tokenizer 和 substring 语义，同时换成适合 PostgreSQL 的加速实现”，不是偏离 Akashic 的产品合同。

### 2.3 Keyword candidate window

Akashic 使用：

```text
keyword_limit = max(30, 2 * actual_top_k)
```

在默认 `actual_top_k=15` 时，keyword window 为 30。

源码证据：

- `../akashic-agent/memory2/retriever.py:21`
- `../akashic-agent/memory2/retriever.py:225`

## 3. RRF 从第一性原理看

### 3.1 为什么使用 RRF

vector score 与 keyword coverage score 不是同一种量：

- vector score 表示 embedding 空间中的相似程度；
- keyword score 表示命中了多少 term；
- 两者的数值范围和分布没有天然可比性。

RRF 不直接相加原始 score，而只使用各 lane 中的排名：

```text
RRF(d) = Σ_lane weight_lane / (k + rank_lane(d))
```

这样可以绕过“不同 score 尺度如何归一化”的问题。

### 3.2 Akashic 默认参数

Akashic 的默认值是：

```text
k = 60
vector weight = 1.0
keyword weight = 0.5
```

源码证据：

- `../akashic-agent/memory2/retriever.py:19`
- `../akashic-agent/memory2/retriever.py:20`
- `../akashic-agent/memory2/retriever.py:520`

### 3.3 为什么 `0.5` 会阻断 lexical-only 补召回

keyword-only 第一名的分数：

```text
0.5 / (60 + 1) = 0.00820
```

vector-only 第 15 名的分数：

```text
1.0 / (60 + 15) = 0.01333
```

所以当 vector lane 返回 15 条时，最强 keyword-only 候选仍低于最弱的 vector top-15 候选。RRF 随后只保留 top-15，它就会被截掉，更不可能进入 final top-8。

可以把这个条件写成一般公式。若 keyword 第一名要超过 vector 第 `N` 名，需要：

```text
w_keyword / (k + 1) > 1 / (k + N)

w_keyword > (k + 1) / (k + N)
```

代入 `k=60, N=15`：

```text
w_keyword > 61 / 75 = 0.8133
```

因此：

- `0.5` 必然不够；
- `1.0` 能让 keyword rank-1 超过 vector rank-15；
- 但 `1.0` 是否能提供整体最优 Recall/Precision，仍需 Gold Set，而不是只靠这一个边界例子决定。

这个计算解释了 Amadeus 为什么先把 lexical weight 设为 `1.0` 作为可见性基线，也解释了为什么还必须做参数实验。

### 3.4 Candidate top-k 是不可逆的第一道门

RRF 只能给已经进入候选集合的 memory 排名。若相关 memory：

- 没进入 vector top-k；
- 也没进入 lexical top-k；

它就不在 RRF 的输入里，后续任何权重都救不回来。

因此参数实验必须把问题拆成两层：

1. candidate layer：相关 memory 是否进入 lane 候选并集；
2. final layer：进入候选后，是否通过 RRF 排进 final top-8。

只看 final Recall@8 会知道失败了，却不知道失败发生在候选窗口还是融合排序。

## 4. Hotness 的真实公式和边界

Akashic 的 hotness 为：

```text
frequency = sigmoid(log1p(reinforcement))

effective_half_life =
14 天 * (1 + 0.5 * emotional_weight / 10)

recency = exp(-ln(2) * age_days / effective_half_life)

hotness = frequency * recency

final_vector_score =
0.8 * semantic_score + 0.2 * hotness
```

源码证据：

- `../akashic-agent/memory2/store.py:161`
- `../akashic-agent/memory2/store.py:175`
- `../akashic-agent/memory2/store.py:179`
- `../akashic-agent/memory2/store.py:181`
- `../akashic-agent/memory2/store.py:1324`
- `../akashic-agent/plugins/default_memory/engine.py:606`

重要边界：

- semantic threshold 在 hotness 融合之前执行；不相关 memory 不能只靠“热”越过语义门；
- hotness 只改变 vector lane 内排序；
- keyword lane 仅用 reinforcement 作同 coverage 下的 tie-break；
- `emotional_weight` 不直接加分，而是延长半衰期；默认最大从 14 天延长到 21 天；
- `alpha=0.20` 与 `half-life=14d` 都是生产硬编码，不是实验结论。

## 5. Akashic 评测覆盖了什么

Akashic 有两套端到端 harness：

### 5.1 LongMemEval adapter

流程是：

```text
回放历史
-> consolidation / post-response
-> 运行真实 AgentLoop 回答问题
-> token-F1 / exact match / LLM judge
```

它验证最终回答，但没有按 memory id 标注 Amadeus 参数实验所需的 qrels。

### 5.2 PersonaMem adapter

它回放 persona history，再以 multiple-choice accuracy 检查个性化回答。

### 5.3 没有覆盖的内容

Akashic 当前没有：

- retrieval qrels；
- Recall@K、Precision@K、MRR、nDCG；
- lexical-only outside-vector-window 回归；
- candidate layer 与 final layer 的分层指标；
- 完整 lane provenance；
- PostgreSQL P50/P95；
- 参数 sweep、dev/holdout 或 dataset hash；
- LangSmith 集成。

当前 checkout 也没有可直接运行的 LongMemEval/PersonaMem 数据文件；这些 harness 依赖外部下载。因此 Akashic 能给 Amadeus 架构参考和端到端验证思路，不能直接给出 Amadeus 的最优参数。

## 6. 已发现的 Akashic 风险

### 6.1 RRF 顺序在 context injection 前被破坏

`memory2/retriever.py:300` 又按通用 `score` 字段排序。vector item 的 `score` 与 keyword-only item 的 coverage score 不是同一尺度，这会覆盖 RRF 已经得到的融合顺序。

Amadeus 前置任务已经明确保留 final fusion order，不应迁移这个行为。

### 6.2 Provenance 不完整

Akashic 虽计算 `rrf_score`，但 `_build_record()` 主要把 `extra_json` 转成 `signals`，没有稳定公开每个 lane 的 rank、contribution 和 status。

Amadeus 已经补齐：

- `lanes`；
- `vector_rank` / `lexical_rank`；
- 每个 lane 的 RRF contribution；
- vector/lexical/union/final candidate counts；
- lane status 与独立降级状态。

### 6.3 测试没有证明 keyword lane 的主要价值

现有测试证明 vector 为空时 keyword 可以返回，也证明 vector 填满时结果维持 vector 顺序；它没有证明“vector 窗口外的 lexical-only memory 能进入 final top-8”。这正是 Amadeus 已新增的 raw-query / lexical-only regression 所覆盖的行为。

## 7. 对 Amadeus 参数实验的直接影响

### 必须保留的合同

- raw query 永远存在；
- event/general hypothesis 只进入 vector lane；
- lexical 只吃 raw query，避免 LLM 扩展制造虚假字面命中；
- vector 与 lexical 独立取候选；
- 两 lane 使用相同 user/status/type/scope/time 过滤；
- 两 lane 独立失败降级；
- 融合只比较 rank，不直接比较异构原始 score；
- context injection 保留最终融合顺序；
- retrieval eval 与 answer eval 分层。

### 必须通过实验回答的问题

- vector candidate window 是否应包含 Akashic 的 `15` 基线；
- lexical window `30` 是否过大或过小；
- lexical weight 是否保持 `1.0`，还是在可见性和噪声之间选择其他值；
- RRF `k=60` 是否适合 Amadeus 的候选深度；
- threshold `0.35` 是否漏掉必要语义候选；
- hotness `alpha=0.20`、14 天半衰期和 emotional scale 是否符合实际长期助理场景。

### 参数合同需要修订的地方

只提供 `vector_candidate_multiplier` 无法精确表达 Akashic 的 `max(limit, 15)`。实验 profile 应能表示一个绝对 floor 或显式 effective window，例如：

```text
vector_limit = max(vector_candidate_floor, request_limit * multiplier)
```

这样在 final top-8 固定时可以比较 `15/16/32/64`，而不是把 15 四舍五入成 16 后声称已经复现 Akashic。

## 8. 最终判断

Akashic 是本任务的架构基线，不是参数真值来源。

```text
迁移 Akashic 的机制合同
!=
复制 Akashic 的硬编码数字
```

Amadeus 已经先完成独立双 lane，这解决了“相关 memory 是否有资格成为候选”的结构问题。当前任务接下来要用审核后的 qrels、真实 PostgreSQL 和冻结变量的实验，解决“候选窗口、RRF、threshold 与 hotness 应取什么值”的证据问题。

