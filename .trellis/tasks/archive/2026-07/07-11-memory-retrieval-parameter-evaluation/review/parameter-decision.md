# 长期记忆检索参数决策

## 决策

**保留当前 Amadeus 生产默认参数，不发布本轮候选。**

当前默认值仍为：final top-k `8`；vector candidate `max(32, request_limit * 4)`；lexical candidate `max(30, request_limit * 2)`；lexical RRF weight `1.0`；RRF `k=60`；semantic threshold `0.35`；hotness alpha `0.20`；基础半衰期 `14d`；reinforcement strength `1.0`；emotional half-life scale `0.5`。

该结论不是“所有候选都更差”，而是：没有候选在保持关键分层质量的同时改善 Recall@8。探索候选在 holdout 的 MRR/nDCG 更高，但 development lexical-only 排名明显退化，且 bootstrap 区间不足以排除无改善；保守候选只减少候选暴露面，没有召回或排序收益。按照预注册的“证据互有胜负时保留 baseline”规则，不更改生产默认值。

## 冻结条件

- Development 参数选择 dataset hash：`2748c90799831d4c9eccabb8dc96c02c3cefa793cf530a1c92beec3a136571dd`
- Holdout qrels 补齐后 dataset hash：`b0566f9a99a94761f4ba40669d70c7d941933464feac8b81830d5047d38499c9`
- Holdout overlay 只新增 `103` 条 qrels，不改变 corpus、query、split 或参数。
- Selection snapshot：`2748c9079983/dataset/memory_retrieval_benchmark_v1-selection.yaml`，重新加载后 hash 为 `2748...`、judgments 为 `499`；严格 rebase 证明新 benchmark 恰好是该 snapshot 加 103 条 approved holdout qrels。
- Embedding：DashScope `text-embedding-v4`，`1024` 维只读 cache。
- Embedding cache fingerprint：`92d1d4cdb85e1acf31d5561866992fbeaf092da9f0db5ef1a0293c2e0231cbf5`
- Ranking time：`2026-07-12T04:00:00+00:00`
- PostgreSQL：本机 WSL Debian Docker 中的真实 PostgreSQL + pgvector/pg_trgm。
- LangSmith：未使用。
- 延迟：未测 P50/P95，不参与选择。
- Holdout practical-equivalence：解封前固定为 `1/18 = 5.56pp`。

Development artifacts 位于 `C:\Users\Zinc\.amadeus\evaluation\memory-retrieval-v1\2748c9079983`；最终 holdout artifacts 位于 `C:\Users\Zinc\.amadeus\evaluation\memory-retrieval-v1\b0566f9a99a9`。

## 分阶段结果

### Stage 0：基线与 Akashic 参考

| Profile | 硬门 | Recall@8 | Precision@8 | MRR@8 | nDCG@8 |
|---|---:|---:|---:|---:|---:|
| Amadeus baseline | 通过 | 0.9722 | 0.1562 | 0.8843 | 0.8906 |
| Akashic-inspired reference | 通过 | 0.9444 | 0.1528 | 0.8681 | 0.8691 |

Akashic 的 `vector=15 / lexical=30 / lexical weight=0.5 / k=60` 参考点在该 development 集上少召回一个 family，不能替代当前 baseline。这也验证了架构参考不等于参数真值。

### Stage 1：候选窗口

`vector=15/16/32/64` 与 `lexical=16/30/60` 共 12 组全部通过硬门，且总体 Recall/Precision/MRR/nDCG 相同。冻结两个不同取舍点：

- `window-v15-l16`：候选暴露面最小，保留 lexical weight `1.0`。
- `window-v32-l30`：保留当前有效窗口，避免只根据总体平均过早缩小候选。

### Stage 2：RRF 融合

两个窗口各比较 lexical weight `0.5/0.75/1.0/1.25/1.5` 与 RRF `k=10/30/60/90`，共 40 组。低 lexical weight 或较大的 `k` 多次把 Recall 从 `0.9722` 降为 `0.9444`。

冻结：

| Profile | Recall@8 | MRR@8 | nDCG@8 | Lexical-only MRR | Lexical-only nDCG |
|---|---:|---:|---:|---:|---:|
| `v32/l30/w0.75/k10` | 0.9722 | 0.8931 | 0.8910 | 0.1333 | 0.3449 |
| `v15/l16/w1/k60` | 0.9722 | 0.8843 | 0.8906 | 0.4167 | 0.5612 |

第一组提高总体 MRR，但明显压低 lexical-only 相关项的排名；第二组保留 lexical-only 排名质量，因此两个取舍点都继续验证。

### Stage 3：语义阈值

`0.25/0.30/0.35/0.40` 在两个分支上保持 Recall、all-required 与 Precision；`0.40` 的 nDCG 更高，因此冻结两个 `threshold=0.40` profile。

`threshold=0.45` 在两个分支上都让 `stress_cross_user_region_zh` 的跨 scope 私密口令进入 top-8，触发 `dangerous_hit` 硬门。即使其总体 MRR/nDCG 更高，也必须淘汰。

### Stage 4：hotness

按用户批准的收缩范围，本轮不做大规模 hotness sweep，只保留并验证 `alpha=0.20 / half-life=14d / reinforcement=1.0 / emotional scale=0.5` baseline。两个分支均通过硬门和既有 hotness pair case。

因此，本任务证明的是“当前 hotness baseline 没有在 finalist 路径上造成回归”，不是“0.20/14d 已被充分搜索并证明最优”。

### Stage 5 development

| Profile | 硬门 | Recall@8 | Precision@8 | MRR@8 | nDCG@8 |
|---|---:|---:|---:|---:|---:|
| `amadeus-baseline` | 通过 | 0.9722 | 0.1562 | 0.8843 | 0.8906 |
| `v32/l30/w0.75/k10/t0.40` | 通过 | 0.9722 | 0.1562 | 0.8931 | 0.8937 |
| `v15/l16/w1/k60/t0.40` | 通过 | 0.9722 | 0.1562 | 0.8889 | 0.8936 |

三组在查看 holdout 前冻结。第一次 holdout collect-pool 只收集 unknown，不计算胜负；103 条 qrels 全部批准后，通过 `rebase-shortlist` 只更新 dataset hash，三组参数保持不变。

## Locked holdout

最终 completeness 为 `unknown_pairs=0`。正式 holdout 只运行一次，之后没有根据结果继续调参。

| Profile | 硬门 | Recall@8 | All required | Precision@8 | MRR@8 | nDCG@8 | Avg union |
|---|---:|---:|---:|---:|---:|---:|---:|
| `amadeus-baseline` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9167 | 0.9325 | 37.39 |
| `v32/l30/w0.75/k10/t0.40` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9524 | 0.9584 | 37.39 |
| `v15/l16/w1/k60/t0.40` | 通过 | 1.0000 | 1.0000 | 0.1339 | 0.9167 | 0.9319 | 21.11 |

逐 family 明细见 `review/locked-holdout-paired-analysis.md`。14 个有正例的 family 参与 Recall/MRR/nDCG；4 个 abstention family 按定义不进入 Recall 分母。解封前固定的 `5.56pp` 规则仍用于决策；本次所有 profile 的 Recall 差值恰好为 0，因此 14/18 分母差异不改变结论。

| Candidate - baseline | Recall Δ / 95% CI | MRR Δ / 95% CI | nDCG Δ / 95% CI |
|---|---:|---:|---:|
| `v32/l30/w0.75/k10/t0.40` | 0.0000 / [0.0000, 0.0000] | 0.0357 / [0.0000, 0.1071] | 0.0259 / [-0.0035, 0.0803] |
| `v15/l16/w1/k60/t0.40` | 0.0000 / [0.0000, 0.0000] | 0.0000 / [0.0000, 0.0000] | -0.0006 / [-0.0019, 0.0000] |

探索组的总体排序改善主要来自 `holdout_stress_conflict`，同时 `holdout_stress_homonym` 的 nDCG 下降；其 nDCG 区间跨 0，并且 development lexical-only 分层退化。保守组候选更少，但没有 Recall/MRR 改善，nDCG 略低。两组都未达到改变默认参数所需的稳定证据。

## 安全与残余风险

- 三组的 user/status/replacement/scope/type/time、provenance、dangerous-zero-hit、lane status 与两次稳定性检查全部通过。
- `threshold=0.45` 已被安全硬门淘汰，不能因更高平均排序指标恢复。
- Development 和 holdout 的 no-answer false-positive 均为 `1.0`：当前 retrieval 会在 abstention query 上返回普通记忆。三组参数都没有改善这一点；它更像“何时不注入/何时拒答”的产品机制问题，不能靠本轮 RRF 数字解决。
- Holdout 没有 lexical-only family，无法在 locked split 独立确认探索组的 lexical-only 退化是否复现。这正是保留 baseline 而非宣布探索组获胜的原因之一。
- Hotness 只验证 baseline，没有得出替代 alpha/半衰期参数结论。

## 发布与后续

- 不修改 `MemoryRetrievalParameters` 默认值，也不扩大 `.env` / `RuntimeConfig` 配置面。
- 旧值即当前值，不需要生产回滚变更；实验 runner 仍可显式注入所有候选 profile。
- 后续优先补充 lexical-only holdout families 和真实 dogfooding 失败样本，再开新 dataset version；不能回改已经解封的 v1 holdout。
- no-answer false-positive 应单独评估 context injection/answer abstention 合同，而不是继续扫 RRF 参数。
- 若以后需要验证“检索改善是否改善最终回答”，再创建 LangSmith answer-level A/B task；本任务不使用 LangSmith。
