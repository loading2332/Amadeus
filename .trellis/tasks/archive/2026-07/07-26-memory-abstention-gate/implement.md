# 实施计划：abstention 置信度门

## 执行顺序

### 步骤 1：分布分析（已完成，2026-07-27）

- 结论见 `research/abstention-distribution.md`：any-hit 口径的 FP 无法由分数门
  改善（HyDE 实体陷阱）；经用户决策改走 Akashic 式逐条过滤 + 灰区标注。
- 模拟校准（基于已提交 ablation full-baseline run）：`S_floor=0.50` 时
  无答案误注入 37→22 条（-41%）、有答案无关注入 225→160、相关项零误杀。

### 步骤 2：参数与门实现

- `amadeus/memory/retrieval_parameters.py`：新增 `abstention_semantic_floor`
  （默认 0.0=关闭）与 `abstention_confident_semantic`（默认 1.0），校验 +
  as_dict/fingerprint，docstring 注明 embedding 模型耦合（DashScope
  text-embedding-v4 / 1024 维）。
- `amadeus/memory/retriever.py` recall 路径末端加逐条门（仅 `intent=="answer"`）：
  lexical lane 命中或 `vector_score >= confident` → 正常；`floor <= vector_score
  < confident` → 保留并在 record.signals 标 `uncertain: true`；`vector_score <
  floor` 且无 lexical 来源 → 丢弃。写 `trace["abstention"]`（enabled/outcome/
  dropped_count/uncertain_count/参数值）。
- `_render_priority_sections`（`build_context` 渲染层）：uncertain 条目文本
  追加"（可能相关，不确定）"标注。

### 步骤 3：单元测试

- `tests/memory/test_memory_retriever.py`（或新文件）：设计文档第 6 节列出的合同
  （拒绝/旁路/豁免/关闭一致/trace/参数校验）。
- 验证：`.venv/Scripts/python.exe -m pytest tests/memory/ -q` 全绿。

### 步骤 4：验证运行

- 新增 `scripts/run_abstention_calibration.py`（复用 07-26 ablation 脚本骨架与
  未标注 pair 的池化处理）：gate-off（floor=0）、floor=0.45/0.50 的 informal
  dev 运行；除既有指标外，额外统计无答案误注入条数与有答案无关注入条数
  （从 results JSON 后处理，qrels 判相关性）。
- 预期确认模拟数字：floor=0.50 → 37→22 / 225→160 / 相关项零误杀 /
  Recall・MRR・nDCG 与 gate-off 一致（门只丢无关与低分项，Recall 分子分母不变，
  Precision 允许变化）。
- `S_confident` 取 0.70 与 0.75 两档看灰区标注条数，选标注面更合理的一档。

### 步骤 5：定稿

- 更新 `MemoryRetrievalParameters` 默认值为选定阈值。
- 检查并更新断言旧 fingerprint 的测试。
- 全量验证：`.venv/Scripts/python.exe -m pytest -q`（预期 661+ 全绿）。
- 用选定配置复跑 gate-on/off 对照，确认 36 有正例 family 指标与 gate-off 完全一致。

### 步骤 6：收尾

- 写 `runtime-artifacts/evaluation/abstention-gate/analysis-<date>.md`：
  背景、分布、阈值决策、前后对照表、简历/面试口径段落、残余风险
  （dev-only、小样本、embedding 耦合）。
- spec 更新（trellis-update-spec）：检索门合同与校准协议要点。
- 提交：`feat(memory): 检索 abstention 置信度门`（实现+测试）、
  `feat(eval): abstention 校准与对照产物`（可合并为一个，视 diff 大小）。

## 验证命令

```bash
.venv/Scripts/python.exe -m pytest tests/memory/ tests/evaluation/ -q
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -X utf8 scripts/run_abstention_calibration.py --cache "C:/Users/Zinc/.amadeus/evaluation/memory-retrieval-v1/text-embedding-v4-1024.json"
```

## 回滚点

- 任意阶段：`abstention_semantic_floor = 0.0` 即完全关闭门，行为与 main 当前一致。
- 步骤 5 之前默认值始终为 0.0，中途合入不影响生产行为。

## Review 门

- 步骤 1 完成后：分布是否可分 → 决定继续/调整目标。
- 步骤 4 完成后：阈值决策表 → 用户确认后才改默认值（步骤 5）。
