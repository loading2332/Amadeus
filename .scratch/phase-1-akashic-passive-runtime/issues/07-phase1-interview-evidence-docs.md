Status: ready-for-agent
Label: ready-for-agent

# 更新 Phase 1 交付文档和面试证据映射

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

更新 Phase 1 相关项目文档，把实现后的被动 runtime 能力映射到简历 claim、Akashic 参考点、公开行为证明和验证命令。文档必须清楚说明 Phase 1 已迁移的 Akashic contracts、明确延后的内容，以及 session SQLite 与 Phase 2 vector-memory SQLite 的区别。

这个 slice 是交付收口：让用户能在面试里用准确措辞讲出 Phase 1 的亮点，不把尚未实现的 memory/retrieval/outbound/proactive 能力说成已完成。

## Acceptance criteria

- [ ] interview roadmap 中 Phase 1 描述更新为 Akashic-style passive agent runtime，而不是只确认闭环。
- [ ] resume claim gap audit 更新 Phase 1 已完成能力：Reasoner、真实 LLM、tool loop、文件工具、hook policy、loop guard、SQLite session trace。
- [ ] 文档列出 Phase 1 对应的 Akashic 参考机制，以及 Amadeus 迁移的是契约和数据流而不是目录结构。
- [ ] 文档明确 Phase 2 才处理 Markdown memory、vector memory、embedding、retrieval、recall/forget/correction。
- [ ] 文档区分 SQLite session persistence 和 vector-memory SQLite，避免简历措辞混淆。
- [ ] 文档包含普通对话 smoke、文件工具 smoke、确定性测试命令。
- [ ] 文档说明未覆盖的真实集成前提，例如需要配置 OpenAI-compatible API 凭据。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/06-cli-trace-real-llm-smoke.md`
