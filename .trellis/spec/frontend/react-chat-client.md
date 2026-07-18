# React 聊天客户端契约

## 场景：可恢复的单用户流式聊天界面

### 1. 范围 / 触发

- 触发：修改 `frontend/src/api`、`streaming`、聊天时间线、主题、FastAPI Web schema 或静态构建链。
- 目标：PostgreSQL/FastAPI 保存权威历史，浏览器只叠加未终态实时状态；断线、终态刷新和跨会话切换不丢失或重复内容。

### 2. 签名

- 普通 HTTP：`createApi(instance)` 提供 bootstrap、sessions、turns、create/cancel/retry；只能经过单一 Axios instance。
- 实时流：`TurnStreamManager.connect(turnId, sessionId)` 使用原生 `EventSource` 连接 `GET /api/turns/{id}/events?after_seq=<lastSeq>`。
- 服务端状态：TanStack Query keys `bootstrap/sessions/session-turns/turn`。
- 实时状态：`useLiveTurnStore.turns[turnId]` 保存 `lastSeq/parts/status/error/connection`，不得保存 `EventSource`。
- 生产构建：`pnpm install --frozen-lockfile && pnpm run build`，Vite base 为 `/static/`，Docker 把 `dist` 复制到 `amadeus/web/static`。

### 3. 契约

- React 只提交资源 ID 和文本，不提交 `user_id`；启动时以 `/api/bootstrap` 返回的 owner 为准。
- Query 是服务器快照；Zustand 是未终态 overlay。终态事件先应用到 overlay，再失效并等待 Query refetch 成功，最后删除 overlay，让服务器 `answer/partial_answer/error` 接管界面。
- 不得在发起 refetch 时立即删除 overlay，否则网络失败或 refetch 窗口会让部分正文闪回或消失。
- SSE `seq <= lastSeq` 必须忽略；协议坏包只显示固定安全提示，不暴露原始 payload/异常。
- 工具 `started` 显示过程行；`completed/failed` 立即变为紧凑摘要。只显示工具名和状态，不显示参数、结果或思考。
- 主题 key 固定为 `amadeus:theme-mode:v1`，只接受 `system/light/dark`；`InitColorSchemeScript` 与 `ThemeProvider` 必须使用同一 key，避免首屏闪烁。
- 窄屏 Drawer 即使 keep-mounted 也不得产生重复 DOM id；可复用控件使用 React `useId()`。

### 4. 验证与错误矩阵

| 条件 | 行为 |
|---|---|
| Axios 非 2xx 且存在安全 `code/detail` | 转为 `ApiError`，不显示未知字段 |
| 网络失败 / 请求取消 | 分别为可重试 `network_error` / 不可重试 `request_cancelled` |
| SSE 重复或乱序 seq | reducer 原样返回，不重复正文或工具 |
| SSE JSON/契约无效 | 关闭连接，保留已收内容并显示安全恢复提示 |
| 终态 refetch 成功 | 删除 overlay，Query 最终快照获胜 |
| 终态 refetch 失败 | 保留 overlay，避免丢失已经展示的内容 |
| 用户主动上滚 | 停止自动跟随并显示“回到底部” |
| owner 与本地记录变化 | 清理旧 session URL 定位，以新 owner 的 sessions 回退 |

### 5. Good / Base / Bad Cases

- Good：`text -> tool -> text -> done` 先按事件顺序展示；工具完成后收起；refetch 成功后最终 answer 接管。
- Base：刷新页面没有 live overlay，直接从 FastAPI turns 恢复 done/failed/cancelled 时间线。
- Bad：终态一到就清除 Zustand，再异步 refetch；网络慢时正文闪空。
- Bad：组件直接 `fetch/axios`，或把 EventSource 放入 Zustand，使认证、清理和 StrictMode 幂等边界分裂。
- Bad：Playwright 只 mock 浏览器请求却宣称验证了 FastAPI/PostgreSQL/worker。

### 6. 必需测试

- Vitest：response guard、Axios 非 2xx/网络/取消、安全 payload、SSE seq 去重与坏包、工具折叠、Markdown 安全、复制反馈、Composer Enter/IME/移动端、滚动保护和主题存储异常。
- Playwright Chromium：使用独立 `amadeus_e2e` PostgreSQL 数据库、真实 FastAPI store 和真实 `TurnWorker`，仅 runner 使用确定性 fixture；覆盖完成、跨会话、停止、失败重试、刷新、Drawer、主题和 Markdown 局部溢出。
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
