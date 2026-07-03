# FastAPI 网页对话 turn 框架

## 目标

为 Amadeus 增加一个最小 Web 对话入口，让浏览器客户端可以提交用户消息、观察长耗时 agent turn 的执行状态，并在完成后拿到助手回复，而不是让 HTTP 请求一直阻塞到模型调用结束。

这个第一版切片故意收窄：先让用户能在网页端对话，并能追踪 `pending / processing / done / failed` 状态。不在本任务里做 JWT、完整账号系统、生产级多用户隔离，也不把 PostgreSQL/pgvector 迁移作为硬目标。

## 背景

- Amadeus 已经有被动运行时入口：`PassiveRuntime.run_turn(...)` 接收 `session_key` 和 `user_message`，返回持久化后的消息 id 和助手回复。
- Amadeus 已经通过 `amadeus.session.store.SessionStore` 持久化会话消息，目前是 SQLite 的 `sessions` 和 `messages` 行表。
- Amadeus 已经有 `MemoryEngine` 记忆边界；本任务不能绕过这个边界直接访问记忆存储。
- 当前 Amadeus 包内还没有 FastAPI Web adapter、turn queue、独立 worker loop 或 SSE 状态契约。
- 外部参考：`redrumY/telegram-bot` 的 `codex/web-agent-architecture` 分支使用 FastAPI 路由、`conversation_turns` 队列、worker、SSE 状态事件，以及后续 PostgreSQL `FOR UPDATE SKIP LOCKED` store。Amadeus 可以借鉴它的边界形状，但不要照搬它的完整数据模型。
- 用户决定：包含一个临时浏览器页面，使用原生 HTML、CSS、JavaScript。该页面只是验证工具，后续前端可能替换成 React。
- 用户决定：worker 必须是和 FastAPI 分离的独立进程/命令，这样 API 请求处理和模型执行解耦，也方便后续扩展 worker 数量。

## 需求

- 提供一个 FastAPI 应用模块，暴露最小 Web 对话 API。
- 支持提交消息后快速返回 `turn_id`，不等待 LLM turn 完成。
- 每个提交的 turn 都有明确状态：`pending`、`processing`、`done`、`failed`。
- 提供单个 turn 的状态查询接口。
- 提供 SSE 接口，状态变化时推送事件，并在 `done` 或 `failed` 后关闭。
- 提供一个最小原生 HTML/CSS/JS 页面，能够提交消息、显示 turn 状态、追加助手回复。
- 提供 worker 路径，消费 pending turn，并调用现有 `PassiveRuntime.run_turn(...)` pipeline。
- turn 执行必须在独立 worker 进程/命令中进行，不能作为 FastAPI 进程内 background task。
- 第一版需要足够序列化同一 session 的执行，避免同一会话并发写乱上下文。
- 复用现有 runtime、session、memory 边界，不增加平行 agent pipeline。
- storage abstraction 要按后续 PostgreSQL + `FOR UPDATE SKIP LOCKED` 可替换的方向设计。
- 加测试证明 API、worker、status 行为，不依赖真实 LLM provider。

## 不做范围

- JWT、OAuth、密码、用户注册、权限管理。
- 完整生产级多租户安全。
- PostgreSQL 或 pgvector 正式迁移。
- Telegram 或 QQ 集成改造。
- Proactive loop、Scheduler、DriftRunner 或 outbound delivery。
- 超出验证 Web chat 状态流所需的复杂前端产品化工作。
- React、前端构建工具、路由、组件架构或精修 UI。
- 真实 LLM smoke test，除非配置已经可用且用户明确要求。

## 验收标准

- [ ] 客户端可以通过 FastAPI 提交消息，并收到包含 `turn_id`、`session_key`、`status="pending"` 或等价 queued 状态的响应。
- [ ] 客户端可以查询单个 turn 状态，并观察到 `pending`、`processing`、`done`、`failed` 的转换数据。
- [ ] 客户端可以订阅某个 turn 的 SSE，并在不轮询的情况下收到完成或失败事件。
- [ ] 最小 HTML/CSS/JS 页面可以发送消息，并显示 queued/processing/done/failed 状态。
- [ ] worker 可以 claim 一个 pending turn，执行 fake/test runtime，并把 turn 标记为 `done`，写入助手回答。
- [ ] worker 失败时会把 turn 标记为 `failed`，错误能通过状态查询和 SSE 看见。
- [ ] 第一版 worker 不会并发处理同一 session 的两个 pending turns。
- [ ] 测试覆盖提交、状态查询、SSE 契约，以及 worker 成功/失败/session 序列化行为。
- [ ] 实现可以在本地无 PostgreSQL 的情况下运行。
- [ ] 设计文档说明第一版 store 如何在后续替换为 PostgreSQL `FOR UPDATE SKIP LOCKED`。

## 备注

- `prd.md` 只记录需求、约束和验收标准。
- 这是复杂任务，实现前必须有 `design.md` 和 `implement.md`。
