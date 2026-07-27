# Research: 流式 Markdown 渲染与代码高亮方案调研

- **Query**: 流式 markdown 渲染业界做法、代码高亮方案对比、KaTeX 集成成本
- **Scope**: external(版本号于 2026-07-27 经 npm registry 实查;体积数据来自 bundlephobia API 同日实查,标注"估算"者除外)
- **Date**: 2026-07-27

## 一、流式 Markdown 渲染的主流做法

### 1. 按块(block)分段渲染 + memo(Vercel AI SDK cookbook 模式)

- 做法:用 `marked`(v18.0.7,12.5KB gz)的 lexer 把累计文本切成 block 列表(段落/代码块/表格…),每个 block 用一个 `memo` 的 `<ReactMarkdown>` 渲染。流式期间只有**最后一个 block** 的文本在变,前面的 block 引用不变 → 跳过重解析和 re-render。
- 来源:https://ai-sdk.dev/cookbook/next/markdown-chunking (MemoizedMarkdown 模式)
- 集成要点:Amadeus 已按 tool 事件把回复切成多个 text part(reducer.ts),此模式是在**单个 text part 内**再细分;`marked.lexer()` 只用来切块(取 `token.raw`),渲染仍走 react-markdown,行为不变。
- 成本:+1 依赖(marked),`MarkdownMessage.tsx` 内部改造,约 40 行。
- 风险:块边界在流式中会变(最后一个块可能从段落长成表格),需以 "除最后一块外全部 memo" 处理;marked 与 remark 对边界情况的分块偶有差异,但只影响 memo 粒度不影响正确性。

### 2. 节流合帧(throttle/rAF batch)

- 做法:把高频 delta 先积到 ref,再按 rAF 或固定间隔(30–80ms)批量 setState。AI SDK `useChat` 的 `experimental_throttle` 即此思路。
- 对 Amadeus:**当前不需要**。SSE 端点 250ms 轮询(amadeus/web/sse.py:16),事件频率 ≤4/s,已经天然节流;问题反而是粒度太粗。若未来后端改成真·逐 token 推送,此技术再启用。

### 3. 平滑字符显现(smooth streaming / typewriter drain)

业界两条路线:

- **客户端匀速吐字(推荐)**:store 保存"目标全文",UI 层用一个 hook(rAF 循环)以恒定速率(如每帧 2–6 字符,或按剩余 buffer 长度自适应加速)把"已显示长度"追向目标长度,显示 `target.slice(0, visible)`。追上后停;`turn_terminal` 时瞬间补齐。ChatGPT/Claude 网页端观感即来源于此类平滑。无需依赖,~60 行 hook(如 `useSmoothText(target, done)`)。
  - 参考实现思路:AI SDK `smoothStream()`(https://ai-sdk.dev/docs/reference/ai-sdk-core/smooth-stream ,服务端按词切 chunk)与社区客户端 typewriter hook;Amadeus 后端粒度粗,客户端侧实现收益最大。
- **逐词 fade-in 动画库**:`flowtoken@1.0.40`(npm: https://www.npmjs.com/package/flowtoken ,`AnimatedMarkdown` 组件,词级 fade/blur-in)。体积小但接管整个 markdown 渲染组件、样式体系与现有 MUI/Emotion 组件映射冲突,社区小、维护弱。**不推荐引入,只作交互参考**。
  - 折中:平滑吐字 hook + 对新增文本 span 加 CSS `animation: fadeIn 120ms`(motion 已在依赖里,但纯 CSS 即够;注意尊重 `prefers-reduced-motion`,项目已有先例 TurnItem.tsx:157)。

### 4. 不完整 markdown 自愈(streaming repair)

- **remend@1.3.0**(3.6KB gz,Vercel streamdown 仓库拆出的独立包,https://github.com/vercel/streamdown ):"Self-healing markdown",补全流式中途未闭合的 `**`/`` ` ``/链接/围栏代码块,避免半截语法闪烁。
- 集成要点:纯字符串函数,渲染前 `remend(content)` 即可,仅在流式进行中启用(终态用原文)。
- 风险:极低;是 streamdown v2 的官方内部依赖,活跃维护。

### 5. 一体化方案:streamdown(评估后不推荐)

- `streamdown@2.5.0`(react-markdown 的流式替代品,Vercel 出品):内置 remend、Shiki 高亮插件(@streamdown/code)、KaTeX(@streamdown/math)、Mermaid。
- **不适合 Amadeus 的原因**(npm 实查):核心即 141KB gz;样式基于 Tailwind utility class,要求宿主配置 Tailwind `@source "../node_modules/streamdown/dist/index.js"`(README 明示)—— 本项目无 Tailwind(MUI v9 + Emotion),引入等于装整套 Tailwind 或样式失效;依赖树含 mermaid(~2MB 级)。
- 价值:其源码是最佳实践参考(块级 memo + remend + 按需高亮),照抄思路、不装包。

## 二、代码高亮方案对比

| 方案 | 包/版本 | 集成方式 | 体积(gz) | React 19 | 流式表现 | 明暗主题 | 结论 |
|---|---|---|---|---|---|---|---|
| highlight.js | `rehype-highlight@7.0.2`(内含 lowlight@3.3.0 / highlight.js@11.11.1) | rehypePlugins 一行接入 react-markdown | 48.6KB(默认 common ~37 语言,bundlephobia 实查) | 是(纯 rehype 层,无 React 依赖) | **同步**、正则容错,半截代码不报错只是着色不准,每次重渲染即时可用 | 官方 CSS 主题成对(github.css / github-dark.css),用 `[data-mui-color-scheme="dark"]` 作用域各写一份,或自定义 CSS 变量主题 | **短期最优**:改动最小、体积可控、无异步复杂度 |
| Shiki | `shiki@4.3.1` + `@shikijs/rehype@4.3.1` 或 `react-shiki@0.11.0` | rehype 插件(异步,需 `react-markdown` 之外的处理)或独立组件替换 code 渲染 | 细粒度 bundle + JS engine + 预编译语法:每语言 10–200KB 不等,10 语言 + 双主题估算 200–400KB(**估算,采用前需实测**);web 全量 bundle >1MB | 是 | 高亮是**异步**的(highlighter 初始化 + 解析),流式高频重高亮需节流;`react-shiki` 内置 `delay` 节流选项,并对未知/半截代码回退纯文本 | 一流:原生双主题(`themes: {light, dark}` 输出 CSS 变量),与 MUI cssVariables 模式天然契合 | 质量上限最高,作为**二期升级项**;首选 `react-shiki`(专为流式场景做了节流) |
| Prism 系 | `rehype-prism-plus@2.0.2` / `react-syntax-highlighter@16.1.1` | rehype 插件 / 独立组件 | prism core 小,但 react-syntax-highlighter 依赖重 | react-syntax-highlighter 对 React 19 兼容但维护放缓;Prism v1 停滞(v2 未落地) | 同步,容错好 | CSS 主题成对 | 不选:生态停滞,相对 hljs 无增益 |

- 来源:https://github.com/rehypejs/rehype-highlight 、https://shiki.style 、https://shiki.style/packages/rehype 、https://github.com/AVGVSTVS96/react-shiki 、react-markdown README 高亮示例 https://github.com/remarkjs/react-markdown
- 共同集成要点(无论选哪个):都发生在 `frontend/src/chat/MarkdownMessage.tsx`;`MarkdownMessage` 已是 lazy chunk(TurnItem.tsx:15-19),高亮库体积不会进首屏 bundle,只影响首条回复的 chunk 加载。
- rehype-highlight 细节:默认只注册 common 语言集;`detect: false`(默认)时无 `language-x` class 的块不高亮,建议保持以省 CPU;可 `languages` 精简注册进一步减体积。
- 深色主题落地:项目用 MUI v9 `cssVariables + colorSchemes`(frontend/src/app/theme.ts:4-17),暗色选择器是 `[data-mui-color-scheme="dark"]`,两份 hljs 主题 CSS 按此作用域即可,无闪烁。

## 三、可选增强:KaTeX 数学公式

- 包:`remark-math@6.0.0` + `rehype-katex@7.0.1` + `katex@0.18.1`。
- 体积(bundlephobia 实查):katex JS 76.9KB gz;另需 `katex/dist/katex.min.css`(~23KB gz)+ 字体(woff2 若干,按需加载,单个 ~10–25KB)。合计首条含公式回复约 +100KB gz。
- 集成要点:`remarkPlugins={[remarkGfm, remarkMath]}` + `rehypePlugins={[rehypeKatex]}`,import CSS;`rehype-katex` 默认 `throwOnError: false`,渲染失败显示红色原文,不炸组件 —— 流式半截公式($ 未闭合)会闪原文,配合 remend/终态重渲染可接受。
- 风险:`$...$` 单美元符会误伤普通货币文本(remark-math 默认开启 single dollar,可 `singleDollarTextMath: false` 只认 `$$`,按产品取向定);CSS/字体需进 lazy chunk 避免拖首屏。
- 来源:https://katex.org 、https://github.com/remarkjs/remark-math
- 建议:后端 prompt 是否会产出 LaTeX 决定优先级;若模型常吐 `\[...\]` 需另加 delimiters 归一化(小函数即可)。

## Caveats / Not Found

- react-shiki / flowtoken 的 bundlephobia 查询被限流(429),体积为估算,采用前需 `vite build` 实测 chunk 大小。
- streamdown v2 的 Shiki 高亮已拆到可选插件 `@streamdown/code`(README 实查),核心包 141KB gz 不含高亮。
- 未调研 Mermaid 图表渲染(依赖巨大,当前产品无此需求信号)。
