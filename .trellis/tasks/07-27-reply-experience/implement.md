# 实施计划 — 改进前端回复效果

依赖顺序:批次 1(高亮+排版+自愈,零耦合)→ 批次 2(分块 memo)→ 批次 3(吐字+光标+滚动)→ 批次 4(复制+收尾)。每批次结束跑一次验证命令,全绿再进下一批。

## 批次 1:高亮 + 排版 + 自愈(S)

- [x] `pnpm add rehype-highlight remend`(frontend/)
- [x] 新增 `frontend/src/chat/highlight.css`:github 亮色 + `[data-amadeus-color-scheme="dark"]` 作用域的暗色 token 规则;删除 `.hljs` 背景规则
- [x] `MarkdownMessage.tsx`:接入 `rehypePlugins={[[rehypeHighlight, {detect: false}]]}`;import highlight.css;code 组件提取语言标签显示在代码块右上角
- [x] `MarkdownMessage.tsx`:新增 `streaming` prop,streaming 时 `remend(content)` 预处理;`TurnItem.tsx` 对活跃 turn 传 `streaming`
- [x] `MarkdownMessage.tsx`:容器 sx 拆为模块级 `markdownSx` 并补排版规则(h1–h6/img/table/th/hr/任务列表,按 design.md §5)
- [x] 单测:高亮(渲染 ```js 块断言 `<span class="hljs-keyword">`)、语言标签、streaming 自愈(未闭合 ** 不渲染成 strong 残缺形态)
- [x] 验证:`pnpm typecheck && pnpm lint && pnpm test -- --run`

## 批次 2:分块渲染 + memo(M)

- [x] `pnpm add marked`
- [x] `MarkdownMessage.tsx` 重构为 MemoizedBlock 模式(design.md §3):marked.lexer 切块、索引 key、components/urlTransform/sx 提为模块级常量、onCopyCode 经空依赖 useCallback
- [x] 检查项:components 对象与所有传给 MemoizedBlock 的 props 引用稳定(以渲染计数单测替代 Profiler 手测:流式期间历史块 0 次 re-render)
- [x] 单测:多块内容仅尾块变化时,前块组件不重渲染(用渲染计数 spy)
- [x] 验证:`pnpm typecheck && pnpm lint && pnpm test -- --run`

## 批次 3:平滑吐字 + 光标 + 滚动联动(M)

- [x] 新增 `frontend/src/streaming/useSmoothText.ts`(design.md §1:rAF 自适应步进、done/reduced-motion 直达、cleanup)
- [x] `TurnItem.tsx`:活跃 turn 的最后一个 text part 经 useSmoothText;其后渲染闪烁光标 span(design.md §2);终态/失败/取消不显示光标
- [x] `TurnTimeline.tsx`:`streamSignal` 滚动触发改为 ResizeObserver 跟随(design.md §6);删除 streamSignal 订阅;保留其余滚动行为
- [x] 单测:useSmoothText(fake rAF:推进、done 补齐、reduced-motion 直达、卸载清理);TurnItem 光标出现/消失
- [ ] 手测:长回复流式观感连续、脱离底部后不被拉回、回到底部按钮正常(待人工确认)
- [x] 验证:`pnpm typecheck && pnpm lint && pnpm test -- --run && pnpm test:e2e`

## 批次 4:复制全文 + 收尾(S)

- [x] `TurnItem.tsx`:回答尾部 hover 显现"复制全文"按钮(design.md §7),终态可用、流式隐藏;Snackbar 提示
- [x] 单测:复制按钮可见性(终态显示/流式隐藏)、点击后 clipboard 内容
- [x] `pnpm build`:确认 marked/rehype-highlight/remend 落在 MarkdownMessage lazy chunk;记录 chunk 体积对比(首屏 index +2.4KB raw/+0.7KB gzip;MarkdownMessage lazy chunk 155.9→377.1KB raw / 46.8→115.8KB gzip)
- [x] 全量验证:`pnpm typecheck && pnpm lint && pnpm test -- --run && pnpm test:e2e`
- [x] 对照 prd.md Acceptance Criteria 逐条勾验(自动化可验项全过;"长回复手测卡顿"与"流式观感"待人工确认)

## 回滚点

- 每批次为独立提交粒度;批次 2 出问题可单独回退到单 ReactMarkdown(批次 1 成果保留)。

## Review gates

- 批次 2 完成后:确认 memo 命中(Profiler 截图或渲染计数测试)再进批次 3——这是吐字性能的前提。
- 批次 3 完成后:e2e 全量跑通才允许进批次 4。
