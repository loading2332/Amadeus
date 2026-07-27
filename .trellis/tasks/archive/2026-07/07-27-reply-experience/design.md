# 技术设计 — 改进前端回复效果

## 总体架构

改动集中在两层,不动 streaming store/reducer 的数据结构:

```
store(目标全文 target)                      —— 不变
  └─ TurnItem
       └─ useSmoothText(target, done)       —— 新增:显示文本 visible = target.slice(0, n)
            └─ MarkdownMessage(content=visible, streaming)
                 ├─ remend(content)          —— streaming 时自愈
                 ├─ marked.lexer 切块        —— 尾块外全部 memo
                 └─ ReactMarkdown(每块)      —— + rehype-highlight
```

关键决策(依据 research/streaming-render-options.md):

- **平滑吐字放在 UI 层**(hook),store 仍保存权威全文。原因:reducer 幂等性与终态交接逻辑零改动;`turn_terminal` 后 store 被移除、回退 `turn.answer` 的现有链路天然成为"补齐"路径。
- **吐字与分块 memo 必须同批**:visible 每帧变化,若仍整段重解析则 O(n) × 60fps 不可接受;分块后每帧只重解析尾块。
- **remend 只在 streaming=true 时应用**;终态(fallback 渲染 `turn.answer`)不经过 remend,保证权威内容原样。

## 模块设计

### 1. `frontend/src/streaming/useSmoothText.ts`(新增)

```ts
function useSmoothText(target: string, done: boolean): { text: string; settled: boolean }
```

- 内部 state 仅 `visibleLength`;rAF 循环里按帧推进:`step = clamp(2, remaining / 24, 48)` 字符/帧(自适应:buffer 大则加速,避免落后太多)。
- `done === true` 或 `prefers-reduced-motion`(`useReducedMotion()` from motion/react)→ 直接 `visibleLength = target.length`,不起 rAF。
- target 变短(理论上不发生,防御)→ 直接对齐。
- `settled = visibleLength >= target.length`,供光标与滚动联动使用。
- 只对**活跃 turn 的最后一个 text part** 启用(TurnItem 判定),历史 parts 直接整段显示。

### 2. 流式光标

- 位置:`MarkdownMessage` 不感知光标;光标由 TurnItem 在活跃 text part 之后渲染独立 `<Box component="span">`(避免侵入 markdown 树)。
- 样式:`display: inline-block; width: 8px; height: 1em; bgcolor: text.primary; animation: blink 1s steps(2) infinite`;`prefers-reduced-motion` 下 `animation: none`(常亮)。
- 生命周期:`isActive(status)` 期间显示(含 finalizing);终态消失。

### 3. `MarkdownMessage` 分块重构

```tsx
interface Props { content: string; streaming?: boolean }
```

- `streaming` 默认 false;TurnItem 对活跃 turn 传 true。
- 内部:
  1. `const healed = streaming ? remend(content) : content;`
  2. `const blocks = useMemo(() => marked.lexer(healed).map(t => t.raw), [healed]);`
  3. 渲染 `blocks.map((raw, i) => <MemoizedBlock key={i} raw={raw} />)`;`MemoizedBlock = memo(({raw}) => <ReactMarkdown ...>{raw}</ReactMarkdown>)`——流式期间只有最后一块 raw 变化,前面块引用稳定命中 memo。
  4. key 用索引:块只会在尾部增长/变化,索引稳定。
- 现有 components 映射(a/table/code)与 `safeUrlTransform`、复制代码逻辑提为模块级常量,供每个 MemoizedBlock 共享(避免每渲染重建导致 memo 失效——**注意 components 对象引用必须稳定**)。
- Snackbar 状态提升到 MarkdownMessage 顶层不变;copyCode 回调经 context 或模块级事件传入?——直接把 `onCopy` 放进模块级 mitt 不必要,采用:MemoizedBlock 接受稳定的 `onCopyCode` prop(useCallback 包裹,依赖为空,通过 ref 转发 setCopyNotice)。

### 4. 语法高亮

- `rehypePlugins={[[rehypeHighlight, { detect: false }]]}` 加入每块 ReactMarkdown。
- 语言标签:code 组件从 `className` 提取 `language-x`,块级代码容器右上角(复制按钮左侧)显示 `<Typography variant="caption">x</Typography>`。
- 主题 CSS:新增 `frontend/src/chat/highlight.css`,内容为 github.css 与 github-dark.css 的合并——亮色规则原样,暗色规则包在 `[data-amadeus-color-scheme="dark"] &` 作用域下(注意:项目的 colorSchemeSelector 是 `data-amadeus-color-scheme`,不是默认的 `data-mui-color-scheme`,见 frontend/src/app/theme.ts:5)。由 `MarkdownMessage.tsx` import,随 lazy chunk 加载。
- hljs 的 `.hljs` 背景色规则删除,沿用现有代码块容器背景,只保留 token 前景色,避免与 MUI 容器样式打架。

### 5. 排版补全(MarkdownMessage 容器 sx)

拆成模块级 `markdownSx` 常量:

- `& h1..h6`:fontSize 对齐 MUI h5/h6/subtitle1/subtitle2/body1(缩一档,聊天气泡里 h1 不应是页面级大小),`mt: 3, mb: 1.5`,`fontWeight: 600`。
- `& img`: `maxWidth: "100%", borderRadius: 1`。
- `& table`: 去 `minWidth: 480`;`& th`: `bgcolor: "action.hover", fontWeight: 600`。
- `& hr`: `border: 0, borderTop: "1px solid", borderColor: "divider", my: 2`。
- `& li > input[type=checkbox]`: `mr: 1`,禁用态不变灰(GFM 任务列表)。

### 6. 滚动联动(TurnTimeline)

- 现状:`streamSignal`(lastSeq 拼串)每事件触发 `scrollToBottom(auto)`。
- 改动:吐字期间内容高度逐帧变化,改用 ResizeObserver:观察 timeline 内容容器,`followingRef.current === true` 时每次尺寸变化 `scrollToBottom(auto)`。删除 `streamSignal` 订阅(其唯一用途就是滚动触发)。ResizeObserver 回调本身按帧聚合,与 rAF 吐字天然同步。
- 保留:会话切换滚底、`rows.length` 变化滚底、跟随阈值与回到底部按钮逻辑全部不动。

### 7. 复制整条回答(TurnItem)

- 回答容器(`aria-label="Amadeus 的回答"`)尾部渲染操作行:`<IconButton aria-label="复制全文">` hover 显现(桌面),触屏常显(`@media (hover: none)`)。
- 数据源:活跃 turn 用 store 的 text parts 拼接原文;终态用 `turn.answer`。
- 复制成功/失败提示:TurnItem 自持 Snackbar(与 MarkdownMessage 的代码复制 Snackbar 相互独立,实现简单;文案"回答已复制")。
- 仅在回答非空时显示;流式进行中隐藏(内容未定,复制无意义)。

## 数据流与状态(变更前后)

- store/reducer/manager/events:**零改动**。
- TurnItem:新增对活跃尾部 text part 的 useSmoothText 接管 + 光标 + 复制按钮;其余 parts 原样。
- 终态交接:`turn_terminal` → done=true → hook 瞬间补齐 → streamManager 移除 overlay → fallback `turn.answer`(streaming=false,无 remend)。观感:光标消失、文本无跳变(visible 已 == target == answer)。

## 兼容与回滚

- 所有新行为按文件粒度独立:高亮(MarkdownMessage + css)、吐字/光标(useSmoothText + TurnItem)、滚动(TurnTimeline)、复制(TurnItem)可单独 revert。
- `MemoizedBlock` 重构如出边界问题,退路是恢复单 ReactMarkdown 渲染(保留其余改进)。
- 新依赖均为纯函数库,无运行时全局副作用。

## 风险

| 风险 | 缓解 |
|---|---|
| marked 与 remark 分块边界不一致 | 只影响 memo 命中率;块渲染仍各自走 remark,正确性不受影响(research 已确认) |
| remend 修补与最终文本视觉跳变 | remend 只补闭合符,追平后文本即权威内容;终态不经 remend |
| rAF 循环泄漏 | hook 内 cleanup cancelAnimationFrame;done 后不再调度 |
| components 对象引用不稳定导致 memo 失效 | 模块级常量 + 空依赖 useCallback,实现清单里列为检查项 |
| e2e 断言"确定性回答"出现时机 | 吐字动画使文本延迟毫秒级(e2e 文本短);Playwright toBeVisible 自带等待,预期不受影响;若抖动,e2e server 文本极短可忽略 |
