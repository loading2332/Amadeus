# Research: 现状梳理 — 回复流式呈现管线

- **Query**: SSE 事件 → store → 组件渲染的完整链路 + 当前回复渲染短板
- **Scope**: internal
- **Date**: 2026-07-27

## Findings

### 完整数据流(后端 → 前端 → 渲染)

```
LLM delta
  → PersistedTurnStream.publish_content()      amadeus/worker/turn_worker.py:124-133
    节流落库:满 128 字符 或 距上次 ≥100ms 才 flush(turn_worker.py:107-108, 129-133)
  → store.append_content_snapshot → Postgres turn_events(累计快照,单调 seq)
  → SSE 端点轮询 DB,poll_interval=250ms        amadeus/web/sse.py:16, 38
  → EventSource("/api/turns/{id}/events?after_seq=N")
                                                frontend/src/streaming/manager.ts:22-24
  → decodeTurnEvent(严格校验 4 种事件)          frontend/src/streaming/events.ts:52-99
  → useLiveTurnStore.applyEvent                 frontend/src/streaming/store.ts:25-33
  → reduceTurnEvent(纯函数 reducer)             frontend/src/streaming/reducer.ts:48-71
    content_snapshot:算新增后缀 delta,追加到末尾 text part(reducer.ts:73-92)
    tool_activity:按 activityId upsert tool part(reducer.ts:94-113)
  → TurnItem 订阅 state.turns[turnId]           frontend/src/chat/TurnItem.tsx:22
  → parts.map:text → <MarkdownMessage>(lazy);tool → <ToolActivity>
                                                frontend/src/chat/TurnItem.tsx:55-71
  → MarkdownMessage:ReactMarkdown + remark-gfm 全量渲染 part.content
                                                frontend/src/chat/MarkdownMessage.tsx:26-48
```

自动滚动与终态交接:

- `TurnTimeline` 用 `streamSignal`(所有可见 turn 的 lastSeq 拼串)订阅 store,每个事件触发一次 `useLayoutEffect` 滚到底(frontend/src/chat/TurnTimeline.tsx:45-47, 53-55);"跟随/脱离底部" 由 scroll handler 维护(TurnTimeline.tsx:67-77)。
- 收到 `turn_terminal` 后:manager 关闭 EventSource(manager.ts:39-43)→ `handOffTerminalTurn` 先 invalidate react-query(turn/turns/messages/sessions)再 `removeTurn` 移除 live overlay(frontend/src/app/streamManager.ts:6-25)。之后 `TurnItem` 回退渲染权威 `turn.answer`(TurnItem.tsx:25, 72-81)。
- 连接入口:`ChatView` 对所有 ACTIVE 状态 turn 调 `turnStreamManager.connect`(frontend/src/chat/ChatView.tsx:56-59),提交新 turn 后也 connect(ChatView.tsx:143)。

### 关键文件

| 文件 | 职责 |
|---|---|
| `frontend/src/streaming/events.ts` | SSE 事件解码/校验(content_snapshot / tool_activity / turn_status / turn_terminal) |
| `frontend/src/streaming/manager.ts` | EventSource 生命周期、重连状态、terminal 回调 |
| `frontend/src/streaming/reducer.ts` | 快照→delta→parts(text/tool 交错)纯函数 |
| `frontend/src/streaming/store.ts` | zustand:`turns: Record<turnId, TurnStreamState>` |
| `frontend/src/app/streamManager.ts` | 终态交接:refetch 权威数据后移除 live overlay |
| `frontend/src/chat/TurnItem.tsx` | 单轮渲染:用户气泡 + parts/fallback + 思考脉冲点 + 失败重试 |
| `frontend/src/chat/MarkdownMessage.tsx` | ReactMarkdown + remark-gfm + 代码块复制 + URL 白名单 |
| `frontend/src/chat/ToolActivity.tsx` | 工具调用胶囊(started 展开 / 完成后 collapsed) |
| `frontend/src/chat/TurnTimeline.tsx` | 滚动容器、自动跟随、回到底部按钮 |

### 已有的优点(不要在改进中破坏)

- `TurnItem` 外层 `contentVisibility: "auto"` + `containIntrinsicSize`(TurnItem.tsx:33),长会话渲染有跳过优化。
- `TurnItem` 与 `MarkdownMessage` 都 `memo`;`MarkdownMessage` 通过 `lazy()` 单独分包(TurnItem.tsx:15-19)。
- reducer 对乱序/重复事件幂等(`seq <= lastSeq` 丢弃,reducer.ts:49)。
- URL 白名单 `safeUrlTransform`(MarkdownMessage.tsx:66-75)+ 外链 `noopener noreferrer`。
- 自动跟随滚动逻辑完善(阈值 96px + 回到底部按钮)。

### 当前回复渲染的短板(以实际代码为准)

1. **代码块无语法高亮**。`MarkdownMessage.tsx:34-44` 只包了一层带边框的 `<code>`(monospace + `action.hover` 背景),没有任何 highlight 管线;也没有语言标签显示(`className="language-x"` 只透传)。
2. **流式文本按大块跳变,无平滑显现**。后端每 128 字符/100ms 落一个快照(turn_worker.py:107-108),SSE 端点又以 250ms 轮询聚合(sse.py:16),前端每个事件一次性把整段 delta 拼进 text part 并立即渲染 —— 用户看到的是每 ~250ms 跳出一大段文字,而非逐字/逐词显现。无打字机、无 fade-in chunk。
3. **无流式光标/输出中指示**。文本开始输出后(parts 非空),`PendingState` 思考点消失(TurnItem.tsx:82),正文末尾没有闪烁光标或任何 "正在生成" 视觉标记,`finalizing` 状态也无区分。
4. **markdown 全量重解析**。`MarkdownMessage` 的 memo key 是整个 `content` 字符串,流式期间每个快照事件 content 都变 → ReactMarkdown 对整段已积累文本重新走 remark 解析 + 整棵 React 树 diff。回答越长单次解析越贵(O(n) 每事件,累计 O(n²)),没有按 block 分段 memo。
5. **流式中的未闭合 markdown 会闪烁异常形态**。未闭合的 ``` 围栏会把后续所有文本渲染成代码块、未闭合的 `**`/`[` 会先以原文显示再突变 —— 没有任何 "自愈/修补不完整 markdown" 处理。
6. **无数学公式支持**。无 remark-math / rehype-katex / katex 依赖(frontend/package.json:18-32),LaTeX 输出会按原文显示。
7. **markdown 排版样式不完整**(MarkdownMessage.tsx:25 单行 sx):
   - 标题 h1–h6 无样式规则,落到浏览器默认(字号/边距与 MUI 主题脱节);
   - `img` 无 `maxWidth` 约束,大图会撑破气泡;
   - 表格固定 `minWidth: 480`,小表格在移动端也强制横向滚动;无斑马纹/表头底色;
   - `hr`、任务列表 checkbox、脚注等 GFM 元素无样式适配。
8. **自动滚动跟随 250ms 跳变**。`streamSignal` 每事件变化触发 `scrollToBottom(auto)`(TurnTimeline.tsx:53-55),滚动与文本一样一顿一顿;文本平滑化后此处需要联动(改为 rAF 驱动即可顺带解决)。
9. **turn 完成后工具轨迹消失**。live overlay 被 `removeTurn` 移除后只剩 `turn.answer`(TurnItem.tsx:24-25;streamManager.ts:23),`Turn` 契约里没有工具活动字段 → 历史回看不到 "调用过哪些工具"。属于契约级限制,非纯前端可解。
10. **reducer 非前缀快照会丢 tool parts**。当 `content` 不以旧 snapshot 为前缀时(理论上重放/修正场景),parts 被整体替换为单个 text part,已有 tool part 全部丢失(reducer.ts:74-81)。
11. **首个 chunk 有裸文本闪烁**。`MarkdownMessage` 是 lazy chunk,Suspense fallback 是无样式 `<Typography whiteSpace="pre-wrap">`(TurnItem.tsx:58-67),模块加载完成瞬间从纯文本切换到 markdown 排版会跳。
12. **无整条消息复制按钮**。只有代码块级复制(MarkdownMessage.tsx:40),没有 "复制整条回答"。

## Caveats / Not Found

- 前端收到的 chunk 粒度本质受后端 `flush_characters=128 / flush_interval=0.1s / poll_interval=0.25s` 限制;纯前端平滑显现(客户端匀速吐字)可以完全掩盖这一粒度,不必动后端。
- 未发现任何节流/合帧代码(store 每事件直接 set);但事件频率本身 ≤4/s,渲染频率不是当前瓶颈,单次全量重解析才是。
- `motion`(motion/react)目前只用于 fade-up 入场(frontend/src/ui/motion.ts),流式文本未使用动画。
