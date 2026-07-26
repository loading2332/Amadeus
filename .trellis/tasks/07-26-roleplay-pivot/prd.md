# Roleplay 角色扮演方向改造

## Goal

把 Amadeus 项目往 roleplay 赛道强化，使其作为求职作品（目标岗位：AI agent 全栈开发）更有竞争力。
交付物要同时满足两点：面试官 30 秒内能看到可玩的 demo；面试深挖时有技术深度可讲（记忆一致性、人设一致性评测等）。

## Background（求职上下文）

- 用户海投 200-300 份简历，仅 3-4 个面试邀约；目标岗位为 AI agent 全栈开发。
- 前期讨论结论：瓶颈主要在简历呈现与项目叙事，改造要服务于"可展示 + 可深挖"的叙事，而非堆功能。

## Confirmed Facts（仓库勘察结论）

- 项目**已经是单角色 roleplay**：persona 硬编码为《命运石之门 0》Amadeus 牧濑红莉栖（`amadeus/prompts/persona.py:1`），并有精细的中文人格行为规则（`amadeus/prompts/personality_rules.py:1`），通过 `amadeus/prompts/__init__.py` 拼装进 system prompt。
- 记忆系统完备：RRF 双路检索、ranking、retriever（`amadeus/memory/`），且有检索评测基准与消融实验（`amadeus/evaluation/memory_retrieval_benchmark.py`、`memory_retrieval_experiment.py`），benchmark 场景目前是 personal_assistant / project_assistant / stress，**尚无 roleplay/persona 一致性场景**。
- 会话层：`amadeus/session/`（identity/store/postgres/titles），正在进行中的 07-26-session-delete 任务补齐会话删除。
- 全栈形态完整：FastAPI web 层（`amadeus/web/`）+ React 前端（`frontend/src/`：chat、sessions、streaming、ui）。
- Agent 能力：tool loop 在 Reasoner、tool_chain 执行元数据、MCP 工具注册（`amadeus/mcp/`）、worker（`amadeus/worker/turn_worker.py`）。
- 评测基建：evaluators、LangSmith 同步、prompt cache benchmark（`amadeus/evaluation/`）。

## Requirements

- TBD（brainstorm 进行中）

## Acceptance Criteria

- [ ] TBD

## Open Questions（阻塞规划）

1. 产品形态：单角色（红莉栖）深耕 vs 多角色角色卡平台化？
2. MVP 范围与周期约束（求职窗口期内先出什么）。
3. 是否包含 LoRA 微调对比实验（作为本任务或后续子任务）。
4. persona 一致性评测的形态与指标。

## Out of Scope（暂定）

- Redis / 消息队列等纯工程化中间件（目标岗位为 AI agent 全栈，优先级低于 agent/记忆/评测叙事；除非后续出现真实性能问题）。
