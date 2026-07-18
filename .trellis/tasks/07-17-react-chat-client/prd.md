# 实现 React 单用户聊天客户端

## Goal

基于稳定的流式 turn/SSE 公开契约，把临时原生 JavaScript 验证页替换为 Amadeus 所有者本人使用的 React 单用户多会话聊天客户端。

## Background

- 当前 FastAPI 已在 `/` 返回 `amadeus/web/static/index.html`，并把同一目录挂载到 `/static`；现有原生 JavaScript 页面只是验证壳。
- FastAPI、worker 与 PostgreSQL 是独立运行边界，浏览器只能通过公开 HTTP/SSE 契约访问它们。
- 本任务依赖 `07-18-owner-scoped-web-identity` 和 `07-17-streaming-runtime-sse` 先完成实现与验证；依赖关系不能用前端临时兼容代码绕过。
- 产品定位是所有者本人使用的单用户客户端，但会话和 turn 仍使用服务器校验的结构化身份。

## Requirements

- R1. 提供会话列表、新建会话、切换会话、历史加载和刷新恢复。
- R2. 提交消息后增量显示回答正文，并正确收口 `done/failed/cancelled` 状态。
- R3. 前端只提交 `session_id` 等资源标识，不提交或选择 `user_id`；owner identity 由 FastAPI 注入，前端不直接访问数据库、memory store 或 runtime 内部实现。
- R4. MVP 范围边界以本文 Out of Scope 为准，不得为了展示完整度引入尚无后端公共契约的功能。
- R5. 本任务依赖 `07-17-streaming-runtime-sse` 的公开流式契约完成并通过评审。
- R6. 聊天界面展示安全的工具名称与 `started/completed/failed` 活动状态，但不展示工具参数、返回值或模型原始思考。
- R7. 流式生成中途失败时保留已收到的部分回答，并明确标记为失败且内容不完整。
- R8. 生成期间提供“停止生成”操作；取消后保留部分回答并显示用户取消状态。
- R9. 同一会话存在未终结 turn 时禁用该会话继续发送，但允许切换到其他会话并在那里提交消息；状态按会话/turn 隔离，而不是使用全局 `busy`。
- R10. 前端采用 React + TypeScript + Vite；普通 FastAPI HTTP 接口统一通过一个 Axios instance 调用，组件不得直接使用裸 Axios 或 `fetch`。Axios 负责 base URL、JSON、取消、统一错误转换，并为未来认证凭证和 401/403 处理保留集中入口。
- R11. TanStack Query 只管理 FastAPI 服务端状态的浏览器内存缓存，包括会话列表、历史消息和最终 turn 快照；刷新页面后以 PostgreSQL/FastAPI 为权威重新获取。
- R12. Zustand 只管理按 `session_id/turn_id` 隔离的实时客户端状态，包括增量正文、工具活动、SSE 连接状态、失败与取消状态；EventSource 资源本身由独立 stream client 管理。
- R13. 输入框、侧边栏开合和弹窗等局部界面状态保留在 React 组件内，不进入全局 store。
- R14. React 启动时通过 bootstrap API 获取服务器 owner ID；浏览器不提供修改身份的输入或配置，并且依赖 `07-18-owner-scoped-web-identity` 完成。
- R15. 失败或取消的 turn 在刷新后仍作为“未完成尝试”保留在会话时间线，显示部分回答、安全错误和重试入口；重试创建关联的新 turn，成功 turn 不提供重新生成。
- R16. SSE 断开、刷新或关闭标签页不触发取消；重新进入会话后从 FastAPI/PostgreSQL 恢复累计快照和安全工具事件。
- R17. 前端不显示原始异常；只消费后端稳定的 `error_code/message/retryable` 契约。
- R18. 生产环境使用 Docker 多阶段构建：Node 阶段生成 Vite 静态产物，复制到 Python 运行镜像并由现有 FastAPI 静态路由同源托管；本地开发使用 Vite dev server 代理 `/api` 与 SSE 到 FastAPI，不为生产引入独立前端服务器或跨域依赖。
- R19. 视觉方向采用克制、内容优先的 Material Design 桌面工作台：中性背景、清晰排版、有限强调色、稳定层级与紧凑工具状态，避免霓虹渐变和装饰性“AI 科幻控制台”。
- R20. 组件与样式采用纯 MUI：由 MUI `createTheme`、theme variables、`sx` 与 `styled` 统一负责 Material 组件、设计 token、响应式和主要样式；不引入 Tailwind CSS、shadcn/ui 或 MUI X，避免维护第二套主题与覆盖优先级。
- R21. 助手消息使用安全的 GitHub Flavored Markdown 渲染，支持标题、列表、引用、链接、表格、任务列表、删除线、行内代码、代码块与复制；禁止原始 HTML，外链使用新标签页及安全 `rel` 属性。
- R22. 流式累计正文可能包含暂未闭合的 Markdown，渲染器必须容错且保持布局稳定；FastAPI 返回的原始 Markdown 文本仍是唯一内容事实来源，前端不得把渲染 HTML 作为第二份权威数据持久化。
- R23. MVP 提供完整可用的响应式 Web 布局：桌面端固定会话侧栏，窄屏使用 MUI Drawer 且主区只显示当前聊天；输入区保持底部可达并适配软键盘与安全区域。
- R24. 窄屏下工具状态、失败信息和普通消息不得造成页面级横向滚动；Markdown 表格与长代码块允许自身横向滚动。
- R25. 主题支持“跟随系统、浅色、深色”三态，首次默认跟随系统；手动选择保存在浏览器 `localStorage`，不进入 TanStack Query 或 Zustand。MUI theme variables 必须保证两种配色下的对比度和状态辨识。
- R26. MVP 的消息输入只接受文本；前端不得把本地路径或浏览器文件伪装成文本元数据发送给服务器。
- R27. 新建会话在首条消息前显示“新对话”；首次成功创建 turn 时，由服务器将第一条用户消息规范化为单行并截取约 30 个字符作为持久化标题，不额外调用 LLM。MVP 不提供手动重命名。
- R28. 桌面端 `Enter` 发送、`Shift+Enter` 换行；输入法组合期间 `Enter` 只能确认候选词。空白消息不能发送，创建 turn 请求期间阻止重复提交，当前会话生成中发送按钮切换为停止；移动端通过明确按钮发送并保留软键盘换行。
- R29. React 客户端必须直接替换现有原生静态原型：删除旧 `amadeus/web/static/index.html`、`app.js`、`styles.css` 及其专属测试假设，不保留历史入口、fallback、兼容脚本或双构建链。`amadeus/web/static` 仅作为生产镜像中的 React 构建产物落点。
- R30. 前端统一使用 pnpm，不使用 npm 或 Bun；提交唯一 `pnpm-lock.yaml`，在 `package.json#packageManager` 固定 pnpm 版本。开发、CI 与 Docker 使用同一 pnpm 版本和 `pnpm install --frozen-lockfile`，不得混用命令或生成其他 lockfile。
- R31. React 与 Python 后端保留在同一 Git 仓库，前端源码独立放在根目录 `frontend/`；二者共享任务、契约变更、CI 和 Docker 发布，但各自保留独立依赖清单。当前只有一个 JavaScript package，不引入 Nx、Turborepo 或 pnpm workspace。
- R32. 测试采用分层策略：Vitest + React Testing Library 覆盖纯逻辑、状态、hooks、组件和模拟 HTTP/SSE 集成；Playwright 只覆盖关键真实浏览器链路。CI 默认运行 Chromium，不在每次提交运行 Firefox/WebKit，也不使用真实付费 LLM 或大规模像素截图断言。
- R33. Axios 不承担 RBAC 判定；授权始终属于 FastAPI。SSE 继续使用原生 EventSource，不经过 Axios。未来若引入登录/RBAC，应优先设计同源 HttpOnly Cookie 等同时适用于 Axios 与 EventSource 的凭证机制；Bearer header、登录和 RBAC 本身仍不属于本次 MVP。
- R34. 首个完整可运行 React UI 完成后、最终视觉验收前必须执行 `kill-ai-slop` 审计。扫描范围仅为 `frontend/src` 等手写界面源码，排除 `node_modules/dist`、lockfile 与生成文件；扫描结果必须逐项人工判断，先向所有者提交分组报告并获得批准，再做最小修复，不把启发式扫描器当作自动 lint 或批量改写器。

## Acceptance Criteria

- [ ] 所有者可以创建、切换和刷新恢复会话，并看到对应历史消息。
- [ ] 回答正文随 SSE 增量更新，重连或终态收口不重复内容。
- [ ] 工具活动状态与对应 turn 一起显示，且不会泄露参数、结果或原始推理。
- [ ] 中途失败的部分回答不会消失，也不会以正常完整回答的视觉状态展示。
- [ ] 所有者可以停止正在生成的 turn，UI 最终显示 `cancelled`，并且不会把停止解释为已撤销工具副作用。
- [ ] 一个会话生成期间可以切换并使用另一会话；返回后恢复原 turn 的最新流式快照，且不同会话内容不会串流。
- [ ] 测试证明普通服务端数据与实时流状态边界清晰：Query 缓存失效不会丢失活动流，SSE 增量也不会制造第二份权威历史记录。
- [ ] 失败、空状态、加载状态和窄屏布局具有可验证的用户行为。
- [ ] React 公共行为测试、构建检查和 FastAPI 集成测试通过。
- [ ] 失败/取消 turn 刷新后仍在时间线中，重试不会覆盖原尝试，也不会给成功回答提供重新生成入口。
- [ ] 浏览器断开 SSE 不会发送取消；只有明确点击停止才调用取消端点。
- [ ] Markdown 行为测试覆盖 GFM、代码复制、流式未闭合语法、原始 HTML 禁用与危险链接处理。
- [ ] 响应式测试覆盖桌面固定侧栏、窄屏 Drawer、底部输入可达性，以及表格/代码块局部滚动而非页面横向溢出。
- [ ] 主题测试覆盖系统偏好、手动覆盖、刷新恢复以及浅色/深色下主要状态的可读性。
- [ ] 组件与构建检查证明 MUI 是唯一主要组件/主题系统，未引入 Tailwind、shadcn/ui 或 MUI X。
- [ ] 首条消息后会话标题由服务器确定性生成并在刷新后保持一致，过程不调用 LLM。
- [ ] 输入测试覆盖 Enter、Shift+Enter、中文 IME composition、空白阻止、重复提交阻止、生成中停止按钮和移动端显式发送。
- [ ] 生产构建产物可由 FastAPI 同源返回，本地 Vite 代理可连接 HTTP 与 SSE，且无生产 CORS 依赖。
- [ ] 零残留检查证明旧原生 HTML/JS/CSS、专属选择器和兼容入口均已删除；访问 `/` 时只能得到 React 构建入口，缺少构建产物时明确失败而不是回退旧页面。
- [ ] Vitest 覆盖 API guard、Query/live overlay 合并、SSE seq 去重、Markdown、Composer/IME 和主要组件状态；运行快速且不依赖真实浏览器或网络。
- [ ] Chromium Playwright 使用确定性 FastAPI/PostgreSQL/流式 worker fixture 覆盖：创建并流式完成、跨会话恢复、停止保留部分回答、失败刷新重试、窄屏 Drawer/主题/Markdown 溢出；失败时保留 trace，测试不调用真实付费 LLM。
- [ ] API client 测试证明普通 HTTP 统一经过 Axios instance 并正确转换非 2xx、网络错误、取消和安全错误 payload；组件不直接调用 Axios/fetch，SSE 仍由独立 EventSource 管理。
- [ ] `kill-ai-slop` 审计提供扫描与人工 triage 报告；经批准的修复完成后重新扫描，并通过桌面/移动端视觉 QA。保留的命中必须说明其明确设计意图，不得仅为通过扫描而隐藏。

## Out of Scope

- 登录注册、租户/RBAC 与多用户管理。
- 会话重命名、删除、搜索、置顶和分支管理。
- 图片、文件、粘贴/拖拽附件、服务器路径选择，以及附件持久化和模型能力协商。
- 成功回答的重新生成。
- 管理后台、记忆编辑器和评测控制台。
- PWA 安装、离线模式、移动端推送和原生手势导航。
- 旧原生前端的历史兼容、隐藏入口或并行维护。
