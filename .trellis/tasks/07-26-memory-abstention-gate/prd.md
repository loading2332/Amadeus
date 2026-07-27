# PRD：记忆检索 abstention 置信度门

## 背景

当前检索管线是"过语义阈值的候选按分数取 top-k"，对任何查询都会返回排名前 8 的记忆，
没有"本次没有可信结果、返回空"的机制。冻结基准（v1，60 families / 602 qrels）中
`expected_abstention` 家族的 no-answer false-positive 在 development 与 holdout 均为
**1.0**：无答案查询 100% 误注入不相关记忆。07-26 的 feature ablation 进一步确认该缺口
与检索配置无关——从纯向量到完整方案的全部 4 个配置 FP 均为 1.0。

危害：不相关记忆被注入 prompt 后，模型会基于"长期记忆里有这些"编造答案，是幻觉的
直接放大器。07-11 参数决策文档已明确：该问题不能靠继续调 RRF 参数解决，需要独立的
拒绝机制（`.trellis/tasks/archive/2026-07/07-11-memory-retrieval-parameter-evaluation/review/parameter-decision.md`）。

## Goal

在 recall 返回与 context 注入之间加入置信度门（abstention gate）：置信度不足时返回
空结果集，而不是硬凑 top-8。

## Requirements

- 门位于检索层唯一咽喉（`engine.recall()` 所走的 retriever 返回路径），使 runtime
  注入与 benchmark 计量自动共享同一行为。
- 门决策基于可解释信号（top-1 语义分、top-1/top-2 间隔、词法 lane 锚点等），不引入
  额外 LLM 调用。
- 门参数纳入 `MemoryRetrievalParameters`，参与 fingerprint；存在"完全关闭"取值。
- 阈值在 development split 上校准，选择过程留档、可复算。

## Acceptance Criteria

> **2026-07-27 修订**：步骤 1 分布分析（`research/abstention-distribution.md`）证明
> 检索层分数门无法让 any-hit 口径的 no_answer_false_positive 显著下降（基准的
> HyDE 陷阱需要实体级理解才能识别）。经用户决策，方案对齐 Akashic：纯规则
> 逐条阈值过滤 + 灰区"不确定"标注，不引入 LLM verifier。主指标随之从
> "FP(any-hit)"改为"误注入条数"。

以 development split（42 families）为准，全部以 gate-off/on 同集对照计量：

- [ ] **主指标**：无答案查询的误注入条数下降 **≥ 40%**（基线 37 条；floor=0.50
      模拟值为 22 条 / -41%）。
- [ ] **附带指标**：有答案查询的无关条目注入数下降（模拟值 225 → 160）；
      灰区条目在返回记录与渲染文本中带"不确定"标注。
- [ ] **不回归硬门**：36 个有正例 family 的 Recall@8 保持 **0.9722 不下降**，
      相关项零误杀；dangerous-hit 零命中保持；determinism 双跑稳定保持。
- [ ] **诚实披露**：`no_answer_false_positive`（any-hit 口径）预期不变，分析
      文档必须写明原因与检索层边界，不得把条数下降表述成"误注入率下降"。
- [ ] **可观测**：trace 记录每次 recall 的丢弃条数、灰区条数与门参数。
- [ ] **可回滚**：`abstention_semantic_floor = 0.0` 时行为与当前逐字节一致，
      现有测试与消融结果不变。
- [ ] **证据产物**：gate-off/on 对照表（误注入条数、Recall、MRR、nDCG、
      Precision、硬门）落入 runtime-artifacts，可复算。

## 非目标

- 不做生成层的 answer abstention（模型拒答话术、prompt 工程）。
- 不修改 RRF/热度等既有排序参数与默认值。
- 不新增 qrels、不改 v1 数据集；holdout 保持 locked，不为本任务解封（v1 holdout
  已在参数实验中解封过一次，再次使用会进一步弱化其效力）。
- 不处理 85 个 ablation 未标注 pair 的补标（独立任务）。

## 风险

- 6 个 abstention family 样本量小，阈值有过拟合 development 的风险——缓解：优先选
  两类分布间隔的中点而非贴边阈值，并在分析文档中报告分布重叠情况。
- 阈值过紧会伤害有答案查询的召回——缓解：验收标准中 Recall 不回归是硬门，任何候选
  阈值先过硬门再比较 FP。
- 语义分数分布依赖 embedding 模型（DashScope text-embedding-v4，1024 维），更换模型
  需重新校准——在参数注释中显式记录该耦合。
