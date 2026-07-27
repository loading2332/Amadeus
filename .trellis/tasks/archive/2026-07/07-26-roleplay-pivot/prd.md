# Roleplay 角色扮演方向改造（父任务）

> **状态：已取消（07-27）**。Grilling 结论：当前求职瓶颈未验证在哪一段（初筛 vs 面试），项目功能投入属二阶段动作。先做零代码验证（简历改写 + 在职者 review + 换渠道小批量对照投递），两周后若约面率改善且面试反馈指向项目深度，可从本归档恢复——D1/D2 决策与基准调研（CharacterEval / PersonaGym / PersonaMem）仍然有效。

## Goal

把 Amadeus 强化为"单一可塑造的长期陪伴 agent"，服务于求职叙事（目标岗位：AI agent 全栈开发）。
目标叙事一句话：**用户可以任意重塑 agent 人格，系统用评测集保证任意人设下的行为一致性与记忆正确性。**
交付两件事：可现场演示的"塑造人格"功能（薄壳、限时）+ 可写上简历的 persona 一致性评测数字（主要投入）。

## Background

- 用户海投 200-300 份简历仅 3-4 个面试，结论：瓶颈在项目叙事而非功能数量；本任务为叙事补最后一环，不堆功能。
- 项目现状已是单角色 roleplay（内置牧濑红莉栖），已有的大亮点资产：RRF 双路记忆检索 + 检索 benchmark/消融实验（`amadeus/evaluation/`）、prompt cache 基准、tool loop 架构。本任务用产品故事把它们串起来。

## Decisions

- **D1 产品形态**：单一可塑造主体（Replika 线，非猫箱式多角色平台）。每用户一个伴侣主体，identity / personality / self model 全部用户可编辑；记忆保持 user 级，**无隔离改造**。（07-26 确认）
- **D2 投入结构**：子任务 1 薄壳限时 2-3 天；子任务 2 评测为主菜约 1 周；LoRA 对比实验为可选后续，不进本任务。（07-26 确认）

## Confirmed Facts（仓库勘察）

- "主体"由三部分拼装（`amadeus/prompts/__init__.py`）：Identity（`amadeus/prompts/persona.py:1`，硬编码）+ Personality Rules（`amadeus/prompts/personality_rules.py:1`，硬编码）+ Self Model（`SELF.md`，已是 workspace 数据文件并随记忆演化，`amadeus/app/workspace.py:19`、`amadeus/memory/markdown.py:155-158`）。self_model 属 prompt 核心段落（`amadeus/prompting/budget.py:3`）。
- Behavior Rules 中 Source Boundaries 与 History Retrieval Protocol 为系统协议段（`amadeus/prompts/__init__.py:14-27`），与人格无关，不应暴露给用户编辑。
- 记忆按 `user_id` 强隔离且跨 session 共享（`amadeus/memory/postgres.py:19-27`）；会话归属 `(user_id, session_id)`（`amadeus/session/identity.py:7`）。单主体形态下此模型无需变动。
- 评测基建现成：evaluators、benchmark runner、LangSmith 同步、检索 benchmark 场景机制（`amadeus/evaluation/memory_retrieval_benchmark.py`，现有场景 personal_assistant / project_assistant / stress，无 roleplay 场景）。

## Task Map（子任务）

| 子任务 | 交付物 | 约束 | 依赖 |
|---|---|---|---|
| `07-26-persona-editable` 主体可塑化薄壳 | persona/personality 改为可编辑数据 + 编辑 API + 前端设置页 | 限时 2-3 天，做完即停 | 无 |
| `07-26-persona-consistency-eval` Persona 一致性评测 | roleplay 评测场景 + 一致性指标 + 基线与自定义人设的评测报告 | 主要投入约 1 周 | 自定义人设用例依赖子任务 1 的注入能力 |

## Cross-child Acceptance Criteria（父任务验收）

- [ ] 演示路径成立：前端改一段人设 → 新会话行为随之改变 → 评测报告给出该人设下的一致性数字。
- [ ] 未做任何编辑的存量用户，行为与改造前完全一致（默认红莉栖）。
- [ ] 产出一份可引用的评测报告（指标定义 + 数字），落在 `runtime-artifacts/evaluation/` 下。
- [ ] 两个子任务各自归档后，父任务做最终集成 review 并归档。

## Out of Scope

- 多角色角色卡平台、按角色的记忆隔离（明确否决，见 D1）。
- Redis / 消息队列等中间件（与目标岗位叙事无关，无真实性能问题不做）。
- LoRA 微调对比实验（可选后续任务，不阻塞本任务归档）。

## Open Questions

- 无（阻塞级问题已全部决策；设计细节由各子任务 design.md 解决）。
