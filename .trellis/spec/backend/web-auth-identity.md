# Web 鉴权与运行时身份契约

## 场景：GitHub 登录、双 Token 会话与 turn 身份贯穿

### 1. Scope / Trigger

- 触发：修改 GitHub OAuth、JWT、refresh token、Web owner scope、session/turn 归属、worker 装配或用户 workspace。
- 目标：浏览器不能通过提交或猜测数字 `user_id/session_id/turn_id` 获得权限；服务端验证出的身份必须一直贯穿到实际 Agent 运行时。
- Akashic 没有可迁移的 OAuth/JWT 合同；这是 Amadeus 的项目特定边界。

### 2. Signatures

- `GET /auth/github/login`、`GET /auth/github/callback`
- `POST /auth/refresh`、`POST /auth/logout`
- `AuthService.verify_access(token: str) -> CurrentUser`
- `AuthStore.get_or_create_identity(provider: str, subject: str) -> int`
- `AuthStore.rotate_refresh_token(token_hash, replacement_hash, expires_at) -> RefreshResult | None`
- `get_owner_scope(request: Request) -> OwnerScope`
- `build_passive_app(..., user_id: int | None = None) -> PassiveApp`
- `PassiveAppTurnRunner.run(turn, stream_sink) -> str`
- 数据表：
  - `user_identities(provider, provider_subject, user_id, created_at)`
  - `auth_refresh_tokens(id, user_id, token_hash, expires_at, revoked_at, replaced_by_id, created_at)`

### 3. Contracts

- GitHub 身份只使用稳定数字 `profile.id` 作为 `provider_subject`；用户名和邮箱不可作为权限主键。
- access token 是 15 分钟 HS256 JWT，强制验证固定 algorithm、`sub/iss/aud/iat/exp`；refresh token 是 7 天随机不透明字符串，数据库只保存 SHA-256 哈希。
- 两个 token 都通过 `HttpOnly; Secure; SameSite=Lax` Cookie 发送。access Cookie 路径为 `/`；refresh Cookie 路径必须为 `/auth`，否则 logout 收不到 refresh token。
- refresh 每次使用都在事务中锁定旧 row、写 replacement、撤销旧 row。旧 token 重放只撤销其 `replaced_by_id` 链，不影响同一用户的其他设备。
- 业务 API 不接受 `user_id`。`get_current_user()` 只从 access Cookie 验签得到内部 `users.id`，再创建 `OwnerScope`。
- 资源读取和变更使用 `(resource_id, authenticated_user_id)`；不存在与跨用户统一返回 404。`/api/health` 匿名可用；生产 OpenAPI/docs 关闭。
- worker 进程不得预构造固定 owner 的 `PassiveApp`。每次执行必须从已持久化 `turn.user_id` 调用 `build_passive_app(user_id=...)`，派生 `<workspace>/users/<user_id>`、Markdown memory user、PostgreSQL memory user 和文件工具 hook root；公网 turn 强制 `mcp_mode="disabled"`。
- 前端仅对 `GET/HEAD/OPTIONS` 的 401 自动 refresh 并重放一次；非幂等写请求不自动重放。SSE 关闭后 refresh 一次，再使用原 `lastSeq` 作为 `after_seq` 重连。
- 必需环境：`AMADEUS_PUBLIC_BASE_URL`（HTTPS）、`AMADEUS_GITHUB_CLIENT_ID`、`AMADEUS_GITHUB_CLIENT_SECRET`、至少 32 字符的 `AMADEUS_JWT_SECRET`。缺失、示例值或 HTTP URL必须启动失败。

### 4. Validation & Error Matrix

| 条件 | 公开行为 |
|---|---|
| access Cookie 缺失、篡改、过期、issuer/audience 不符 | 业务 API 401“需要登录” |
| GitHub callback 缺 state、state 不符、profile id 无效或 GitHub 非 2xx | 401“GitHub 登录失败”，不暴露第三方响应 |
| refresh 缺失、过期、已撤销或重放 | 401“登录已过期”并清理两个 Cookie |
| refresh 成功 | 原子 rotation，返回 204 并覆盖两个 Cookie |
| logout | 撤销当前 refresh row、返回 204、清理两个 Cookie |
| 猜测其他用户 session/turn id | 与不存在资源相同的 404 |
| `user_id <= 0` 或用户 workspace 不能保持在 base 下 | 拒绝构造运行时 |
| 公网用户 turn 配置了 `local_trusted` MCP | 用户运行时覆盖为 `disabled` |

### 5. Good / Base / Bad Cases

- Good：GitHub 用户 A 创建 session，JWT 的 `sub=A` 写入 turn；worker 读取 `turn.user_id=A`，memory 和文件路径均落在 `users/A`。
- Good：同一登录 refresh 后旧 token 被窃取并重放，只撤销该 rotation 链；另一设备的 refresh 仍有效。
- Base：access 过期时启动 GET 自动 refresh 一次并恢复；发送消息 POST 由用户显式重试，避免重复 turn。
- Bad：把 `session_id` 当身份凭证，或从 query/body 读取 `user_id`。
- Bad：worker 启动时先用 `AMADEUS_OWNER_USER_ID` 构造单例 memory，再在 turn 执行时临时改属性。
- Bad：refresh Cookie 使用 `/auth/refresh` 路径，导致 `/auth/logout` 无法收到并撤销 token。

### 6. Tests Required

- Auth/PostgreSQL：稳定 identity 映射、JWT 篡改、refresh hash-only storage、rotation、旧 token replay、独立设备不受影响。
- Web：匿名 API 401/health 200、OAuth redirect 含 state、Cookie flags、双用户资源 404、refresh/logout、生产 docs 404。
- Worker/runtime：连续两个不同 `turn.user_id` 分别调用用户运行时；断言 `SessionRef`、workspace、Markdown store user、MCP disabled 与关闭生命周期。
- 文件边界：另一个用户绝对路径、`..` 与 symlink escape 均由 resolve 后 containment 检查拒绝。
- 前端：landing、只重放安全读取、非幂等请求不重放、SSE refresh 后按 `lastSeq` 重连、refresh 失败进入登录过期、显式 logout。

### 7. Wrong vs Correct

#### Wrong

```python
app = build_passive_app()  # 使用固定 AMADEUS_OWNER_USER_ID
await app.runtime.run_turn(
    session=SessionRef(turn.user_id, turn.session_id),
    user_message=turn.content,
)
```

`SessionRef` 虽然是用户 A，`app.memory`、长期记忆 store 和 workspace 仍可能属于固定 owner。

#### Correct

```python
user_app = build_passive_app(
    workspace_root=workspace_root,
    env_path=env_path,
    user_id=turn.user_id,
)
await user_app.runtime.run_turn(
    session=SessionRef(turn.user_id, turn.session_id),
    user_message=turn.content,
)
```

#### Wrong

```ts
if (error.status === 401) {
  await refresh();
  return http.request(error.config); // POST 也可能被重复执行
}
```

#### Correct

```ts
if (error.status === 401 && ["GET", "HEAD", "OPTIONS"].includes(method) && !retried) {
  await refresh();
  return http.request({ ...config, _amadeusRetried: true });
}
```
