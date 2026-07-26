# 会话删除功能

## Goal

用户可以在会话侧栏删除不再需要的会话。当前新增会话后无法删除,列表只增不减。

## Requirements

- 后端提供 `DELETE /api/sessions/{session_id}` 接口,仅允许删除 owner 自己的会话
- 删除会话时级联清理其关联数据(messages / turns,依赖已有 DB `ON DELETE CASCADE`)
- 前端会话列表每行提供删除入口(hover 显示删除按钮)
- 删除前需要用户确认(确认对话框),避免误触
- 删除成功后会话立即从列表消失;若删除的是当前选中会话,自动切换到列表中的其他会话(或空态)
- 删除失败(网络/服务端错误)时有用户可见的错误提示,且列表状态不被破坏

## Non-Goals

- 软删除 / 回收站 / 恢复功能(硬删,数据不可恢复)
- 批量删除
- 删除时对运行中 turn 的特殊拦截(运行中 turn 随会话级联删除,worker 侧更新变为 no-op,可接受)

## Acceptance Criteria

- [ ] `DELETE /api/sessions/{id}` 删除成功返回 204;会话不存在或非本 owner 返回 404
- [ ] 删除后该会话的 messages / turns 在 DB 中不再存在(级联生效)
- [ ] 侧栏会话行 hover 出现删除按钮,点击弹出确认对话框,确认后执行删除
- [ ] 删除当前选中会话后,界面自动落到剩余会话中的第一个;删除最后一个会话后进入无会话空态,不白屏
- [ ] 删除失败时展示错误提示,会话仍留在列表中
- [ ] 前端(SessionSidebar / queries / client)与后端(route + store)均有对应测试,现有测试不回归

## Notes

- DB 外键已具备级联:`conversation_messages`、`conversation_turns`、`memory_markdown_state` 均对 `conversation_sessions.id` 定义了 `ON DELETE CASCADE`,无需新迁移
- `App.tsx` 的 `effectiveSelectedId` 已实现"选中 id 不在列表则回落第一个",删除后的选中态切换可复用该逻辑
