# 执行计划

## 顺序

两个 implement 子代理并行：

- 子代理 A（后端）：F1 → F3 → F2（先小后大，F2 涉及面最广放最后）
- 子代理 B（前端）：F4

## 检查单

- [ ] F1: `run_forever` 迭代级 try/except + 退避；`run_once` 的 `mark_failed` 防击穿；新增 worker 存活测试
- [ ] F3: `_extract_tool_calls` JSON 防护 + 降级；流式/非流式一致；新增畸形 JSON 测试
- [ ] F2: sse.py / routes.py / PersistedTurnStream 的同步 store 调用下沉 `asyncio.to_thread`；确认池线程安全；flush 顺序性保障
- [ ] F4: ChatView connect 过滤 ACTIVE；新增组件测试
- [ ] 后端验证：`uv run pytest`（全量）
- [ ] 前端验证：`pnpm typecheck && pnpm lint && pnpm test`（frontend/ 下）
- [ ] trellis-check 子代理全量复查
- [ ] 提交（只含本任务文件，不含 prompt-cache-benchmark 的未提交改动）

## 回滚点

每个 F 独立成文件级改动，出问题按文件 revert。
