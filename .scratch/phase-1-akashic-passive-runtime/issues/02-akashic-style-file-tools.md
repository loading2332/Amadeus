Status: ready-for-agent
Label: ready-for-agent

# 迁移 Akashic-style 文件工具：list/read/write/edit

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

实现 Phase 1 文件工具集：`list_dir`、`read_file`、`write_file`、`edit_file`。这些工具应参考 Akashic 的文件工具契约，而不是只做最薄包装：工具自身支持 `allowed_dir` 路径边界，读取支持分页或截断，写入支持创建父目录和完整覆盖语义，编辑要求 exact old-text matching，并在成功时返回可审计 diff。

工具层需要提供基础路径安全兜底，但全局读写策略留给后续 runtime hook policy slice 统一控制。

## Acceptance criteria

- [ ] `list_dir` 能列出允许目录内的文件和目录，并拒绝非目录目标。
- [ ] `read_file` 能读取允许目录内文本文件，支持 offset/limit 或等价分页能力，并对大文件做截断提示。
- [ ] `write_file` 能在允许目录内创建父目录并完整覆盖写入文本内容。
- [ ] `edit_file` 要求 `old_text` 精确匹配；未找到、匹配多处且未明确 replace_all 时返回可解释错误。
- [ ] `edit_file` 成功后返回 diff summary，便于 tool trace 审计。
- [ ] 写入和编辑操作使用文件级 mutation lock 或等价机制，避免并发修改同一文件互相覆盖。
- [ ] 每个文件工具都支持 `allowed_dir`，相对路径基于该目录解析，路径逃逸会被拒绝。
- [ ] 单元测试覆盖成功路径、路径逃逸、缺失文件、目录/文件类型错误、大文件读取、编辑歧义和 diff 输出。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/01-extract-reasoner-ordinary-chat.md`
