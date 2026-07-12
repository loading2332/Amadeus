# Stage 0/1 development 正式结果

## 冻结输入

- Dataset hash：`4daf138fcd02540f13bf8b70eb593ad90e769a224c0b2466cd5344ceacad8a7b`
- Embedding cache fingerprint：`92d1d4cdb85e1acf31d5561866992fbeaf092da9f0db5ef1a0293c2e0231cbf5`
- Ranking time：`2026-07-12T04:00:00+00:00`
- Experiment ID：`memory-retrieval-v1-4daf138fcd02-development`
- Stage 0/1 completeness：均为 `unknown_pairs=0`
- PostgreSQL experiment user 残留：每次运行后均为 `0`

## Stage 0

| Profile | 硬门 | Recall@8 | Precision@8 | MRR@8 | nDCG@8 | Dangerous families |
|---|---:|---:|---:|---:|---:|---:|
| `amadeus-baseline` | 失败 | 0.9722 | 0.1562 | 0.8690 | 0.8834 | 7 |
| `akashic-inspired-reference` | 失败 | 0.9167 | 0.1493 | 0.8634 | 0.8641 | 6 |

## Stage 1

12 个 `vector=15/16/32/64 × lexical=16/30/60` profile 全部为：

- `Recall@8=0.9722`
- `Precision@8=0.1562`
- `MRR@8=0.8690`
- 每个 profile 均有 7 个 `dangerous_hit` family，未通过安全硬门
- vector 15/16 的 `nDCG@8=0.8850`，vector 32/64 的 `nDCG@8=0.8834`

由于预注册规则要求安全硬门先于平均指标，不能因为 Recall 较高就冻结一个失败 profile。Stage 1 没有合法 shortlist，Stage 2 不得静默回退 baseline。

## 根因分类

| 类型 | Families | 结论 |
|---|---|---|
| Scope fixture 缺失 | `project_identifier_lexical_mixed`、`personal_airport_pickup_mixed`、`project_deploy_rollback_mixed`、`stress_scope_channel_zh`、`personal_unknown_wifi_mixed`、`stress_forgotten_secret_zh` | query 或 memory 缺少本应存在的 channel/chat，使“另一个群的口令”在测试数据中变成全局可检索项。属于 benchmark fixture 缺陷，不能归因于候选窗口参数。 |
| Lifecycle fixture 冲突 | `project_current_release_version_mixed` | `project_release_date_related` 描述旧版 0.3.2，但仍为 active；同一数据集中另一条旧版记忆已经 superseded。属于 corpus 生命周期状态不一致。 |

正式 artifact 位于本机：

- `%USERPROFILE%\.amadeus\evaluation\memory-retrieval-v1\4daf138fcd02\stage-0\formal`
- `%USERPROFILE%\.amadeus\evaluation\memory-retrieval-v1\4daf138fcd02\stage-1\formal`

