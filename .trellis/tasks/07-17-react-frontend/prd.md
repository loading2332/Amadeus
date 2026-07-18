# 规划并增加 React 前端

## Goal

把现有的临时原生 JavaScript Web Chat 验证页升级为 Amadeus 所有者本人使用、可维护的 React 单用户智能体聊天客户端。MVP 页面边界仍需通过需求访谈确定。

## Background

- 仓库已经有 FastAPI Web adapter，并把 `/api` 路由和静态页面挂载到同一个应用中（`amadeus/web/app.py:43-56`）。
- 现有公开接口覆盖健康检查、会话创建/列表、消息历史、消息提交、turn 状态查询和 turn SSE 事件（`amadeus/web/routes.py:25-98`）。
- 当前浏览器端是单文件原生 JavaScript 验证页：固定 `user_id = 1`，在 `localStorage` 中保存结构化 `user_id/session_id`，优先用 SSE 等待回答并在失败时退化为轮询（`amadeus/web/static/app.js:1-188`）。
- PostgreSQL Web 测试已经证明用户范围隔离、pending turn、missing turn 404、terminal SSE 和结构化会话 ID 契约（`tests/web/test_postgres_web_app.py:13-103`）。
- 既有规划明确记录：PostgreSQL/API 稳定后，前端应完整使用 React 实现（`.trellis/tasks/archive/2026-07/07-04-postgres-worker-runtime/prd.md:124`）。

## Requirements

- R1. 使用 React 替换现有临时原生 JavaScript 页面，同时保留已经成立的 FastAPI、PostgreSQL、worker 和结构化会话身份边界。
- R2. React 前端不得绕过公开 Web API 直接访问数据库、memory store 或运行时内部实现。
- R3. 首版服务 Amadeus 所有者本人，采用单用户产品假设，不建设登录、注册、租户或角色权限系统。
- R4. 单用户假设不得破坏后端现有 `user_id/session_id` 数据边界；前端仍需显式携带结构化身份。
- R5. MVP 提供多会话工作流：显示会话列表、创建新会话、切换会话、加载所选会话的历史消息，并在刷新后恢复上次使用的会话。
- R6. MVP 不扩展后端会话管理 API，不提供会话重命名、删除、搜索或置顶。
- R7. 产品必须支持回答正文的增量流式展示；仅显示 `pending/processing/done/failed` 后再一次性渲染最终答案不满足最终产品需求。
- R8. 流式 runtime、turn 增量状态与 SSE 契约作为 React 实现的前置纵向切片，在本次产品化工作中先完成并独立验证。
- R9. React 客户端必须直接基于最终流式契约实现，不先围绕一次性终态响应建立临时数据模型。
- R10. 身份配置方式、增量持久化策略和部署方式在访谈中收敛后再固化。
- R11. Web 产品不得展示模型原始思考、chain-of-thought 或供应商私有推理字段；可观察性应通过安全的状态或活动事件提供。
- R12. Web 产品支持协作式停止生成，并将 `cancelled` 与 `failed`、`done` 区分；取消不承诺回滚已发生的外部工具副作用。
- R13. 同一会话只允许一个未终结 turn，但不同会话可以独立工作；React 状态不得退化为锁住整个应用的全局 `busy`。
- R14. React 客户端采用 `fetch + TanStack Query + Zustand`：Query 管理 FastAPI 服务端状态缓存，Zustand 管理跨会话实时流状态，局部 UI 状态留在组件内。
- R15. 单用户 owner identity 由服务器配置并注入 Web 边界；浏览器通过安全 bootstrap API 消费身份，不能选择或覆盖 `user_id`。

## Acceptance Criteria

- [ ] React 前端可以通过公开 API 创建或恢复会话、提交消息、观察 turn 状态并显示最终回答或失败原因。
- [ ] 前端继续以 `user_id` 和 `session_id` 作为 JSON/浏览器边界的结构化身份，不重新引入字符串 session key。
- [ ] 首版不要求用户完成登录或注册即可进入所有者自己的聊天客户端。
- [ ] 所有者可以创建和切换多个会话；切换后只显示对应会话的历史消息。
- [ ] 刷新页面后，仍存在的上次会话会被恢复；若该会话已不可用，客户端能够安全选择或创建有效会话。
- [ ] MVP 界面不出现无法由现有 API 完成的重命名、删除、搜索和置顶入口。
- [ ] 所有者提交消息后，可以在 turn 完成前持续看到新增的回答正文，终态答案与增量内容一致且不会重复。
- [ ] 流中断或 worker 失败时，客户端显示明确失败状态，并且已经收到的部分内容不会被误报为成功的完整回答。
- [ ] 流式 runtime/SSE 切片具有不依赖 React UI 的自动化验收证据；React 切片随后通过该公开契约完成端到端验证。
- [ ] 现有后端 Web/API 行为测试保持通过，并增加能够证明 React 公共行为的自动化验证。
- [ ] 最终 MVP 的页面、交互、非目标和验收场景经用户评审确认。

## Out of Scope

- 在需求访谈完成前，不默认加入管理后台、记忆编辑器、评测控制台、Telegram 配置或主动行为控制面板。

## Task Map

1. `07-18-owner-scoped-web-identity`：先统一服务器 owner 配置，建立 owner-scoped Web/BFF 和 bootstrap 契约。
2. `07-17-streaming-runtime-sse`：依赖 owner Web 边界，实现并独立验证 provider → runtime → worker → PostgreSQL turn → SSE 的增量流式契约。
3. `07-17-react-chat-client`：依赖前两个子任务的公开契约，实现单用户多会话 React 客户端及前后端集成验证。

父任务负责完整需求、跨子任务验收与最终集成评审，本身不直接承载实现。

## Open Questions

- 单用户模式下 `user_id` 应由部署配置、前端构建配置还是运行时设置提供？
- 流式增量采用怎样的持久化与断线恢复语义？
- React 构建产物继续由 FastAPI 同源托管，还是采用独立前端开发/部署边界？
