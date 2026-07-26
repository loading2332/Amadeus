# 会话删除 — 执行计划

## 顺序清单

### 1. 后端 Store

- [ ] `amadeus/session/postgres.py`:`PostgresSessionStore.delete_session(*, user_id, session_id) -> bool`(单条 DELETE,返回 rowcount > 0)
- [ ] `amadeus/session/store.py`:`InMemorySessionStore.delete_session` 同名对齐(pop `_sessions` / `_messages`)
- [ ] 不改 `SessionStoreProtocol`(见 design.md 边界决策)

### 2. 后端路由

- [ ] `amadeus/web/routes.py`:`DELETE /sessions/{session_id}`,204 / 404(`OwnerResourceNotFound`)
- [ ] 后端测试:`tests/web/test_postgres_web_app.py` 增加删除成功(204 + 列表不再含该会话 + messages/turns 级联消失)、删除不存在会话(404)、删除他人会话(404)用例

### 3. 前端 API 层

- [ ] `frontend/src/api/client.ts`:`deleteSession(sessionId, signal?)`
- [ ] `frontend/src/api/queries.ts`:`useDeleteSessionMutation`(onSuccess 过滤 sessions 缓存 + removeQueries messages/turns)
- [ ] 对应单测:`client.test.ts` / 相关 queries 测试

### 4. 前端 UI

- [ ] `frontend/src/sessions/SessionSidebar.tsx`:行内 hover 删除按钮 + 确认 Dialog(loading / 错误重试态)
- [ ] `frontend/src/app/App.tsx`:接入 `onDelete` 回调与 mutation
- [ ] `SessionSidebar.test.tsx`:删除按钮渲染、确认流、取消流、失败提示
- [ ] 验证删除选中会话后的回落行为(依赖现有 `effectiveSelectedId`,补断言)

### 5. 收尾

- [ ] e2e(`frontend/e2e/chat.spec.ts`)按需补删除路径(若现有 e2e 基建可覆盖)
- [ ] 全量校验通过后进入 Phase 3(spec 更新 + 提交)

## 验证命令

```bash
# 后端
python -m pytest tests/web/ -x -q

# 前端(在 frontend/ 下)
pnpm typecheck && pnpm lint && pnpm test -- --run
```

## Review Gate / 回滚点

- 步骤 1-2(后端)完成后可独立验证(pytest),再进入前端;若前端方案有变,后端接口不受影响
- 每步为独立可回滚单元;整任务为纯新增,revert 提交即回滚
