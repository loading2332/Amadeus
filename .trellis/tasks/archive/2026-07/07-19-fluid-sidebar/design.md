# 重塑灵动侧栏：技术设计

## 设计原则

“完全收起”的本质不是把侧栏换成更窄的侧栏，而是让导航区域退出布局。桌面根容器仍使用 Flex：侧栏外壳负责占据 `280px` 或 `0px`，聊天主区使用 `flex: 1` 自动获得剩余空间。这样动画只改变一个明确的布局变量，聊天区不会被浮层遮挡。

## 状态与边界

### 桌面展开态

- `App` 持有 `desktopCollapsed = false`。
- `desktop-sidebar-shell` 宽度为 `280px`，内部渲染 `SessionSidebar`。
- `SessionSidebar` 提供收起按钮、新对话导航行、分组会话列表和主题按钮。
- `ChatView` 不显示桌面专用的展开与新建入口。

### 桌面完全收起态

- `App` 持有 `desktopCollapsed = true`，并通过现有 `writeSidebarCollapsed` 持久化。
- 侧栏外壳宽度过渡到 `0px`，内部内容不可见且不可交互。
- `ChatView` 不渲染顶栏和会话标题；聊天画布左上角浮动显示桌面专用的“展开侧边栏”和“新对话”图标按钮。
- 新建按钮复用 `App.createNewSession`，创建中禁用并显示进度，避免绕过现有 mutation 和选中状态更新。

### 移动端 Drawer

- `mobileOpen` 与 `desktopCollapsed` 保持独立。
- 移动端聊天画布左上角始终浮动显示“打开会话列表”入口，不为它创建独立顶栏。
- Drawer 内使用相同的 `SessionSidebar` 展开内容，并显示关闭按钮；桌面专用图标通过 MUI 断点隐藏，避免重复可访问入口。

## 组件契约与事件流

```text
App
├─ desktopCollapsed + mobileOpen
├─ createNewSession()
├─ toggleDesktopSidebar()
├─ SessionSidebar
│  ├─ onCreate -> App.createNewSession
│  ├─ onSelect -> App.selectSession
│  └─ onToggleCollapse -> App.toggleDesktopSidebar（仅桌面）
└─ ChatView
   ├─ desktopSidebarCollapsed
   ├─ creatingSession
   ├─ onOpenSessions -> 打开移动 Drawer
   ├─ onOpenDesktopSidebar -> App.toggleDesktopSidebar
   ├─ onCreateSession -> App.createNewSession
   └─ TurnTimeline.submittingFirstTurn -> 首条消息提交期间隐藏欢迎提示
```

`App` 继续作为布局状态和创建会话副作用的唯一所有者。`ChatView` 只根据 props 呈现入口并发出意图，不直接访问本地存储或会话 mutation。

## 会话分组

新增可单元测试的纯函数，将 `SessionSummary[]` 转换为固定顺序的非空分组：

```ts
type SessionGroupKey = "today" | "yesterday" | "earlier";
type SessionGroup = { key: SessionGroupKey; label: string; sessions: SessionSummary[] };
```

算法先把 `now` 与每个会话的 `updatedAt ?? createdAt` 归一到本地当天零点，再比较日历日差：差值为 `0` 归“今天”，为 `1` 归“昨天”，其余归“更早”。日期为空、解析失败或位于未来时归“更早”，保证分组稳定且不伪造时间含义。保持后端返回的会话顺序，不在前端重复排序。

## 视觉与交互

- 侧栏使用 `background.paper` / `text.primary` / `divider` 等主题 token，不固定为某个深色值。
- 侧栏与聊天区通过轻微的语义分隔体现层级，不使用厚重硬边界。
- 新对话和会话项共用导航行语言：紧凑高度、最多单行、圆角不超过 8px。
- 选中态使用 `action.selected`，hover 使用 `action.hover`，键盘焦点使用 `focusVisible` 可见轮廓。
- 宽度动画统一为 `200ms`，缓动使用主题标准 easing；`prefers-reduced-motion: reduce` 时立即切换。
- 图标按钮使用 `aria-label` 补充无文字控制的语义；是否显示 Tooltip 由具体交互决定，“回到底部”入口不显示悬停提示。
- 聊天主区不显示会话标题、顶栏背景或横向分隔线；浮动入口所在断点为时间线增加顶部内边距，避免与首条消息重叠。
- 全局拉丁字形使用本地打包的 `Inter Variable`，中文优先使用 `Noto Sans SC`；字距固定为 `0`，导航中的异常粗字重统一收敛为 `600`。
- 空会话欢迎提示使用占满 `TurnTimeline` 可用高度的 Grid 容器双向居中，不用固定 `minHeight` 模拟位置。`rows.length === 0` 且首条消息未提交时才显示；mutation 进入 pending 后立即隐藏，创建失败则恢复空状态供用户重试。
- Composer 的外壳保持完整胶囊圆角，文本输入槽单独增加左内边距，使 textarea 起点距外壳左缘至少 `20px`。右内边距、发送按钮和上下内边距不随之改变，避免为了修正左侧视觉关系而破坏按钮或多行对齐。
- “回到底部”使用固定 `40px` 的圆形 `IconButton`，界面只显示向下箭头。仅以 `aria-label` 提供辅助技术语义，不渲染按钮文字或 Tooltip；禁用点击涟漪。点击后进入临时的 returning 状态并平滑滚动：滚动期间按钮保持显示，只有底部间距进入 `2px` 容差时才恢复 following 并隐藏；该高频状态使用 ref，不让每一帧触发 React 重渲染。

## 兼容性与失败边界

- 本地存储不可用时，现有读写函数已降级为内存态，不阻断 UI。
- 首屏查询失败时保留居中的连接状态，并由“重试连接”同时重新获取 bootstrap 与 sessions；不要求刷新 document。
- 创建会话失败不产生虚假的本地会话。展开态在“新对话”导航行下方显示紧凑反馈，完全收起态在浮动入口旁显示同一失败事实，两者仍调用 `App.createNewSession`。
- 选中会话的 turns 查询失败时由 `TurnTimeline` 显示“重新载入”，事件回到 query 的 `refetch()`，不绕过 TanStack Query 缓存。
- 创建 turn 的 HTTP 请求失败时，`ChatView` 不清空按 session 保存的草稿；`Composer` 在胶囊下方显示“重试发送”，并复用同一个 `onSend` 意图。只有 mutation 成功后才清空草稿并连接 SSE。
- 侧栏内容固定 `280px`，外壳裁剪宽度动画，避免列表文字在过渡中重新换行导致垂直抖动。
- 无会话或无有效日期时仍渲染稳定结构，不出现空分组标题。

## 会话标题数据流

标题的事实来源是持久化 session，而不是浏览器派生状态：

```text
首条用户消息
→ POST /api/messages
→ PostgresTurnStore.create_turn() 同一事务写入 turn 与 session.title
→ useCreateTurnMutation() 失效 sessions query
→ /api/sessions 返回持久化标题
→ SessionSidebar 显示摘要
```

摘要继续由后端 `title_from_first_message()` 单点负责：合并空白、最多保留 30 个 Unicode 字符并在截断时追加省略号。前端只在尚无标题的空会话显示“新对话”，不得复制截断规则或读取 turns 来临时拼标题。这样刷新、切换浏览器或未来增加其他客户端时，所有消费者看到同一个标题。

## 桌面对话分组

视觉分组遵循接近原则：空间越近，用户越容易把元素理解为同一组。桌面 `md` 断点将用户消息到本轮回答的间距收紧为 `16px`，相邻 turn 之间扩大为 `48px`。该变化只作用于桌面断点，本轮不调整移动端密度。

## 滚动边界

应用外壳固定为 `100dvh` 并隐藏外层溢出，`main` 与 `ChatView` 通过 `height: 100%`、`minHeight: 0` 传递确定高度。侧栏继承外壳高度，不参与 document 滚动；`TurnTimeline` 是聊天页唯一的纵向滚动容器。这样长会话只增加时间线的 `scrollHeight`，不会撑高 document，也让现有自动跟随逻辑始终操作正确的元素。

## 回滚策略

改动仅限前端组件、纯分组函数及测试。若宽度动画产生不可接受的布局问题，可保留完全收起状态模型并临时取消 transition；无需回滚本地存储键或后端数据。

## 架构关联

- 产品能力：提升 React 单用户聊天客户端的会话导航效率和主题一致性。
- 公开行为证据：用户可完全收起/展开侧栏、从收起态创建会话、看到按日期分组的会话，并在刷新后保留偏好。
- Akashic 参考：无对应机制；本任务不改变 Agent、记忆或运行时边界。
