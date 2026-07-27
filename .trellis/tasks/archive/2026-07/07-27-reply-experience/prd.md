# 改进前端回复效果

## Goal

提升 Amadeus 聊天界面中 AI 回答的呈现质量:代码块有语法高亮、流式文本平滑显现且有生成中光标、长回复渲染不随内容增长变卡、流式中途的 markdown 不闪烁异常形态、排版细节与主题一致、支持一键复制整条回答。

## Scope

纯前端改动(frontend/),不动后端契约与推送粒度。对应 research/improvement-candidates.md 的 #1–#7。

## Requirements

1. **代码块语法高亮**:带 `language-x` 标注的围栏代码块按语言着色,显示语言标签;明暗主题下均有匹配配色,主题切换无闪烁。无语言标注的块不做自动检测(省 CPU)。
2. **平滑字符显现 + 流式光标**:流式期间文本以匀速逐字符追进方式显现(buffer 越大追进越快),不再按 ~250ms 一大块跳变;正文末尾显示闪烁光标,直到 turn 终态;`turn_terminal` 时立即补齐全部剩余文本。尊重 `prefers-reduced-motion`(减弱动效时直接整块显示、无光标闪烁动画)。
3. **分块渲染性能**:流式期间仅重解析/重渲染正在变化的尾部 block,已完成的 block 不随新事件重渲染;长回复(>10k 字符)流式期间无可感知卡顿。
4. **流式 markdown 自愈**:流式进行中,未闭合的 `**`、`` ` ``、链接、``` 围栏不产生"半截语法闪烁";终态渲染权威原文。
5. **排版补全**:h1–h6 字阶/边距对齐 MUI 主题;`img` 不撑破容器;表格去掉固定 `minWidth`,表头有底色;`hr`、任务列表样式适配;明暗两套下均正常。
6. **滚动跟随联动**:自动跟随滚动与平滑吐字同步,不再呈现 250ms 一顿的跳跃;"脱离底部/回到底部"现有行为不回退。
7. **整条消息复制**:每条回答提供"复制全文"入口(hover 显示),复制原始 markdown 文本,复用现有 Snackbar 提示。

## Constraints

- 不引入 Tailwind 及任何接管渲染层的动画库(flowtoken/streamdown 整包明确排除)。
- 新依赖限定:`rehype-highlight@7`、`remend@1`、`marked@18`(均已调研,见 research/streaming-render-options.md);高亮相关体积必须落在 MarkdownMessage 的 lazy chunk,不进首屏。
- 不破坏现有优点:`contentVisibility` 跳过渲染、`TurnItem`/`MarkdownMessage` memo、reducer 幂等、URL 白名单、自动跟随滚动阈值逻辑(见 research/current-reply-pipeline.md "已有的优点")。
- 现有单测与 e2e 全部保持通过;新行为补测试。

## Acceptance Criteria

- [ ] 含 ```python 等标注的代码块流式与终态下均正确高亮,显示语言标签,明暗主题均正常
- [ ] 流式回答肉眼观感为连续吐字,末尾有光标;终态光标消失、文本与权威 answer 一致
- [ ] 开启系统"减弱动态效果"后,不做吐字动画,直接分块显示
- [ ] 长回复流式期间输入框打字、滚动均不卡顿(手测);React DevTools 确认历史 block 不随新事件重渲染
- [ ] 流式中途输出未闭合 ``` 时,后续文本不会整体变成代码块样式
- [ ] 大图不溢出气泡;小表格不出现无意义横向滚动条
- [ ] 回答 hover 出现复制按钮,点击后剪贴板为完整 markdown 原文,Snackbar 提示
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm test:e2e` 全绿
- [ ] `pnpm build` 通过,首屏 chunk 体积无明显增长(高亮/marked 均在 lazy chunk)

## Notes

- 调研依据:research/current-reply-pipeline.md(现状与短板)、research/streaming-render-options.md(选型)、research/improvement-candidates.md(排序)。
- KaTeX、Shiki 升级、工具轨迹持久化、逐 token 推送均已明确移出本任务(另开)。
