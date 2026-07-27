# Research: 改进建议清单(按收益/成本排序)

- **Query**: 回复效果改进候选项,标注复杂度与任务归属
- **Scope**: mixed(基于 current-reply-pipeline.md 与 streaming-render-options.md)
- **Date**: 2026-07-27

## 建议本任务做(高收益、纯前端、互相成就)

| # | 改进项 | 改什么 / 动哪些文件 | 复杂度 |
|---|---|---|---|
| 1 | **代码块语法高亮**:接入 `rehype-highlight@7.0.2`,补语言标签显示,双份 hljs 主题 CSS 按 `[data-mui-color-scheme="dark"]` 作用域 | `frontend/src/chat/MarkdownMessage.tsx`(rehypePlugins + code 组件读 `language-x`)、新增主题 CSS(或 `frontend/src/app/theme.ts` 内联)、`frontend/package.json` | S |
| 2 | **平滑字符显现 + 流式光标**:新建 `useSmoothText` hook(rAF 匀速追进 + buffer 自适应加速,`turn_terminal` 补齐,尊重 `prefers-reduced-motion`),文本末尾加闪烁光标,`finalizing` 期间保留光标 | 新增 `frontend/src/streaming/useSmoothText.ts`、`frontend/src/chat/TurnItem.tsx`(仅对活跃 turn 的最后一个 text part 启用) | M |
| 3 | **按块分段渲染 + memo**:用 `marked@18` lexer 切 block,除最后一块外全部 memo,消除长回复每事件全量重解析 | `frontend/src/chat/MarkdownMessage.tsx` 内部重构(MemoizedBlock 模式)、`frontend/package.json` | M |
| 4 | **不完整 markdown 自愈**:流式进行中用 `remend@1.3.0` 预处理文本,消除未闭合 `**`/``` 的闪烁;终态渲染原文 | `frontend/src/chat/MarkdownMessage.tsx`(或在 TurnItem 传 `streaming` prop)、`frontend/package.json` | S |
| 5 | **markdown 排版补全**:h1–h6 对齐 MUI 主题字阶、`img { maxWidth: 100% }`、去掉表格 `minWidth: 480` 改为内容自适应 + 表头底色、`hr`/任务列表样式;顺手把单行巨型 sx 拆成常量 | `frontend/src/chat/MarkdownMessage.tsx:25` | S |
| 6 | **滚动跟随与平滑联动**:吐字改为 rAF 后,把 `streamSignal` 触发的跳跃式 scrollToBottom 改为在吐字循环内跟随(或保留现逻辑仅调 behavior),消除 250ms 顿挫 | `frontend/src/chat/TurnTimeline.tsx:45-55`(与 #2 同批实现) | S |
| 7 | **整条消息复制按钮**:回答底部 hover 显示"复制全文"(复用现有 Snackbar 逻辑) | `frontend/src/chat/TurnItem.tsx`、`frontend/src/chat/MarkdownMessage.tsx` | S |

推荐实施顺序:1 → 5 → 4 → 2 → 6 → 3 → 7(1/5/4 立竿见影且零耦合;2/6 一组;3 在 2 之后做可直接按"已显示文本"分块)。
注意:#2 与 #3 有交互 —— 平滑吐字会让 content 每帧变化,必须配合 #3 的块级 memo 或限制重渲染范围,否则放大重解析成本;design.md 里应把两者当一个整体设计。

## 建议另开任务

| # | 改进项 | 原因 / 动哪些文件 | 复杂度 |
|---|---|---|---|
| 8 | **KaTeX 数学公式**(`remark-math@6` + `rehype-katex@7` + `katex@0.18.1`) | +~100KB gz(JS+CSS+字体),需先确认模型输出是否常含 LaTeX、`$` 定界策略、`\[...\]` 归一化;`MarkdownMessage.tsx` + lazy CSS | M |
| 9 | **高亮升级 Shiki**(`react-shiki@0.11.0` 或 `@shikijs/rehype@4.3.1`,原生双主题) | 异步高亮 + 体积需实测(估 200–400KB gz),等 #1 上线后按代码块使用频率决定是否值得;`MarkdownMessage.tsx` | M/L |
| 10 | **工具轨迹持久化**:turn 完成后仍能看到调用过的工具 | 需要后端契约改动(`Turn` 增加 tool activities 或 messages 接口透出),跨 `amadeus/turns/*`、`amadeus/web/*`、`frontend/src/api/contracts.ts`、`TurnItem.tsx` | L |
| 11 | **reducer 非前缀快照丢 tool parts 修复**(`frontend/src/streaming/reducer.ts:74-81`) | 正确性小修,与"回复效果"主题无关,适合捎带进任意维护任务;需补测试 | S |
| 12 | **真·逐 token 推送**(后端 flush/poll 粒度细化或改推送通道) | #2 的客户端平滑已能掩盖当前粒度,收益存疑;动 `amadeus/worker/turn_worker.py`、`amadeus/web/sse.py`,涉及 DB 写放大权衡 | L |

## 明确不做

- **streamdown 整包接入**:要求 Tailwind、核心 141KB gz、捆绑 mermaid 生态,与 MUI/Emotion 技术栈冲突(详见 streaming-render-options.md);只借鉴其实现思路与 remend 子包。
- **flowtoken 等词级动画库**:接管渲染层、维护弱;用 #2 自研 hook + CSS fade 达成同等观感。

## Caveats

- #3 的 marked 分块与 remark 解析对少数边界(松散列表、HTML 块)的切分不一致,只影响 memo 命中率不影响渲染正确性,design 阶段无需过度设计。
- 所有体积数字见 streaming-render-options.md 的实查/估算标注;进 design.md 前建议对最终选型跑一次 `vite build` 验证 chunk 尺寸。
