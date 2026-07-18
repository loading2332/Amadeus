# React 单用户聊天客户端实施计划

## 1. 实施前置门

- [x] `07-18-owner-scoped-web-identity` 已实现并通过聚焦与全量验证。
- [x] `07-17-streaming-runtime-sse` 已实现并通过 provider/runtime/store/worker/Web/SSE 验证。
- [x] 运行 `trellis-before-dev`，加载 frontend、backend、database 与 cross-layer 规范。
- [x] 确认 pnpm 与 Node LTS 可用并记录固定版本；使用 `pnpm-lock.yaml` 和冻结安装，不运行未经审阅的脚手架升级，禁止 npm、Bun 和多 lockfile 混用。
- [x] 确认工作树中的既有用户改动，只修改本任务相关文件。

## 2. 初始化前端骨架

- [x] 在 `frontend/` 创建 React + TypeScript + Vite 工程和 pnpm scripts，并在 `packageManager` 固定 pnpm 版本。
- [x] 配置严格 TypeScript、Vitest、Testing Library、MSW、ESLint 与 Playwright。
- [x] 将测试职责写入配置与目录：Vitest 负责逻辑/组件/模拟集成；Playwright 默认 Chromium，只保留五条关键用户链路并在失败时输出 trace。
- [x] 安装 MUI/Emotion、TanStack Query、Zustand、Axios、Markdown/GFM；Markdown 渲染器按需加载，MVP 代码块保持普通渲染，未引入不必要的高亮依赖。
- [x] 配置 MUI 直接模块导入与 bundle 检查；确认依赖树没有 Tailwind、shadcn/ui 或 MUI X，且 Axios 只有一个集中实例。
- [x] 建立 Vite 开发代理和生产 `/static/` base。

验证：空壳 `pnpm run typecheck`、`pnpm test -- --run`、`pnpm run build` 全部通过。

## 3. API 与状态边界

- [x] 实现单一 Axios instance、`ApiError`、typed response guards 和稳定 query keys；interceptor 只做协议级转换，不导航、不显示 UI、不写全局状态。
- [x] 建立 bootstrap/sessions/session-turns/turn Query hooks；无依赖请求并行，mutation 禁止自动重试。
- [x] 实现按 turn 的 Zustand live overlay、单调 seq 去重和细粒度 selector。
- [x] 实现独立 EventSource manager；按 turn 管理连接、cursor、重连和终态清理，不把资源放进 store。
- [x] 完成 HTTP/SSE 与终态交接测试，证明权威快照刷新前不会丢 live state，SSE 不制造第二份历史。

风险点：React StrictMode 会重复执行 effect；连接 manager 必须幂等，不能产生两条 EventSource 或把 cleanup 误当成取消。

## 4. Material 主题与 AppShell

- [x] 建立 system/light/dark color schemes、语义状态 token 和组件 overrides。
- [x] 实现版本化 theme localStorage adapter，处理禁用/损坏/配额异常并避免首屏闪烁。
- [x] 实现桌面固定侧栏、窄屏 Drawer、主聊天区和安全区域布局。
- [x] 用 `?session=` 恢复当前会话；无效 session 安全回退。
- [x] 组件测试与 Playwright 覆盖键盘/IME、焦点、ARIA 名称、颜色模式、刷新恢复与窄屏溢出。

## 5. 会话、时间线与流式合并

- [x] 实现会话列表、新建、选择、加载/空/错误状态；活动 turn 在对应会话时间线和 Composer 中展示。
- [x] 实现 `ChatTimeline` 将 Query turn 与对应 live overlay 合并，状态按 session/turn 隔离。
- [x] 实现工具活动、部分失败、取消、停止、重试和原失败记录保留。
- [x] 实现近底部自动跟随、用户上滚保护与“回到底部”。
- [x] 使用稳定 key、按 turn 细粒度 selector 和独立时间线更新边界，避免 delta 驱动整个 AppShell 重渲染。

风险点：终态事件与 Query refetch 可能交错；合并规则必须保证最终服务器 answer 获胜，同时不能在 refetch 窗口闪回旧正文。

## 6. Markdown 与 Composer

- [x] 实现禁用原始 HTML的 GFM 渲染、外链协议白名单和安全属性。
- [x] 实现代码复制、表格/代码块局部滚动；Markdown 渲染器懒加载，流式与终态均使用稳定的普通代码块。
- [x] 实现按 session 的 App 局部草稿、自动增高文本框和发送/停止按钮。
- [x] 实现 Enter、Shift+Enter、IME composition、空白阻止、防重复和移动端显式发送。
- [x] 对流式未闭合 Markdown、恶意 HTML/URL、长代码局部滚动和中文输入法编写组件测试。

## 7. 最小后端配套与生产托管

- [x] 在首次成功创建 turn 时事务化生成持久化会话标题；只更新初始标题并覆盖并发测试。
- [x] FastAPI static route 与 Vite 输出结构对齐；删除旧原生 JS/CSS 入口。
- [x] 删除旧 `amadeus/web/static/index.html`、`app.js`、`styles.css` 及只验证旧 DOM/脚本文本的测试；不得保留兼容目录、隐藏路由或 fallback。
- [x] Dockerfile 改为 Node + Python 多阶段构建，使用 lockfile 安装并复制静态产物。
- [x] 更新 Compose/运行文档；沿用 owner task 的新配置，禁止恢复任何旧 identity 变量。
- [x] Python 集成测试验证 `/` 和 hashed assets，容器 smoke 验证静态产物，Playwright 通过同源公共 API/SSE 完成浏览器到 PostgreSQL 的链路验证。

## 8. 去除 AI 模板感的视觉审计

- [x] 仅在首个完整可运行 UI 完成后，对 `frontend/src` 运行 `kill-ai-slop/scripts/scan.mjs`；排除依赖、构建产物、lockfile 和生成文件。
- [x] 阅读每个命中源码，按 intentional/slop 人工 triage；不得把 scanner 命中直接等同缺陷。
- [x] 在任何修改前向用户提交分组 `file:line` 报告、原因和建议修复，并等待批准应用的组别。
- [x] 只修改获批组别，优先修共享 theme/token/component，不重排无关代码、不增加依赖。
- [x] 修复后重新扫描，并使用真实浏览器完成桌面与移动端视觉、控制台和主要交互复验；剩余四处为无卡片装饰的 MUI 布局 `Box`，属于 scanner 误报。

## 9. 验证顺序

先窄后宽；PostgreSQL 相关 Python 测试保持单进程串行：

```powershell
Set-Location frontend
pnpm run typecheck
pnpm test -- --run
pnpm run build
pnpm run lint
pnpm run test:e2e

Set-Location ..
python -m pytest tests/web/test_postgres_web_app.py tests/turns -q
python -m ruff check amadeus tests
python -m mypy amadeus
python -m pytest tests -q
docker compose build api worker
docker compose up -d postgres migrate api worker
```

容器启动后执行真实公共行为 smoke：创建/切换会话，发送文本，观察多次正文快照和工具状态，切换到另一会话发送，返回恢复，停止一个 turn，制造可重试失败并重试，刷新后核对时间线，最后检查浏览器控制台与网络请求。

若缺少真实 LLM 配置，必须用确定性流式 provider 完成同等浏览器到 PostgreSQL 的端到端验证，并在报告中明确“未覆盖真实供应商网络”，不能把组件 mock 当成完整集成通过。

## 10. 回滚点与完成条件

- 骨架、状态层、页面、后端配套、Docker 各阶段独立可验证后再继续。
- 若高亮依赖显著扩大首包，保持普通 code block 并将高亮拆为懒加载 chunk；不得阻塞对话主链路。
- 若 EventSource 重连存在重复，先以 `seq` 和 Query 权威快照修复，不改成浏览器内存事实来源。
- 完成时逐条映射 `prd.md` R1-R34 和 acceptance criteria，报告单元、组件、浏览器、后端、容器与真实 LLM 的实际覆盖，并附旧原生前端零残留搜索结果和 `kill-ai-slop` triage/复验结论。

## 11. 规划审批

- 状态：用户已于 2026-07-18 批准 PRD、技术设计与实施计划（含 pnpm、同仓库 `frontend/`、Vitest + Playwright、Axios、旧原生前端零兼容替换等后续修订）。
- 审批只允许后续进入 `task.py start`，不等于本轮已经实施。
