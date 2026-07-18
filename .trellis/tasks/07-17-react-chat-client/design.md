# React 单用户聊天客户端技术设计

## 1. 目标与前置依赖

本任务交付一个 React + TypeScript + Vite 的单页客户端，以 FastAPI/PostgreSQL 为权威事实来源，完整承载多会话、流式回答、工具活动、停止、失败保留与重试。

实施前必须满足：

1. `07-18-owner-scoped-web-identity` 已实现并验证服务器注入 owner identity；
2. `07-17-streaming-runtime-sse` 已实现并验证 turn 时间线、typed SSE、取消、重试与安全错误；
3. 前端不得为未完成的依赖增加客户端 `user_id`、轮询私有字段或进程内假流式兼容层。

## 2. 技术栈与目录

新建根目录 `frontend/`：

```text
frontend/
  src/
    api/          # Axios instance、response guards、query keys
    app/          # provider 组合、AppShell、主题
    chat/         # timeline、turn、composer、markdown
    sessions/     # 会话侧栏和选择逻辑
    streaming/    # EventSource manager、Zustand live overlay
    test/         # 测试支持与 fixtures
  package.json
  pnpm-lock.yaml
  tsconfig*.json
  vite.config.ts
```

依赖边界：

- React、TypeScript、Vite；
- MUI、Emotion、MUI icons；
- TanStack Query；
- Zustand；
- Axios（仅普通 HTTP；SSE 仍使用 EventSource）；
- `react-markdown` + `remark-gfm`；
- 代码高亮器只在完成的代码块需要时懒加载；流式中先稳定显示普通 code block；
- Vitest、React Testing Library、MSW 和 Playwright 用于验证。

不引入 Tailwind、shadcn/ui、MUI X 或第二套路由/状态框架。MUI 组件与图标使用直接模块路径导入，避免 barrel import 扩大开发与构建成本。

## 3. 应用边界

```text
FastAPI/PostgreSQL
  -> api client（单一 Axios instance + typed guard）
      -> TanStack Query：服务器快照
  -> EventSource manager（连接资源）
      -> Zustand：未终态 turn 的实时 overlay

React view = Query 快照 + 对应 turn 的 live overlay
```

### 3.1 TanStack Query

只管理服务器状态：

- `['bootstrap']`
- `['sessions']`
- `['session-turns', sessionId]`
- `['turn', turnId]`

bootstrap 与 sessions 没有依赖，启动时并行请求。选定 session 后再请求其 turns，避免无意义拉取全部会话历史。mutation 默认不自动重试，防止网络不确定时重复创建 turn；失败后通过重新读取服务器状态恢复。

### 3.2 Zustand 实时 overlay

状态按 `turn_id` 索引，并记录：

- 最新 `seq` 与累计正文；
- 工具活动列表；
- SSE `connecting/open/reconnecting/closed`；
- 当前 turn 状态和安全错误；
- 所属 `session_id`。

store action 接受完整 typed event，并拒绝 `seq <= lastSeq`。它不保存 Session、完整历史或 EventSource 对象。

### 3.3 EventSource manager

模块级 manager 用 `Map<turnId, EventSource>` 管理资源，负责连接、重连、cursor 和清理。切换会话不会取消正在运行的 turn，也不会让不同 session 共用连接状态。应用从时间线发现所有未终态 turn 后确保其连接存在。

终态事件到达时：

1. 先用终态 payload 更新 live overlay；
2. 更新或失效 `turn` 与 `session-turns` Query；
3. Query 获得权威终态后关闭连接并清理对应 transient overlay；
4. 不把增量另存成第二份历史。

## 4. API 客户端与错误

`api/` 提供单一 Axios instance 和语义函数，不让组件拼 URL 或直接访问 Axios：

- `getBootstrap()`
- `listSessions()` / `createSession()`
- `listSessionTurns(sessionId)`
- `createTurn(sessionId, message)`
- `cancelTurn(turnId)`
- `retryTurn(turnId)`
- `getTurn(turnId)`

Axios instance 只集中处理相对 base URL、JSON、AbortSignal、凭证策略入口和安全错误转换；禁止在 interceptor 中直接导航、显示 toast、修改 React/Zustand 状态或吞掉业务错误。response guard 校验 SSE discriminated union 和关键 HTTP 字段。Axios 非 2xx/网络错误统一转成 `ApiError`；UI 只读取后端安全 `error_code/message/retryable`，不显示未知 response body 或堆栈。

Axios 不参与 SSE。原生 EventSource 无法设置自定义 Authorization header，所以“使用 Axios”不等于已经为 RBAC 完成认证设计。未来如果引入登录/RBAC，服务端授权仍是事实来源，并优先评估同源 HttpOnly Cookie，使 HTTP 与 EventSource 使用同一浏览器凭证；本任务不实现 token 刷新、角色模型或权限 UI。

所有 mutation 禁止自动网络重试。按钮提交期间禁用，响应返回 turn 后立即写入时间线 Query 并连接 SSE。

## 5. 页面和组件

### 5.1 AppShell

- 桌面：约 280px 固定会话栏 + 自适应聊天主区；
- 窄屏：MUI Drawer 展示会话，选择后关闭；
- 当前 session 使用根路径查询参数 `?session=<id>`，刷新可恢复且无需新增服务端 SPA fallback；无效 ID 回退到第一个可用 session。

主要组件：

- `SessionSidebar`：新建、列表、选中状态和各会话活动指示；
- `ChatTimeline`：服务器 turn 时间线与 live overlay 合并；
- `TurnItem`：用户输入、助手正文、终态与重试；
- `ToolActivityList`：紧凑显示安全工具生命周期；
- `MarkdownMessage` / `CodeBlock`：安全 Markdown 与复制；
- `Composer`：文本输入、发送/停止与键盘/IME 契约；
- `ThemeModeControl`：system/light/dark。

### 5.2 时间线与滚动

- `done` 使用最终 answer；未终态优先使用 overlay snapshot；`failed/cancelled` 保留部分正文和显式状态；
- 重试作为关联的新 turn 显示，原失败尝试不折叠或覆盖；
- 用户处于底部附近时跟随流式内容；用户主动上滚后停止自动抢焦点并显示“回到底部”；
- 长列表使用稳定 key、细粒度 turn 订阅和 `content-visibility`，不在每个 delta 重渲染整个侧栏或全部历史。

### 5.3 Composer

- 桌面 `Enter` 发送、`Shift+Enter` 换行；检查 `isComposing` 防止中文输入法误发；
- 移动端 Enter 换行，发送由按钮触发；
- trim 后为空则禁止；请求中防重；当前 session 有活动 turn 时显示停止；
- 按 session 在 App 局部状态保存未发送草稿，切换会话不丢失，但不写 localStorage/Zustand。

## 6. Material 主题

MUI 是唯一主要设计系统。`createTheme`/color schemes 定义：

- 中性石墨/暖灰 surface；
- 单一低饱和 primary；
- typography、shape、spacing、elevation 和 motion；
- `done/failed/cancelled/processing` 的语义状态，不只靠颜色区分；
- light/dark 两套可访问对比度。

主题偏好 key 为带版本的最小值，例如 `amadeus:theme-mode:v1`，只允许 `system/light/dark`，读写必须捕获 localStorage 异常。首屏在 React 绘制前设置 color scheme，避免明显闪烁。

重复样式提取为 `styled` 组件或 theme component override；一次性布局用 `sx`。禁止同时维护 Tailwind utility 或散落原始色值。

视觉设计遵循“先决定、后装饰；一个强调色、一种文案声音；用尺度与空间建立层级；装饰必须表达语义”。避免默认 AI 模板特征：紫靛渐变、玻璃拟态、过量圆角/阴影/药丸标签、卡片嵌套、发光状态点、虚构统计和空泛宣传句。上述规则不是机械禁令；品牌或功能上有明确理由的例外在 `kill-ai-slop` triage 中保留并说明。

## 7. Markdown 安全与性能

- 使用 `react-markdown` + GFM，不启用 `rehype-raw`；模型输出的 HTML 作为文本处理；
- 链接 protocol 只允许安全集合，外链设置 `target="_blank"` 与 `rel="noopener noreferrer"`；
- 表格与代码块自身可横向滚动，页面不溢出；
- 流式期间容忍未闭合 fence，使用普通代码样式；终态后懒加载语法高亮，避免每个 delta 做昂贵高亮；
- 复制按钮复制原始代码文本，并给出 MUI Snackbar 反馈。

## 8. 会话标题

标题生成属于服务器事实而不是浏览器推测。首次创建 turn 的事务中，如果 session 仍无标题或为初始占位，服务器：

1. 折叠所有空白为单个空格并 trim；
2. 按 Unicode 字符截取约 30 个字符，超长追加省略号；
3. 写入 session title；
4. 不调用 LLM。

前端创建 turn 成功后失效 sessions Query。并发保护保证后续消息不会改写首条标题。

## 9. 构建与托管

### 9.1 开发

Vite dev server 代理 `/api` 到 FastAPI，包括 `text/event-stream`；浏览器只使用相对 URL。开发环境不通过 CORS 绕过同源假设。

### 9.2 生产

Docker 多阶段：

1. 前端构建阶段使用项目固定版本的 pnpm，并按 `pnpm-lock.yaml` 冻结安装，再执行 typecheck/test/build；
2. Vite 使用生产 base `/static/`，输出 `index.html` 与 `assets/`；
3. Python 阶段复制产物到 FastAPI 的 `static_dir`；
4. `/` 返回 index，`/static/assets/*` 由现有 StaticFiles 提供。

不提交生成的 `dist/`。仓库中的旧 `amadeus/web/static/index.html`、`app.js`、`styles.css` 全部删除，`amadeus/web/static` 不再承载手写源码，只是生产镜像复制 React 产物的目标目录。Docker 构建和 Python packaging smoke 必须证明产物存在；缺少产物时 `/` 明确 404/不可用，不允许回退旧页面。

现有针对旧 DOM、脚本文本和 CSS 的测试直接删除或改写为 React 构建/公共行为测试，不保留“兼容旧选择器”的断言。整个项目只有一个前端源码入口：`frontend/src`。

## 10. 验证策略

- unit：API guard、query keys、Zustand seq 去重、主题存储、标题规范化；
- component：会话、时间线、Markdown、Composer、错误/取消/重试、响应式 Drawer；
- integration：MSW HTTP + fake EventSource 验证跨 session 并发与终态收口；
- browser：Playwright 在 CI 默认只跑 Chromium，并用确定性 FastAPI/PostgreSQL/流式 worker fixture 覆盖创建并流式完成、跨会话恢复、停止保留部分回答、失败刷新重试、窄屏 Drawer/主题/Markdown 溢出；失败保留 trace，不把真实付费 LLM 或多浏览器矩阵放入每次提交；
- backend：FastAPI 静态产物、首条标题、owner 404 与 SSE 契约；
- bundle：Vite build 成功，MUI 直接导入，代码高亮拆分 chunk，无 Tailwind/shadcn/MUI X，旧原生前端零残留。
- visual：首个完整 UI 后运行 `kill-ai-slop` scanner，仅把结果作为线索；先提交 `file:line` 分组报告，经用户批准后做最小修复，再重新扫描，并通过桌面与移动端真实浏览器截图/交互复验。
