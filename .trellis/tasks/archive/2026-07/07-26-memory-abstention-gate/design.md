# 设计：abstention 置信度门

## 1. 放置位置

门放在 `MemoryRetriever` 的 recall 路径末端：`rank_candidate_lanes` 产出最终排序结果
之后、返回 records 之前。理由：

- `LongTermMemoryEngine.recall()` 是 runtime（`before_turn` 的 retrieved_memory）与
  benchmark（`_run_query`）共同的唯一入口，在这里拦截，生产行为与评测计量天然一致；
- 放在 prompt 层（丢弃已返回的 records）会造成"检索说有、注入说没有"的 trace 分裂；
- 放在 ranking 内部会与排序逻辑耦合，门的开/关无法独立测试。

scoped → global 两段式回退检索保持不变；门作用于**最终选定 scope 的结果集**，
不干预回退决策本身。

## 2. 门信号与判定规则（三段式，参考 Akashic）

> 设计参考：`akashic-agent/memory2/retriever.py` 的注入层过滤。Akashic 的做法是
> ① 注入时按记忆类型的绝对阈值过滤（默认 0.45，高于候选资格线），全部不过线时注入块
> 自然为空；② 过线但贴近阈值的灰区条目**不拒绝，而是带"有印象，不确定"标签注入**，
> 把不确定性交给生成层处理；③ 每类条数上限 + 字符预算。它没有二元的"拒/收"门，
> 灰区用软标签消化——这解决了"向量分中等既可能相关也可能不相关"的两难。

全部信号来自现有数据，不新增 LLM 调用、不新增 SQL：

| 信号 | 来源 | 含义 |
|---|---|---|
| `top_semantic` | vector lane 最高原始语义分（融合 hotness 之前） | 最强候选与查询的语义相关度 |
| `item_semantic` | 每条候选自身的语义分 | 该条目的置信带归属 |
| `lexical_anchor` | 候选是否来自 lexical lane（字面子串命中） | 强证据，语义分低也按高置信处理 |

判定改为**逐条三段式置信带**（2026-07-27 修订：分数口径 = 每条候选的
`vector_score`，即该条在全部向量 lane 中的最高原始语义分，与现有排序同源；
step-1 分析证明任何分数口径都无法识别 HyDE 实体陷阱，故本门的目标是"减量 +
标注"而非 any-hit 拒绝，详见 `research/abstention-distribution.md`）：

```text
若 request.intent == "answer" 且 gate 启用，对每条候选：
    lexical lane 命中                        -> 高置信带（正常返回）
    item_semantic >= S_confident             -> 高置信带（正常返回）
    S_floor <= item_semantic < S_confident   -> 灰区带（返回，signals 标 uncertain，
                                                注入时渲染"可能相关，不确定"标签）
    item_semantic < S_floor                  -> 丢弃

全部候选都被丢弃 -> 返回空
```

初值（由 step-1 模拟校准，验证运行确认）：`S_floor = 0.50`（离最脆弱的相关项
0.5201 留 0.02 余量；模拟结果：无答案误注入 37→22 条 / -41%，有答案无关注入
225→160，相关项零误杀）；`S_confident` 在验证运行时从灰区标注合理性校准
（候选 0.70/0.75）。

- **回应"向量返回但词法没返回不代表不相关"**：正确，所以词法锚点只是"直入高置信带"
  的充分条件，从来不是返回的必要条件；语义改写类命中走 `S_confident` 高置信带；
  分数中等的走灰区带——**不会被拒绝**，只是诚实地告诉模型"这条不确定"。真正被
  abstention 的只有"连灰区下限都够不到"的候选。
- `S_floor` 与 `S_confident` 均从 development 分布校准；两者相等时退化为二元门。
- 词法旁路的依据：ablation 已证明 lexical lane 找回的是版本号、短 CJK 词等精确标识，
  这类命中语义分天然偏低，不能被语义门误杀。CJK 二字组子串比英文 token 松，是否对
  锚点加词长/覆盖率门槛，由分布分析的数据决定。
- 非 `answer` intent（如维护型检索）不受门影响。
- 与 Akashic 的差异：保留全局阈值先行（6 个 abstention family 撑不起按类型 × 双阈值
  的校准维度），参数结构预留 per-type 覆盖的扩展位；Akashic 未对该机制做过
  no-answer 基准验证，Amadeus 的增量正是用冻结基准量化它。

### benchmark 计量口径的影响

现有 `no_answer_false_positive` 只看"返回了没有"。灰区带条目仍在返回集中，因此指标
上等同于返回——这是刻意的：**FP 指标的下降只能来自 S_floor 以下的真丢弃**，灰区
标签属于生成层的减害措施，不计入检索层指标。分析文档需分别报告：真丢弃带来的 FP
下降、灰区标签的触发比例。

## 3. 参数与回滚

`MemoryRetrievalParameters` 新增字段（全部参与 as_dict/fingerprint，带校验）：

```python
abstention_semantic_floor: float = <校准值>      # 0.0 表示门完全关闭
abstention_confident_semantic: float = <校准值>  # 高置信带下限；等于 floor 时无灰区
```

灰区标签只是返回记录上的 `uncertain` 信号 + 注入渲染差异，不引入独立参数。

`abstention_semantic_floor = 0.0` 时所有查询无条件通过且无灰区标签，行为与当前
逐字节一致——这是回滚开关，也是既有测试兼容的保证。旧 shortlist JSON 反序列化时
按默认值补齐（沿用 07-26 ablation 给 profile 加开关的兼容方式）。

注意：语义分数分布与 embedding 模型耦合（DashScope text-embedding-v4 / 1024 维），
参数 docstring 中注明更换模型必须重新校准。

## 4. 阈值校准协议

1. **分布提取（不跑新实验）**：从已提交的 ablation full-baseline 运行结果
   （`runtime-artifacts/evaluation/retrieval-ablation/...results.json` 的 ranked_records
   signals）提取 development 42 个 query 的 top_semantic：6 个 abstention query 一组、
   36 个有正例 query 一组，观察两组分布与重叠。
2. **选阈值**：候选 S_floor 取两组分布间隔内的网格点（优先中点，不贴边）；若分布
   重叠导致无法零损失分离，按"Recall 不回归优先"取重叠区下沿，接受 FP 只降到部分。
3. **验证运行**：扩展 `scripts/run_retrieval_ablation.py` 模式或新增
   `scripts/run_abstention_calibration.py`，informal 跑 development split：
   gate-off（S_floor=0）与 2~3 个候选 S_floor 各一组 profile，复用既有 harness 的
   指标、硬门与 determinism 检查。
4. **决策**：先过"Recall 0.9722 不降、dangerous 零命中"硬门，再在存活者中选 FP 最低；
   平局选更保守（更低）的 S_floor。全程 development-only，holdout 不动。

## 5. Trace 合同

`result.trace["abstention"]`：

```json
{
  "enabled": true,
  "outcome": "pass|all_dropped|partial",   // partial = 有条目被丢弃但仍有返回
  "top_semantic": 0.41,
  "dropped_count": 5,
  "uncertain_count": 2,                    // 灰区带（带 uncertain 标签返回）条数
  "lexical_anchor_count": 1,
  "reason": "below_floor|intent_exempt|disabled|pass"
}
```

全部丢弃时 records 为空但 trace 完整保留信号值；灰区条目在 record.signals 中带
`uncertain: true`，注入渲染层据此加"可能相关，不确定"标注（Akashic 的
confidence_label 同型机制）。复盘"为什么拒"与"为什么没拒"同样可查。

## 6. 测试策略

- **单元合同**（`tests/memory/`）：低于 floor 拒绝；lexical anchor 旁路；margin 次级
  规则；floor=0 时与现状逐字节一致；非 answer intent 豁免；trace 字段齐全；参数校验
  （范围、类型）。
- **基准回归**（informal runner）：gate-on 校准值配置下，36 有正例 family 指标与
  gate-off 完全一致（门只应影响 abstention family）——这是比"不回归"更强的断言，
  若不成立需在分析文档中逐 family 解释。
- **既有测试**：全量套件（当前 661）保持全绿；默认参数变化会改变 fingerprint，
  检查是否有测试断言旧 fingerprint 并同步更新。

## 7. 取舍记录

- **规则门而非学习门**：6 个 abstention family 训练不了分类器；规则门可解释、可校准、
  可在面试中完整讲清。样本量扩大后再考虑升级。
- **检索层而非生成层**：生成层 abstention（拒答话术）无法阻止污染 context 的
  token 成本与幻觉诱导，且不可被现有 benchmark 计量。两层最终都要，本任务只做检索层。
- **不用 RRF 分数做门**：RRF 是名次函数，量纲不含"绝对相关度"，不同查询之间不可比；
  语义余弦分是唯一跨查询可比的置信度来源。
