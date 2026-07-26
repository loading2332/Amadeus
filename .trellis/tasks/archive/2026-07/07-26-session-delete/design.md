# 会话删除 — 技术设计

## 边界与分层

删除是 Web 产品面操作,不属于 Reasoner 侧会话读写契约,因此:

- `delete_session` 只加在 `PostgresSessionStore`(及 `InMemorySessionStore` 保持双实现对齐,便于测试),**不加入** `SessionStoreProtocol`(该 Protocol 是 reasoner/tools 消费的最小契约,见 `amadeus/tools/defaults.py`)
- Web 路由经 `OwnerScope` 强制 owner 归属校验,与现有 `require_session` 模式一致

## 后端

### Store 层 (`amadeus/session/postgres.py`)

```python
def delete_session(self, *, user_id: int, session_id: int) -> bool:
    # DELETE FROM conversation_sessions WHERE id=%s AND user_id=%s
    # 返回 rowcount > 0;级联由 DB 外键完成,无需手动清理
```

`InMemorySessionStore` 同名方法:从 `_sessions` / `_messages` pop 对应 identity。

### 路由层 (`amadeus/web/routes.py`)

```python
@api_router.delete("/sessions/{session_id}", status_code=204)
async def delete_session(session_id, scope) -> Response:
    deleted = await asyncio.to_thread(
        scope.session_store.delete_session,
        user_id=scope.user_id, session_id=session_id,
    )
    if not deleted:
        raise OwnerResourceNotFound()
    return Response(status_code=204)
```

- 不先走 `require_session` 再删(两次往返 + TOCTOU);直接按 `(id, user_id)` 条件删除,rowcount=0 即 404
- `OwnerResourceNotFound` 沿用应用现有异常映射(→ 404)
- 同现有约定:同步 psycopg 调用统一 `asyncio.to_thread` 下沉线程池

### 级联与并发边界

- `conversation_messages` / `conversation_turns` / `memory_markdown_state` 的 FK 均为 `ON DELETE CASCADE`(见 `migrations/versions/20260704_0001`),删除一条 session 行即完成清理
- `memory_items` 按 user 归属、无 session FK,不受影响(记忆保留是预期行为)
- 会话内有运行中 turn 时删除:turn 行被级联删除,worker 后续 `UPDATE ... WHERE id=...` 影响 0 行成为 no-op;SSE 流断开由前端现有错误处理兜底。不做拦截(Non-Goal)

## 前端

### API 层

- `client.ts`:`deleteSession(sessionId, signal?)` → `DELETE /sessions/{id}`,无返回体
- `queries.ts`:`useDeleteSessionMutation`
  - `onSuccess`:从 `queryKeys.sessions` 缓存中过滤掉该会话;`removeQueries` 清理该会话的 `messages` / `turns` 缓存
  - 失败不改缓存,由 UI 层提示

### UI 层 (`SessionSidebar.tsx` + `App.tsx`)

- 会话行内加 `DeleteOutlineRounded` IconButton:默认 `opacity: 0`,行 hover / 行内 focus-visible 时显示(触屏端 MUI hover 语义下点按仍可触达;保留 aria-label 保证可访问性)
- 点击删除按钮 `stopPropagation`(不触发行选中),打开 MUI `Dialog` 确认框:标题"删除会话?",正文提示不可恢复,操作为 取消 / 删除(error 色)
- Dialog 状态(待删除 session)提升到 `SessionSidebar` 内部管理;`App.tsx` 传入 `onDelete(sessionId)` 回调接 mutation
- 删除进行中:确认按钮 loading + 禁用
- 删除失败:Dialog 内展示错误文案(复用 `ApiError.message`),保持 Dialog 打开可重试或取消
- 选中态切换:复用 `App.tsx` 现有 `effectiveSelectedId` 回落逻辑,无需新增代码;URL `?session=` 参数由现有 effect 同步

## 兼容与回滚

- 纯新增接口与 UI 入口,无 schema 变更、无现有接口行为变化;回滚即 revert 提交
- 风险点:硬删不可恢复 —— 由确认对话框把关,PRD 已明确 Non-Goal 不做回收站
