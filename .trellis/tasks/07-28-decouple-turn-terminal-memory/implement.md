# 拆分回答终态与后台记忆生命周期：实施计划

## 1. 实施原则

- 依赖顺序：数据库契约 → 原子成功提交 → runtime 脱钩 → 独立 memory worker → 浏览器验收 → 文档。
- 每一步先建立能捕获目标缺陷的测试，再修改生产代码。
- 不修改 Akashic 仓库。
- 不实现 CLI、管理 API、人工重放、完整重试/告警策略。
- inline 模式由主会话直接实施与检查，不创建 implement/check sub-agent。

## 实施结果（2026-07-28）

- 已完成 PostgreSQL durable job、`done + terminal + job` 原子事务、独立
  memory worker、stale lease 恢复、固定消息边界与 Compose 服务。
- Runtime 回归测试证明永久阻塞的 `run_post_response` 不再阻塞回答返回。
- E2E fixture 在不启动 memory worker 的情况下留下 `pending` job；真实
  Chromium 链路测得完整回答可见后 15ms 退出生成态，满足 500ms 预算。
- Python 聚焦测试、mypy、变更文件 Ruff、前端 Vitest/typecheck/lint/build、
  WSL Docker migration 和 memory-worker 镜像入口均通过。
- 全量 pytest 为 702 passed / 1 existing integration failure；失败来自既有
  跨进程测试缺少认证/鉴权适配，按用户要求不在本任务中处理。
- 仓库 Playwright 配置的 `127.0.0.1:4173` 落在本机 WSL/Hyper-V 保留端口段，
  因此用同一确定性 E2E 后端在 `127.0.0.1:18001` 直接托管构建产物完成等价验收。

## 2. 实施清单

### 2.1 建立红色反馈回路

- [ ] 将诊断阶段的阻塞 memory harness 固化为自动化测试：post-response 不解除时，回答成功提交与 terminal 必须先完成。
- [ ] 为前端 E2E fixture 增加可阻塞的 post-response memory runner，记录最后字符可见与生成状态结束时间。
- [ ] 先运行测试并确认旧实现失败，保存失败证据。

### 2.2 数据库与 job store

- [ ] 新增 Alembic migration，创建 `post_response_memory_jobs`、约束和 claim 索引。
- [ ] 新增 `PostResponseMemoryJob`、状态常量、错误类型和 store protocol。
- [ ] 实现 PostgreSQL create/claim/heartbeat/done/failed/stale recovery。
- [ ] 使用 `FOR UPDATE SKIP LOCKED` 和 lease 校验。
- [ ] 测试唯一 turn enqueue、并发 claim、旧 lease 拒绝、stale recovery、user/session 隔离和状态不可逆。

### 2.3 原子成功提交

- [ ] 新增 `TurnExecutionResult`，让 `PassiveAppTurnRunner` 返回 answer、message ids 和 explicit memory ids。
- [ ] 实现 `PostgresTurnStore.complete_success()`，在一个事务中写 `done + turn_terminal + memory job`。
- [ ] 验证 message ids 的 user/session/turn 归属。
- [ ] 修改正常 worker 成功路径使用 `complete_success()`。
- [ ] 修改 stale reconcile 的“assistant message 已存在”路径，以等价事务补齐 terminal 与 job。
- [ ] 测试事务失败不会留下孤立 done 或孤立 job，重复调用不会重复 enqueue。

### 2.4 Runtime 与 memory 脱钩

- [ ] 从默认 `after_turn` 模块移除同步 post-response memory 执行。
- [ ] 保持 `MemoryEngine.run_post_response` 和现有候选/纠错/来源引用算法不变。
- [ ] 调整 runtime/memory trace 测试：回答结果不再等待或内嵌后台完成 trace。
- [ ] 测试阻塞/失败的 post-response 不影响 runtime 返回和 turn terminal。

### 2.5 独立 memory worker

- [ ] 新增独立 memory worker module、runner 和 stats。
- [ ] job runner 以 user scope 构建 app，只读取 job 固定的两条 message ids。
- [ ] 通过 `MemoryEngine.run_post_response` 执行并写入结果 trace。
- [ ] 异常时安全标记 `failed`；进程崩溃由 stale lease 恢复。
- [ ] 保证同 session FIFO，不同 session 可领取。
- [ ] 测试进程重启后的 pending/stale job、固定消息边界、user 隔离、重复执行幂等和回答状态独立。

### 2.6 Docker 与配置

- [ ] 在 Docker Compose 增加 `memory-worker`，复用镜像、env、PostgreSQL 和 workspace volume。
- [ ] 增加必要的 poll/heartbeat/stale 配置，默认值与 turn worker 风格一致。
- [ ] 更新应用关闭逻辑，确保 memory provider/client 正确释放。
- [ ] 验证 WSL Docker 下 migration、worker 和 memory-worker 能启动。

### 2.7 前端与端到端验收

- [ ] 保持 SSE 协议不新增 memory 状态。
- [ ] 用可控 E2E 测试证明后台 memory 阻塞时，turn 仍先收到 `done`。
- [ ] 计时验证最后字符可见后 500ms 内：光标消失、停止按钮恢复、Composer 可再次提交。
- [ ] 验证终态 Query handoff 不闪空，memory job 失败不显示聊天错误。

### 2.8 规范与运行文档

- [ ] 更新 backend turn streaming、async boundary 和 frontend chat specs。
- [ ] 更新 README、PostgreSQL runtime 文档和 `.env.example`。
- [ ] 明确 Akashic 参考契约与 Amadeus durable PostgreSQL 扩展。
- [ ] 记录不在本任务内的失败治理后续项，但不创建未获授权的新任务。

## 3. 验证命令

先窄后宽，实际文件名可按实现落点微调：

```powershell
# 数据库与 store
.\.venv\Scripts\python.exe -m pytest tests/db tests/turns tests/memory/test_post_response_memory_jobs.py -q

# worker/runtime/memory
.\.venv\Scripts\python.exe -m pytest tests/worker tests/runtime tests/memory/test_runtime_memory.py tests/memory/test_memory_post_response_worker.py -q

# Web/SSE 跨进程
.\.venv\Scripts\python.exe -m pytest tests/web tests/integration/test_web_stream_cross_process.py -q

# Python 质量
.\.venv\Scripts\python.exe -m ruff check amadeus tests migrations
.\.venv\Scripts\python.exe -m mypy

# 前端
Set-Location frontend
pnpm typecheck
pnpm lint
pnpm test -- --run
pnpm run test:e2e

# WSL Docker
Set-Location ..
wsl docker compose config
wsl docker compose up -d --build postgres migrate api worker memory-worker
wsl docker compose ps
```

最终根据共享改动范围补跑：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 4. 关键评审门

### Gate A：事务正确性

- `done`、`turn_terminal`、memory job 不存在部分提交。
- 正常与 stale recovery 成功路径行为一致。
- cancelled/failed turn 不创建成功回答 job。

### Gate B：生命周期隔离

- post-response 阻塞时，回答仍完成并允许下一轮。
- memory worker 与 turn worker 是独立消费循环。
- job 只读取本轮固定消息，不读取未来 turn。

### Gate C：幂等与隔离

- 一个 turn 最多一个 job。
- lease 失效后旧 worker 不能提交结果。
- user/session 不串线。
- crash recovery 重跑不产生重复破坏性 memory side effect。

### Gate D：用户公共行为

- 最后字符到退出生成状态不超过 500ms。
- 终态交接不闪空、不丢正文。
- memory job 状态不进入聊天协议或 UI。

## 5. 风险与回滚点

| 风险 | 防护 | 回滚点 |
|---|---|---|
| done 与 job 非原子导致漏记忆 | 单事务 + unique turn id | 保留旧表，回滚应用代码 |
| job 读取未来会话内容 | 固定 message ids | 停止 memory-worker，pending 保留 |
| memory worker 阻塞 turn worker | 独立进程/循环 | 单独停止 memory-worker |
| stale recovery 重复副作用 | lease + stable source_ref + store unique 约束 | 禁用 stale claim，保留 job |
| 500ms E2E 在 CI 抖动 | 可控 fixture、测公开状态、避免真实模型网络 | 保留后端因果测试，单独诊断环境抖动 |

## 6. 完成条件

- PRD 中 AC1–AC8 均有对应可运行证据。
- 诊断阶段的原始“最后文字后等待 post-response”反馈回路转绿。
- 所有临时 debug instrumentation 和 fixture 状态已清理或明确归入测试资产。
- 相关规范、运行文档与 Docker 服务同步。
- 用户审阅规划并明确批准后，才执行 `task.py start` 进入实现阶段。
