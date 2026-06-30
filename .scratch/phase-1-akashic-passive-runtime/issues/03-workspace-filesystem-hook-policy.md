Status: ready-for-agent
Label: ready-for-agent

# 实现 workspace filesystem hook policy

## Parent

`.scratch/phase-1-akashic-passive-runtime/PRD.md`

## What to build

把文件访问策略放到 runtime tool hook 边界中统一执行。默认策略是：`list_dir` 和 `read_file` 可以访问 Amadeus workspace 内路径；`write_file` 和 `edit_file` 只能写入或修改 `runtime-artifacts/` 下的路径。工具自身的 `allowed_dir` 作为局部安全兜底，hook 作为全局 runtime policy 和 trace 边界。

当模型尝试越界读写、写源码、使用危险路径或违反写入策略时，hook 应返回结构化 denial，让 tool trace 记录 `denied` 状态和原因，而不是让异常静默丢失。

## Acceptance criteria

- [ ] runtime hook 能规范化相对路径和绝对路径，并把相对路径解析到 workspace 策略范围内。
- [ ] `list_dir` 和 `read_file` 在 workspace 内允许执行，workspace 外路径被拒绝。
- [ ] `write_file` 和 `edit_file` 默认只允许 `runtime-artifacts/` 下路径。
- [ ] 写源码目录、父目录逃逸、绝对路径逃逸都被 hook 拒绝。
- [ ] denial 结果进入 tool execution trace，包含工具名、原始参数、最终状态和拒绝原因。
- [ ] hook 与工具自身 `allowed_dir` 形成双层防御；绕过 hook 时工具仍不能越过自己的 allowed_dir。
- [ ] 测试覆盖允许读、拒绝读、允许写 artifact、拒绝写源码、拒绝 `../` 逃逸、拒绝 workspace 外绝对路径。

## Blocked by

- `.scratch/phase-1-akashic-passive-runtime/issues/02-akashic-style-file-tools.md`
