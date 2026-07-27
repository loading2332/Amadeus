# GitHub 登录与端到端用户运行时隔离设计

## 身份原则

`user_id` 是服务端验证 GitHub OAuth 与 Amadeus JWT 后获得的内部主键。它不是浏览器传入的权限参数，而是身份链在数据库、队列和运行时之间的稳定连接键。当前固定 `AMADEUS_OWNER_USER_ID` 只适合单用户 CLI 兼容；生产 Web worker 必须从 `turn.user_id` 创建用户上下文。

Akashic 中没有可迁移 OAuth/JWT 会话机制，因此本设计是 Amadeus 的项目特定边界扩展。

## 数据模型与会话

新增 `user_identities(provider, provider_subject, user_id, created_at)`，以 `(provider, provider_subject)` 唯一映射 GitHub 稳定 id；新增 `auth_refresh_tokens(id, token_hash, user_id, expires_at, revoked_at, replaced_by_id, created_at)`，只保存 refresh token 哈希与 rotation 链。新本地 `users.id` 由数据库分配，不迁移旧固定 owner 数据。

```text
GitHub OAuth callback
→ identity upsert → users.id
→ access JWT(sub=users.id, 15 min) + opaque refresh token(7 d)
→ HttpOnly/Secure/SameSite=Lax Cookie
→ Web dependency validates access JWT → current user_id
→ session/turn row persists user_id
→ worker reads turn.user_id → UserRuntimeContext(user_id)
```

refresh token 每次使用都在同一事务中废弃旧记录、写入替代记录并发新 token。已废弃 token 被重用时撤销该登录会话。access JWT 强制校验固定 algorithm、issuer、audience、subject 与时间声明。

## Web 授权

新增 auth config、OAuth client、token service、auth store 与 `get_current_user()`。`get_owner_scope()` 仅接受已验证 current user，继续复用既有 `OwnerScope.require_session/require_turn` 的 `(resource_id, user_id)` 检查；跨用户统一 404。

`/api/health` 匿名。根路径未登录时 React 显示 landing；`/auth/github/login`、callback、refresh、logout 建立会话。`/api/bootstrap.owner_user_id` 继续返回内部当前用户 ID，语义不再是配置 owner。生产关闭或等价保护 schema/docs。

## 用户运行时上下文

worker 进程启动时只加载不带用户状态的 `RuntimeConfig`，不构造固定 owner `PassiveApp`。`PassiveAppTurnRunner` 每个 turn 都以 `turn.user_id` 构造并在 finally 中关闭一个用户 `PassiveApp`：

```text
worker process
  RuntimeConfig（无用户 memory/workspace 实例）

PassiveApp(user_id)
  session manager/session context scoped by SessionRef(user_id, session_id)
  PostgresMemoryStore(user_id)
  LongTermMemoryEngine(store=user store)
  MarkdownMemoryRuntime(root=user workspace, user_id=user_id)
  tool executor whose filesystem root is user workspace
```

`PassiveAppTurnRunner.run(turn)` 以 `turn.user_id` 调用 `build_passive_app(user_id=...)`，再把同一 user id 写入 `SessionRef`。不得通过“临时改写共享 `runtime.memory_engine`”完成，因为 worker 可并发或未来并发处理 turn，会造成竞态和串用户。

当前实现优先采用每 turn 独立生命周期，避免任何跨用户实例残留；代价是 provider/连接池会重复初始化。若后续做性能优化，共享服务只可包含不携带用户数据的 provider、连接池、静态工具定义与配置；用户 scope 的 store/engine cache key 必须包含 user id，并有明确关闭/失效生命周期。

## Workspace 与工具边界

运行时根目录设为 `AMADEUS_USER_WORKSPACE_ROOT/<user_id>/`（容器内默认可为 `/workspace/users/<user_id>`）。路径由 `int(user_id)` 转字符串后拼接、`resolve()` 并断言仍在用户 workspace base 下生成；不接受客户端、模型或 tool argument 指定根目录。

该用户根目录承载 Markdown memory 文件和文件工具的工作目录。文件工具必须在执行前对目标 `resolve()`，确认位于本 user root；拒绝绝对路径、`..` 穿越与符号链接逃逸。Postgres memory 自身继续将每次读写绑定 `user_id`。

公网 worker 中关闭 `local_trusted` MCP 与 MCP add/remove 工具。任意 MCP sandbox 为后续任务，不与本切片混合。

## 前端与 SSE

未登录 bootstrap 的 401 进入 landing，不显示连接故障。Axios 对可安全重放的普通读取请求最多 refresh 一次；不自动重放 create-turn 等非幂等写操作。EventSource 连接前确保 access token 有效；鉴权失败时先刷新、再以原 `after_seq` 重连，刷新失败进入未登录态。登出清空 Query、live overlay、session URL 与 owner identity。

## 兼容、部署与回滚

保留 `AMADEUS_OWNER_USER_ID` 仅服务 CLI/旧单用户路径；Web worker 改用 turn identity。环境新增 GitHub client/secret、public URL、JWT secret/issuer/audience 与 user-workspace base。回滚只需停用新镜像；migration 是新增表，既有 conversation 数据不被修改。

## 验证

- Auth unit/integration：OAuth state、identity upsert、JWT validation、refresh rotation/reuse、cookie flags。
- Web integration：匿名拒绝、双用户 session/turn/SSE 404 矩阵。
- Worker/memory integration：同 worker 连续处理两个 user 的 deterministic turn，断言检索、写入和 Markdown 文件均落在各自 user scope。
- Tool tests：绝对路径、`..`、symlink 逃逸与跨用户路径均拒绝。
- 前端：401 landing、refresh/retry、logout、SSE recover；再运行完整 Web/worker/memory 集合及构建质量门。
