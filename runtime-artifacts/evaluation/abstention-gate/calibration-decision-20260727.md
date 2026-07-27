# Abstention 置信度门：校准决策（development split）

- 日期：2026-07-27
- run_id: `memory-retrieval-20260727T071140Z-7578ec`
- 脚本：`scripts/run_abstention_calibration.py`（informal、池化补标口径，与
  07-26 feature ablation 相同；holdout 未使用）
- 前置分析：`.trellis/tasks/07-26-memory-abstention-gate/research/abstention-distribution.md`
  ——检索层分数门无法降低 any-hit 口径的 no_answer_false_positive（HyDE 实体
  陷阱需实体级理解），经决策对齐 Akashic：逐条阈值过滤 + 灰区"不确定"标注。

## 对照结果（42 dev families）

| Profile | 无答案误注入条数 | 有答案相关注入 | 有答案无关注入 | uncertain 标注 | Recall@8 | MRR@8 | nDCG@8 | 硬门 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| gate-off（现状） | 37 | 45 | 225 | 0 | 0.9722 | 0.8843 | 0.8906 | 通过 |
| floor=0.45 / conf=0.70 | 30 (-19%) | 45 | 193 (-14%) | 110 | 0.9722 | 0.8843 | 0.8906 | 通过 |
| **floor=0.50 / conf=0.70** | **22 (-41%)** | **45** | **160 (-29%)** | 69 | 0.9722 | 0.8843 | 0.8876 | 通过 |
| floor=0.50 / conf=0.75 | 22 (-41%) | 45 | 160 (-29%) | 72 | 0.9722 | 0.8843 | 0.8876 | 通过 |

## 逐项核对验收标准

- 主指标：无答案误注入 37 → 22（**-41%**，达标 ≥40%）✅
- 附带：有答案无关注入 225 → 160（-29%）；灰区标注生效（69 条）✅
- 硬门：Recall@8 0.9722 不变、相关注入 45 条不变（**强相关零误杀**）、
  dangerous 零命中、determinism 双跑稳定 ✅
- 诚实披露：`no_answer_false_positive`（any-hit）四组均为 1.0，符合预期，
  不得表述为"误注入率下降" ✅

## 已知代价（必须随结论一起报告）

floor=0.50 时 nDCG@8 由 0.8906 → 0.8876（-0.0030）。逐条核对：门共丢弃 80 条，
其中 76 条 relevance=0（无关）、**4 条 relevance=1（弱相关）**、relevance≥2 零丢弃。
nDCG 微降全部来自 4 条弱相关低分项。判定为可接受：PRD 硬门以 Recall
（relevance≥2）计，弱相关项换取 41% 误注入减量符合门的设计意图。

## 推荐默认值

`abstention_semantic_floor = 0.50`，`abstention_confident_semantic = 0.70`。

- 0.50 对最脆弱的强相关项（0.5201）留 0.02 余量；0.52 只多降 2% 但余量仅
  0.0001，过脆，弃。
- conf=0.70 与 0.75 指标完全相同，0.70 的不必要标注更少（69 vs 72），取 0.70。

## 边界与残余风险

- 阈值依赖 DashScope text-embedding-v4 / 1024 维的分数分布，更换 embedding
  模型必须重新校准。
- development-only 校准；holdout 保持 locked。
- any-hit 口径的无答案误注入未解决（4/6 为 HyDE 实体陷阱），已证明属于
  生成层/verifier 层能力，见分布分析文档。
