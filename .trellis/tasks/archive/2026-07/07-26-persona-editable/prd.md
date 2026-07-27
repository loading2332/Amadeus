# 主体可塑化薄壳

父任务：`.trellis/tasks/07-26-roleplay-pivot`（决策与背景见父任务 prd.md，本文件不重复）。

## Goal

把 agent 主体的三个组成部分（Identity、Personality、Self Model）从"两块硬编码 + 一块无入口的数据"变为用户可查看、可编辑、可恢复默认的数据，前端提供"塑造"设置页。**限时 2-3 个有效工作日，做完即停，不打磨。**

## Requirements

- R1 Identity（`amadeus/prompts/persona.py`）与 Personality Rules（`amadeus/prompts/personality_rules.py`）迁移为按 user 存储的可编辑数据；现有红莉栖内容成为默认值。
- R2 提供读取 / 更新 / 恢复默认的 API（Self Model 复用 `SELF.md` 现有读写通道，暴露查看与编辑入口）。
- R3 前端新增"塑造"设置页：三块文本的编辑、保存、恢复默认。
- R4 prompt 组装（`amadeus/prompts/__init__.py` 的调用方）改为从数据源读取用户自定义内容，缺省回落默认值。
- R5 系统协议段（Source Boundaries、History Retrieval Protocol，`amadeus/prompts/__init__.py:14-27`）保持代码所有，不受用户编辑影响。
- R6 编辑内容进入 system prompt 属用户自定义指令，需基本防护：长度上限；空内容视为恢复默认。

## Constraints

- 时间盒 2-3 天：超时即砍范围（优先砍前端体验，其次砍 Self Model 编辑入口，最后保 R1/R4 核心）。
- 不动记忆系统、不动会话模型、不新增角色概念。
- 注意 identity 段处于 prompt 静态区（涉及 prompt cache 前缀），编辑后缓存前缀变化属预期行为，在 design.md 中确认无正确性问题即可。

## Acceptance Criteria

- [ ] AC1 用户在前端编辑 identity / personality / self model 并保存后，新开会话立即生效（人设行为可观察到变化）。
- [ ] AC2 未做任何编辑的用户，system prompt 与改造前逐字节一致（默认红莉栖，回归无感）。
- [ ] AC3 恢复默认功能对三块内容均可用。
- [ ] AC4 系统协议段在任意用户编辑下保持不变（有测试断言）。
- [ ] AC5 编辑 API 有测试覆盖（含长度上限与空内容语义）；现有前后端测试全绿。

## Out of Scope

- 人设模板库 / 预置角色列表、编辑历史版本、多主体。
- "用户塑造 vs 自我演化"的权重融合机制（记入父任务演进方向，本期直接编辑覆写）。
