# RRF 与 lexical-only 最终可见性研究

## 基础合同

标准 reciprocal rank fusion 对每个独立 retriever 的结果使用：

```text
score(document) = sum(1 / (k + rank_in_retriever))
```

Elasticsearch 官方实现强调：

- 子 retriever 独立执行后再融合；
- 默认 `rank_constant = 60`；
- child retrievers 使用 equal weight；
- `rank_window_size` 是每个 retriever 提供给 RRF 的窗口，final `size` 再截断融合结果；
- explain 会分别展示每个 retriever 的 rank 与 contribution。

来源：[Elasticsearch Reciprocal Rank Fusion](https://www.elastic.co/docs/reference/elasticsearch/rest-apis/reciprocal-rank-fusion)。

这与本任务的两个核心要求一致：candidate set 必须独立，trace 必须保留逐 lane contribution。

## Akashic/Amadeus 当前权重问题

当前常量：

```text
k = 60
vector weight = 1.0
lexical weight = 0.5
```

lexical rank 1 的最高单 lane 分数：

```text
0.5 / (60 + 1) = 0.00819672
```

Amadeus 当前单 query 默认有 32 个 vector candidates。vector rank 32：

```text
1.0 / (60 + 32) = 0.01086957
```

因此，即使新增独立 lexical SQL，只要继续使用 `0.5`，lexical rank 1 仍排在全部 32 个 vector-only candidates 之后，绝不可能进入默认 final top 8。

## 权重下界

要让 lexical rank 1 严格超过 vector rank `N`：

```text
w / (k + 1) > 1 / (k + N)
w > (k + 1) / (k + N)
```

当 `k=60`：

| Final top-k N | weight 下界 |
|---:|---:|
| 1 | `> 1.000000` |
| 2 | `> 0.983871` |
| 8 | `> 0.897059` |
| 16 | `> 0.802632` |

本地确定性计算把一个 lexical rank-1 candidate 与 32 个 vector-only candidates 融合：

| lexical weight | lexical 最终位置 |
|---:|---:|
| 0.5 | 33 |
| 0.9 | 8 |
| 1.0 | 1 或 2（与 vector rank 1 同分，取决于稳定 tie-break） |

## 决策

- lexical weight 改为 `1.0`，回到标准 RRF 的 equal-lane contribution。
- `k=60` 保持不变。
- lexical candidate window `max(30, final_limit * 2)`，满足 window 大于 final limit 的基本条件。
- 稳定 tie-break 必须显式定义；不能依赖 set iteration。
- 不承诺任何弱 lexical hit 必然入选。验收锁定的是稀有、精确、lexical rank-1 候选在默认 final top 8 下可见。
- 若未来必须支持 `limit=1` 且保证 lexical 优先，需要单独定义 exact-match pinning/quota；仅 equal-weight RRF 无法在 rank-1 tie 时表达该产品偏好。

## 测试要求

- 用至少 32 个 vector-only decoys + 1 个 lexical-only target 锁定默认 final top 8。
- 单独测试 weight `0.5` 会失败，避免测试因 vector threshold 过滤掉 decoys 而形成假绿。
- 双 lane candidate 的两项 contribution 都必须出现在 trace。
- final ordering 的 tie-break 使用稳定字段，并有重复运行一致性测试。
