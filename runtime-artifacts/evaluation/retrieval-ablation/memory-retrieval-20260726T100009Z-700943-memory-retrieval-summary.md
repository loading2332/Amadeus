# 长期记忆检索参数实验

- 实验：`memory-retrieval-20260726T100009Z-700943`
- Stage：`unspecified`
- 数据集：`memory-retrieval-v1`
- 数据集哈希：`fa2d25ee01dcfa2a511236d27ccbc079f6256bba02513cd36603860cf0d429a1`
- split：`development`
- 正式实验：`false`
- 延迟指标：未采集（本任务只比较召回质量与可靠性）

| Profile | 硬门 | Recall@8 | Precision@8 | MRR@8 | nDCG@8 |
|---|---:|---:|---:|---:|---:|
| ablation-0-vector-raw | 通过 | 0.8889 | 0.1424 | 0.8843 | 0.8581 |
| ablation-1-dual-query | 失败 | 0.9167 | 0.1493 | 0.9167 | 0.8997 |
| ablation-2-lexical-rrf | 失败 | 0.9722 | 0.1562 | 0.8843 | 0.8984 |
| ablation-3-full-baseline | 通过 | 0.9722 | 0.1562 | 0.8843 | 0.8906 |

正式参数选择必须另行应用预注册的分层决策规则。
