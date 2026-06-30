# Issue tracker：本地 Markdown

本仓库的 PRD 和 issue 使用本地 Markdown 文件管理，放在 `.scratch/` 下。

## 约定

- 一个功能一个目录：`.scratch/<feature-slug>/`
- PRD 文件固定为：`.scratch/<feature-slug>/PRD.md`
- 实现 issue 放在：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号
- triage 状态写在 issue 文件顶部附近的 `Status:` 行
- 评论和后续讨论追加到文件底部的 `## Comments` 区域

## 当 skill 说“publish to the issue tracker”

在 `.scratch/<feature-slug>/` 下创建新文件，必要时先创建目录。

## 当 skill 说“fetch the relevant ticket”

读取用户传入的本地 issue 或 PRD 路径。用户通常会直接给出路径或 issue 编号。
