# 记忆检索 Feature Ablation（development split）

- run_id: `memory-retrieval-20260726T100009Z-700943`
- 日期: 2026-07-26
- 脚本: `scripts/run_retrieval_ablation.py`
- 数据: 冻结 benchmark `memory_retrieval_benchmark_v1.yaml`（60 families / 602 judgments），仅 development split（42 families，其中 36 个有正例、6 个 abstention）
- 环境: 与正式参数实验一致 —— DashScope `text-embedding-v4` 1024 维只读 cache、ranking time `2026-07-12T04:00:00+00:00`、真实 PostgreSQL + pgvector/pg_trgm、determinism 双跑校验
- 性质: informal 消融对照。不触碰 locked holdout，不改变生产默认参数

## 口径（池化假设）

消融配置会把从未进入过正式实验 top-8、因此没有人工标注的 memory 排进结果。
本次给全部未标注 (query, memory) 组合补 relevance=0 临时 judgment：

- Recall@8 / MRR@8 / nDCG@8 相对冻结 qrels 是精确值（未标注项 gain=0，不改变 relevant 集合与 ideal DCG）；
- Precision@8 对未标注项按不相关计，是下界；
- 实际进入 top-8 的未标注 pair 共 **85 个（去重）**，清单见
  `memory-retrieval-20260726T100009Z-700943-memory-retrieval-results-unknown-pairs.md`，
  人工补标合并 qrels 后可升级为正式口径。

## 逐步消融结果（36 个有正例 family，family 平均）

| Profile | Recall@8 | MRR@8 | nDCG@8 | Lexical-only Recall | Hard gate |
|---|---:|---:|---:|---:|---:|
| 0. vector-raw（仅原始 query 向量） | 0.8889 | 0.8843 | 0.8581 | 0.0000 | 42/42 |
| 1. + dual-query 假设改写 | 0.9167 | 0.9167 | 0.8997 | 0.0000 | 41/42 |
| 2. + lexical 通道 / RRF 融合 | 0.9722 | 0.8843 | 0.8984 | 0.6667 | 41/42 |
| 3. + hotness 融合（= 生产 baseline） | **0.9722** | 0.8843 | 0.8906 | 0.6667 | **42/42** |

Profile 3 精确复现正式实验 development 已发布数字（Recall 0.9722 / MRR 0.8843 / nDCG 0.8906），验证消融口径与正式口径一致。

## 逐 family 归因

| 配置 | 未召回 family | 说明 |
|---|---|---|
| vector-raw | personal_dietary_update(0.5)、personal_reply_language(0.5)、project_identifier_lexical(0)、personal_two_character_cjk(0)、personal_airport_pickup(0) | 纯向量既漏语义改写 family，也漏精确标识符 family |
| + dual-query | 修复 dietary_update、reply_language | 双假设补齐语义泛化，Recall +2.78pp，MRR 同时到达全场最高 0.9167 |
| + lexical/RRF | 修复 project_identifier_lexical、personal_two_character_cjk | 精确标识符与短 CJK 词由词法通道找回，Recall +5.56pp，lexical-only slice 0 → 0.6667；代价是总体 MRR 从 0.9167 回落到 0.8843 |
| + hotness | 无 Recall 变化 | 见下方安全发现 |
| 全配置残留 | personal_airport_pickup | 已知残留 badcase，与正式实验一致 |

## 意外发现：hotness 与安全硬门

关闭 hotness 的两个中间配置（profile 1、2）在 `stress_cross_user_region_zh`
上触发 `dangerous_hit` 硬门——一条跨 scope 私密记忆进入 top-8；开启 hotness
后该记忆因时间衰减被压出 top-8，硬门恢复通过。

两个含义：

1. hotness 在本集合上不只是排序偏好信号，还实际参与压制过期的危险记忆；
2. 安全硬门必须在每个候选配置上独立重验，不能只在最终配置上验一次——
   这与正式实验淘汰 `threshold=0.45` 的教训一致。

## 结论（简历/面试口径）

在冻结 development 集上，以 raw-query + vector-only 为基线：

- 完整方案 Recall@8 从 **0.8889 提升到 0.9722**（+8.33pp，36 个 family 多找回 3 个）；
- 其中 dual-query 贡献 +2.78pp（语义改写类），lexical/RRF 贡献 +5.56pp（版本号、短 CJK 词等精确匹配类），hotness 召回中性但守住安全硬门；
- lexical-only 切片从 0 提升到 0.6667，验证"修复纯向量精确词 badcase"的表述；
- 残留缺口：personal_airport_pickup 未召回；no-answer false-positive 全配置仍为 1.0（abstention 机制缺口，与本消融无关）。

限制：development split、informal 池化口径、85 个未标注 pair 待补标；
未测延迟；holdout 未使用（协议保持 locked）。
