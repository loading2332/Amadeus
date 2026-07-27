# Persona 一致性评测

父任务：`.trellis/tasks/07-26-roleplay-pivot`（决策与背景见父任务 prd.md，本文件不重复）。

## Goal

为 roleplay 形态建立 persona 一致性评测：新增评测场景与指标，对"默认红莉栖 + 至少 2 个用户自定义人设"跑出可写上简历的一致性数字。这是本方向的**主要投入**（约 1 周）。

## Requirements

- R1 新增 roleplay / persona 一致性评测场景，接入现有评测基建（`amadeus/evaluation/` 的 evaluators、runner、CLI 模式，参照 `memory_retrieval_benchmark.py` 的场景组织方式）。
- R2 指标至少覆盖：
  - 人设服从率（回复符合当前 persona 设定，LLM-as-judge）；
  - 身份稳定性（不自称 AI 助手、不旁白化、不"扮演"口吻，LLM-as-judge）；
  - 舞台指示违规率（括号动作/表情/心理描写，规则检测，`personality_rules.py` 明确禁止项）；
  - emoji 违规率（规则检测，禁止项）；
  - 记忆归因正确性（不把检索结果当人设或当前事实，抽样 judge）。
- R3 规则可检测的指标必须用规则实现（客观、零成本复跑）；仅主观维度用 LLM-as-judge，judge 提示词与用例一并入库。
- R4 评测对象含：默认红莉栖（基线）+ ≥2 个差异明显的自定义人设（依赖子任务 `07-26-persona-editable` 的注入能力；该子任务未完成前，可先用测试桩直接注入 persona 文本开发评测集）。
- R5 报告输出到 `runtime-artifacts/evaluation/`（JSON + Markdown 摘要），包含指标定义、用例数、各人设得分。

## Constraints

- 用例规模以"数字可信"为准（每人设 ≥30 条对话用例起步），不追求学术级规模。
- LLM-as-judge 成本可控：judge 用便宜模型，用例集设计为可增量复跑。
- 不修改被测系统行为；发现的人设缺陷记录为后续任务，不在本任务顺手修。

## Acceptance Criteria

- [ ] AC1 评测可通过 CLI 一键运行（含只跑规则指标的零成本模式）。
- [ ] AC2 指标定义、用例、judge 提示词全部入库，他人可复跑得到同量级结果。
- [ ] AC3 产出基线 + ≥2 自定义人设的对比报告，落在 `runtime-artifacts/evaluation/`。
- [ ] AC4 报告含一段"简历可引用"摘要（指标名 + 数字 + 用例规模一句话）。

## Out of Scope

- LoRA / 微调对比（可选后续任务）；长程多 session 一致性追踪（演进方向）；对评测发现问题的修复。
