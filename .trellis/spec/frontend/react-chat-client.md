# React 聊天客户端契约

## 场景：可恢复的单用户流式聊天界面

### 1. 范围 / 触发

- 触发：修改 `frontend/src/api`、`streaming`、聊天时间线、主题、FastAPI Web schema 或静态构建链。
- 目标：PostgreSQL/FastAPI 保存权威历史，浏览器只叠加未终态实时状态；断线、终态刷新和跨会话切换不丢失或重复内容。

### 2. 签名

- 普通 HTTP：`createApi(instance)` 提供 bootstrap、sessions、turns、create/cancel/retry；只能经过单一 Axios instance。
- 实时流：`TurnStreamManager.connect(turnId, sessionId)` 使用原生 `EventSource` 连接 `GET /api/turns/{id}/events?after_seq=<lastSeq>`。
- 服务端状态：TanStack Query keys `bootstrap/sessions/session-turns/turn`。
- 会话标题：`PostgresTurnStore.create_turn(user_id, session_id, content, retry_of_turn_id=None)` 在首个非重试 turn 的事务内调用 `title_from_first_message(content)` 更新 `conversation_sessions.title`；`useCreateTurnMutation()` 成功后失效 `queryKeys.sessions`。
- 恢复入口：启动页调用 `bootstrap.refetch()` 与 `sessions.refetch()`；`TurnTimeline.onRetry` 调用当前 turns query 的 `refetch()`；新建与发送失败分别复用原有 `createSession.mutate()` 和 `createTurn.mutate()`。
- 实时状态：`useLiveTurnStore.turns[turnId]` 保存 `lastSeq/parts/status/error/connection`，不得保存 `EventSource`。
- 回复渲染：`MarkdownMessage({ content, streaming?, cursor? })` 按 `marked.lexer` 顶层 block 切块渲染,块用索引 key;`useSmoothText(target, done): { text, settled }` 是 UI 层唯一的平滑吐字入口,只作用于活跃 turn 的最后一个 text part。
- 生产构建：`pnpm install --frozen-lockfile && pnpm run build`，Vite base 为 `/static/`，Docker 把 `dist` 复制到 `amadeus/web/static`。

### 3. 契约

- React 只提交资源 ID 和文本，不提交 `user_id`；启动时以 `/api/bootstrap` 返回的 owner 为准。
- Query 是服务器快照；Zustand 是未终态 overlay。终态事件先应用到 overlay，再失效并等待 Query refetch 成功，最后删除 overlay，让服务器 `answer/partial_answer/error` 接管界面。
- `turn_terminal: done` 是回答生命周期的唯一前端终态；后台 memory job
  不进入 SSE、Query 或 Zustand。完整回答字符可见后 500ms 内必须隐藏停止入口、
  恢复发送入口并启用 Composer，不得等待记忆抽取状态。
- 不得在发起 refetch 时立即删除 overlay，否则网络失败或 refetch 窗口会让部分正文闪回或消失。
- SSE `seq <= lastSeq` 必须忽略；协议坏包只显示固定安全提示，不暴露原始 payload/异常。
- 工具 `started` 显示过程行；`completed/failed` 立即变为紧凑摘要。只显示工具名和状态，不显示参数、结果或思考。
- 主题 key 固定为 `amadeus:theme-mode:v1`，运行时只接受 `light/dark`；没有有效存储值时默认深色，旧的 `system` 值也归一化为深色。主题控件是只显示太阳/月亮的单击切换图标，不显示文字或多选菜单；`InitColorSchemeScript` 与 `ThemeProvider` 必须使用同一 key 和默认值，避免首屏闪烁。
- 桌面侧栏折叠状态由 `App` 单点持有，并通过 `amadeus:sidebar-collapsed:v1` 持久化；占位宽度只能在展开 `280px` 与完全收起 `0px` 之间变化。收起时侧栏必须 `inert`，展开与新建入口由 `ChatView` 左上角浮动图标承接，创建会话仍回到 `App` 的 mutation 边界。
- 聊天区不渲染顶栏、会话标题或横向分隔线。移动端的 Drawer 入口与桌面完全收起态的展开/新建入口绝对定位在聊天画布左上角；时间线在存在浮动入口的断点留出顶部空间，首条消息不得被遮挡。
- 空会话欢迎提示必须在 `TurnTimeline` 的可用视口内水平、垂直居中。只在 `rows.length === 0` 且首条消息没有正在提交时显示；`createTurn` 进入 pending 后立即隐藏，成功后由 Query 中的真实 turn 接管，失败后恢复空状态以允许重试。
- Composer 保持单一圆角矩形外壳,圆角固定 `28px`,不得使用 `borderRadius: 999`(多行高度下胶囊两端成大半圆,顶/底行文字会伸出弧线);textarea 左缘距 `composer-shell` 左缘不得小于 `20px`;该留白由输入槽的左内边距承担,不得整体移动发送按钮或改变单行垂直居中、多行底部对齐。聚焦粗描边必须用 `outline` + 负 `outline-offset` 叠加(纯绘制、零布局);不得聚焦时改 border 宽度(内容位移)或用 border+inset box-shadow 双线拼描边(大圆角下两条弧光栅化错位产生锯齿)。
- 流式呈现属于 UI 层:store/reducer/manager 保存并交接权威全文,不得为打字机、光标等呈现需求改动 `frontend/src/streaming` 的事件与数据结构(useSmoothText 除外,它只消费 target 文本)。`turn_terminal` 后现有的 overlay 移除→回退 `turn.answer` 链路就是"瞬间补齐"路径,不需要额外补齐逻辑。
- Markdown 分块 memo 的前提是引用稳定:remark/rehype 插件数组、components 映射、`markdownSx` 必须模块级常量,回调经空依赖 `useCallback`;`remend` 自愈只在 `streaming` 时应用,终态渲染权威原文。代码高亮用 `rehype-highlight` 且 `detect: false`;暗色 token 规则必须作用于 `[data-amadeus-color-scheme="dark"]`(项目自定义 colorSchemeSelector,不是 MUI 默认的 `data-mui-color-scheme`),且删除 hljs 主题的 `.hljs` 背景规则,背景由容器持有。
- 流式光标是 CSS `::after` 脉冲圆点,挂在最后一个文本叶子元素(段落/标题/列表项/引用内段落)行尾;尾块是代码围栏或表格时不显示(内容增长本身即进度信号);仅当回答尾部 part 是文本时开启;`prefers-reduced-motion` 下静止常显。
- 自动跟随滚动由 ResizeObserver 观察时间线内容尺寸驱动,且仅在 following 状态滚底;不得用 store 事件信号(如 lastSeq 拼串)触发滚动——吐字改为逐帧后事件粒度与内容高度变化不再对应。
- 会话列表行(`ListItemButton`)必须显式 `transition: "none"` 覆盖 MUI 内置的 background-color 150ms 过渡:新会话插入顶部时旧选中行被挤到下一行,残留的选中色淡出会被用户看成高亮闪跳。
- 用户上滚离开 following 状态时，“回到底部”入口必须是固定 `40px` 的圆形 `IconButton`，只渲染向下箭头；仅通过 `aria-label="回到底部"` 提供辅助技术语义，不显示按钮文字、Tooltip 或点击涟漪。点击后使用 `behavior: "smooth"` 平滑滚动；returning 状态下忽略普通的 `96px` following 阈值，按钮持续显示，只有底部间距进入 `2px` 容差后才恢复 following 并隐藏。
- 拉丁字形使用随前端产物本地打包的 `Inter Variable`，中文依次回退到 `Noto Sans SC`、`Microsoft YaHei UI` 与 `PingFang SC`；全局字距为 `0`，不得依赖浏览器默认系统字体作为首选字体。
- 聊天页只能有一个纵向滚动所有者：`App` 固定 `height: 100dvh` 并隐藏外层溢出，`main` 与 `ChatView` 使用 `height: 100%`、`minHeight: 0` 传递确定高度，`TurnTimeline` 承担 `overflowY: auto`。侧栏继承外壳 `100%` 高度；不得用 `minHeight: 100dvh` 让长会话撑高 document，否则侧栏会断层且自动跟随失效。
- 移动 Drawer 的 `mobileOpen` 与桌面折叠偏好相互独立。会话列表按 `updatedAt ?? createdAt` 的本地日历日分为“今天 / 昨天 / 更早”；无效、缺失或未来时间进入“更早”，不得用固定 24 小时差代替日历日比较。
- 窄屏 Drawer 即使 keep-mounted 也不得产生重复 DOM id；可复用控件使用 React `useId()`。
- 首条消息标题是服务端持久化事实：合并空白、最多保留 30 个 Unicode 字符，超长追加 `…`。React 不得复制该算法或逐会话读取 turns 推导标题；空 session 的唯一占位文本为“新对话”，不得显示内部 session ID。
- 首屏、turns、新建 session 与创建 turn 的失败反馈必须靠近原操作并复用现有 Query/mutation。创建 turn 失败不得清空按 session 保存的 draft；只有 mutation 成功后才能清空并连接 SSE。
- 桌面 `md` 断点使用接近原则组织 turn：用户消息到本轮回答为 `16px`，相邻 turn 为 `48px`；移动端密度不由该桌面规则修改。

### 4. 验证与错误矩阵

| 条件 | 行为 |
|---|---|
| Axios 非 2xx 且存在安全 `code/detail` | 转为 `ApiError`，不显示未知字段 |
| 网络失败 / 请求取消 | 分别为可重试 `network_error` / 不可重试 `request_cancelled` |
| SSE 重复或乱序 seq | reducer 原样返回，不重复正文或工具 |
| SSE JSON/契约无效 | 关闭连接，保留已收内容并显示安全恢复提示 |
| 终态 refetch 成功 | 删除 overlay，Query 最终快照获胜 |
| 终态 refetch 失败 | 保留 overlay，避免丢失已经展示的内容 |
| 完整回答已可见且收到 `done` | 500ms 内停止按钮消失、发送入口出现、输入框可编辑；memory job 仍可在后台运行 |
| 用户主动上滚 | 停止自动跟随并显示“回到底部” |
| owner 与本地记录变化 | 清理旧 session URL 定位，以新 owner 的 sessions 回退 |
| 桌面侧栏完全收起 | 外壳最终宽度为 `0px`，聊天区接管剩余宽度，左上角浮动显示展开与新建图标 |
| 空会话提交第一条消息 | 点击发送后欢迎提示立即消失，不等待 HTTP 响应；创建失败时可恢复 |
| Composer 单行空输入 | 文字起点避开左侧圆弧，距外壳至少 `20px`；上下间距差不超过 `1px` |
| 用户上滚离开底部 | 显示等宽等高的圆形向下箭头按钮；可访问名称为“回到底部”，可见文字和悬停提示为空；点击后平滑滚动，动画期间保持显示，实际到底后隐藏 |
| 长会话超过可视高度 | document 高度保持等于视口，侧栏满高不移动，`TurnTimeline` 内部滚动并在 following 状态下停在底部 |
| 本地时间为空、无效或未来 | 会话稳定归入“更早”，列表仍保持后端返回顺序 |
| bootstrap 或 sessions 查询失败 | 显示“重试连接”，同时 refetch 两个启动查询，不刷新 document |
| 当前 session 的 turns 查询失败 | 时间线原位显示“重新载入”，只 refetch 当前 query |
| 创建 session 失败 | 不插入本地假 session；展开侧栏或收起态入口附近显示“重试新建” |
| 创建 turn 失败 | 保留当前 session 草稿并显示“重试发送”；成功后才清空草稿 |
| 首个非重试 turn 创建成功 | 同一数据库事务持久化首条消息摘要；sessions query 刷新后侧栏更新，页面刷新后保持 |
| 流式中途未闭合 `**`/``` 围栏 | remend 自愈渲染,后续文本不塌成代码块;终态以权威原文重渲染 |
| 流式尾块是代码围栏/表格 | 不显示光标圆点,代码块随内容增长即进度信号 |
| 系统开启减弱动态效果 | 吐字直达全文、光标静止、消息无位移动画 |
| 创建会话插入列表顶部 | 选中色块即时切换到新行,旧行不得出现过渡淡出残影 |

### 5. Good / Base / Bad Cases

- Good：`text -> tool -> text -> done` 先按事件顺序展示；工具完成后收起；refetch 成功后最终 answer 接管。
- Good：memory worker 被阻塞时，聊天仍在 `done` 到达后立即结束生成态，用户可以输入下一轮。
- Good：桌面侧栏以 `280px -> 0px` 平滑退出布局，刷新后保持偏好；移动端仍通过独立 Drawer 打开同一套导航内容。
- Good：长会话只增加时间线的 `scrollHeight`；浮动导航、Composer 和侧栏保持在视口内，新增流式内容自动跟随到底部。
- Good：用户上滚后只看到圆形向下箭头；悬停无文字提示，点击无涟漪，按钮随平滑滚动保持可见并在实际到底后稳定退出。
- Good：空会话欢迎提示由占满时间线的 Grid 双向居中，首条 turn mutation 进入 pending 时立即隐藏。
- Good：Composer 外壳保持对称胶囊，输入槽使用更大的左内边距避开圆弧，发送按钮位置不变。
- Good：创建 turn 失败后输入值保持不变，用户在 Composer 下方重试；成功后 draft 清空，Query/SSE 接管时间线。
- Good：首条消息写 turn 和 session 标题发生在同一后端事务，前端只失效 sessions query。
- Good：桌面轮内间距小于轮间间距，用户无需额外边框或卡片也能识别一问一答。
- Good：长回复流式期间只有尾部 block 重解析重渲染,历史 block 引用稳定命中 memo;吐字逐帧推进时输入框与滚动不卡顿。
- Base：刷新页面没有 live overlay，直接从 FastAPI turns 恢复 done/failed/cancelled 时间线。
- Bad：终态一到就清除 Zustand，再异步 refetch；网络慢时正文闪空。
- Bad：增加 memory job 轮询或把 memory 状态合并进 active turn；这会把后台派生计算重新带回用户关键路径。
- Bad：组件直接 `fetch/axios`，或把 EventSource 放入 Zustand，使认证、清理和 StrictMode 幂等边界分裂。
- Bad：桌面收起后保留固定窄栏，或让 `ChatView` 直接操作 localStorage / create-session mutation，造成状态和副作用边界分裂。
- Bad：外壳和聊天 Grid 只设 `minHeight: 100dvh`，让内容把 body 撑高，再依赖浏览器页面滚动承载消息。
- Bad：只用 `rows.length === 0` 控制欢迎提示，导致首条消息已提交但 HTTP 尚未返回时提示仍滞留。
- Bad：Composer 输入槽使用四向相同的小内边距，让文字起点贴入左侧圆弧；或整体增加外壳左内边距导致按钮布局随之偏移。
- Bad：Playwright 只 mock 浏览器请求却宣称验证了 FastAPI/PostgreSQL/worker。
- Bad：在 React 中截断首条消息生成临时标题，或为每个 session 请求 turns，造成刷新、客户端与后端事实不一致。
- Bad：发送失败后立即清空 draft，或用 toast 承担唯一恢复入口，让错误与触发操作分离。
- Bad：Playwright 用全页面 `getByText(/消息内容/).last()` 断言时间线；首条消息成为侧栏标题后，隐藏 Drawer 和当前 turn 都可能匹配。应先定位具体 `article[aria-label="一轮对话"]`。
- Bad：为打字机效果改 reducer/store 数据结构,或在事件处理里做逐字 setState;平滑吐字只属于 UI hook。
- Bad：MemoizedBlock 的 components/plugins 在组件体内重建,导致每帧引用变化、块级 memo 全部失效,长回复 O(n²) 重解析。

### 6. 必需测试

- Vitest：response guard、Axios 非 2xx/网络/取消、安全 payload、SSE seq 去重与坏包、工具折叠、Markdown 安全、复制反馈、Composer Enter/IME/移动端、发送失败保留 draft 与重试、启动查询/turns 查询原位重试、创建 session 失败反馈、滚动保护、“回到底部”无点击涟漪、使用 `behavior: "smooth"`、中间位置保持显示且实际到底后隐藏、主题存储异常和旧值归一化，以及会话日期分组的本地日历日/无效时间边界。回复渲染新增必测:useSmoothText(fake rAF 推进/done 补齐/reduced-motion 直达/卸载清理)、分块渲染计数(尾块外 0 次重渲染)、高亮 token 与语言标签、streaming 自愈与终态原文、光标出现/消失、复制全文内容与可见性。lazy chunk 内元素的首个断言用 `findBy*` 并放宽 timeout,全量并行跑时模块加载可能超过默认 1s。
- Playwright Chromium：使用独立 `amadeus_e2e` PostgreSQL 数据库、真实 FastAPI store 和真实 `TurnWorker`，仅 runner 使用确定性 fixture；覆盖完成、跨会话、停止、失败重试、网络注入后的 session/turn 原位重试与 draft 保留、首条消息标题即时刷新和页面刷新后持久化、桌面轮内/轮间几何关系、刷新、Drawer、主题、Markdown 局部溢出、桌面 `280px -> 0px -> 280px`、无聊天顶栏、欢迎提示双向居中和发送后消失、Composer 左侧留白与单行/多行对齐、浮动入口可达、本地字体生效、长会话 document/侧栏/时间线滚动边界、“回到底部”无 Tooltip、平滑滚动期间持续显示且实际到底后稳定退出、收起态新建、折叠偏好持久化和 keep-mounted DOM id 唯一性。标题持久化必须走真实后端；浏览器路由注入只用于制造网络失败。
- 回答终态时序：确定性 runner 的完整回答可见后开始计时，断言停止按钮消失、
  发送入口出现且输入框恢复的总时间不超过 500ms；后端因果测试另行证明
  该终态不依赖 post-response memory 完成。
- 构建：typecheck、ESLint、Vite build 无大 chunk 警告；Docker 冻结 lockfile 构建并检查 hashed assets。
- 视觉：`kill-ai-slop` 扫描后逐项人工判断；MUI 布局 `Box` 不是卡片，不能为了归零而隐藏或改坏结构。

### 7. 错误与正确示例

#### 错误

```ts
onTerminal(() => {
  liveStore.removeTurn(turnId);
  void queryClient.invalidateQueries({ queryKey: queryKeys.turns(sessionId) });
});
```

#### 正确

```ts
onTerminal(() => {
  void queryClient
    .invalidateQueries({ queryKey: queryKeys.turns(sessionId) })
    .then(() => liveStore.removeTurn(turnId));
});
```

#### 错误：让页面承载聊天滚动

```tsx
<Box sx={{ minHeight: "100dvh" }}>
  <ChatView />
</Box>
```

#### 正确：固定外壳，只让时间线滚动

```tsx
<Box sx={{ height: "100dvh", overflow: "hidden" }}>
  <Box component="main" sx={{ height: "100%", minHeight: 0, overflow: "hidden" }}>
    <ChatView />
  </Box>
</Box>
```

#### 错误：只根据服务端快照显示欢迎提示

```tsx
const showWelcome = rows.length === 0;
```

#### 正确：提交意图立即参与派生状态

```tsx
const submittingFirstTurn = rows.length === 0 && createTurn.isPending;
const showWelcome = rows.length === 0 && !submittingFirstTurn;
```

#### 错误：胶囊输入槽使用过小的对称留白

```tsx
slotProps={{ input: { sx: { p: 0.5 } } }}
```

#### 正确：只扩大文字侧的水平安全区

```tsx
slotProps={{ input: { sx: { py: 0.5, pr: 0.5, pl: 1.5 } } }}
```

#### 错误：点击时提前进入 following

```tsx
onClick={() => {
  updateFollowing(true);
  scrollToBottom(viewport.current, "smooth");
}}
```

#### 正确：滚动中保持按钮，实际到底后再进入 following

```tsx
onClick={() => {
  returningToBottomRef.current = true;
  scrollToBottom(viewport.current, "smooth");
}}

onScroll={(event) => {
  if (returningToBottomRef.current && isAtBottom(event.currentTarget)) {
    returningToBottomRef.current = false;
    updateFollowing(true);
  }
}}
```

#### 错误：前端复制首条消息摘要规则

```ts
const optimisticTitle = message.replace(/\s+/g, " ").slice(0, 30);
queryClient.setQueryData(queryKeys.sessions, patchTitle(optimisticTitle));
```

#### 正确：后端标题提交后刷新权威 sessions

```ts
useMutation({
  mutationFn: ({ sessionId, message }) => api.createTurn(sessionId, message),
  onSuccess: () => void queryClient.invalidateQueries({ queryKey: queryKeys.sessions }),
});
```

#### 错误：在整页查找可能同时出现在标题与消息中的文本

```ts
await expect(page.getByText(/失败/).last()).toBeVisible();
```

#### 正确：先限定到公开的 turn 容器

```ts
const turn = page.locator('article[aria-label="一轮对话"]').filter({ hasText: userMessage });
await expect(turn.getByText("模型响应超时，请重试")).toBeVisible();
```
