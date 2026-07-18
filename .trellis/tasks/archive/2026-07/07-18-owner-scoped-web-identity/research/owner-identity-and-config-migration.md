# Owner identity 与配置迁移研究

## 研究问题

为单用户 React 产品建立服务器拥有的 owner identity 时，需要确认：

1. 当前 `user_id` 在配置、Web、turn、session、memory 和浏览器之间如何流动；
2. 客户端可控 `user_id` 是否只是界面问题，还是实际信任边界缺陷；
3. `AMADEUS_MEMORY_USER_ID` 应直接重命名、临时兼容，还是保留为独立配置；
4. Akashic 是否有可直接迁移的 owner identity 机制。

## 已确认事实

### 1. 当前配置只表达 memory 默认用户

- `RuntimeConfig` 只有 `default_memory_user_id`（`amadeus/app/bootstrap.py:72-78`）。
- 配置来源只有 `AMADEUS_MEMORY_USER_ID`（`amadeus/app/bootstrap.py:292-293`）。
- 该值同时被用于 PostgreSQL memory runtime 与 memory service 组装（`amadeus/app/bootstrap.py:405,450`），但 Web app 没有注入或持有 owner identity。
- 受版本控制的配置面只有 `.env.example:9`、`docker-compose.yml:39,62` 和 `docs/postgres-runtime.md:59`。
- 当前本地 `.env` 存在，但没有显式设置旧变量或新 owner 变量；因此本工作区不会因重命名丢失一个非默认 user ID。研究过程中只检查了变量是否存在，没有读取或记录任何配置值。
- Git 历史显示旧变量在 2026-07-04 至 2026-07-05 的 PostgreSQL/runtime 重构中引入，尚不是长期稳定的公开配置。

### 2. Web 当前信任浏览器提供的身份

- 原生页面写死 `DEFAULT_USER_ID = 1`，并在创建 session 与 turn 时把该值发回服务器（`amadeus/web/static/app.js:1,46-62,119-125`）。
- `SessionCreateRequest` 和 `MessageRequest` 要求客户端提供 `user_id`（`amadeus/web/schemas.py:14-25`）。
- session list 与 message history 通过 query 参数接收 `user_id`（`amadeus/web/routes.py:43-62`）。
- message route 直接把客户端给出的 `user_id/session_id` 传给 turn store（`amadeus/web/routes.py:66-76`）。
- turn status 与 SSE 只按裸 `turn_id` 查询，没有 owner 条件（`amadeus/web/routes.py:80-98`；`amadeus/turns/postgres.py:70-84`）。

因此，前端写死 ID 不是可靠的访问控制。浏览器开发者工具或任意 HTTP 客户端都能修改请求。

### 3. 独立外键不能证明 `(user_id, session_id)` 所有权

`conversation_turns` 的 `user_id` 与 `session_id` 分别引用 `users.id` 和 `conversation_sessions.id`（`migrations/versions/20260704_0001_postgres_foundation.py:75-98`）。这两条独立外键只能证明：

- user 存在；
- session 存在。

它们不能证明该 session 属于该 user。`PostgresTurnStore.create_turn()` 也没有在插入前校验完整身份（`amadeus/turns/postgres.py:37-63`）。

现有 `PostgresSessionStore.get_session_meta(SessionRef)` 已提供正确的复合检查：`WHERE id = %s AND user_id = %s`（`amadeus/session/postgres.py:90-101`）。Web 在创建 turn 前必须使用这个公共 session 边界验证 `SessionRef(owner_user_id, session_id)`，不能依靠外键或裸 session ID。

### 4. 现有测试证明 store 隔离，但没有证明 Web owner boundary

- 当前 Web 测试允许创建 user 1 与 user 2，并通过客户端 query/body 选择用户（`tests/web/test_postgres_web_app.py:13-43`）。这证明 route 会把客户端字段传给 store，不证明服务器拥有身份。
- SSE 测试只验证 terminal event，没有覆盖另一个 owner 读取已知 turn ID（`tests/web/test_postgres_web_app.py:64-91`）。
- 静态页测试反而明确要求浏览器发送 `user_id`（`tests/web/test_postgres_web_app.py:94-103`），与新的单用户 BFF 目标冲突。
- store 的多用户能力仍然有价值，应该继续通过 store 测试保留；改变的是 Web adapter 的信任边界，不是 PostgreSQL 领域模型。

### 5. 项目先例倾向显式破坏性清理，而不是长期兼容

- PostgreSQL-only 迁移明确不保留 SQLite runtime 兼容（`.trellis/tasks/archive/2026-07/07-04-remove-sqlite/design.md:61-67`）。
- structured session identity 任务明确删除字符串 session key 与兼容解析，并设有零残留搜索门禁（`.trellis/tasks/archive/2026-07/07-05-structured-session-identity/prd.md:5-9,59-81`）。
- 当前 backend spec 要求完整内部身份是 `SessionRef(user_id, session_id)`，裸 `session_id` 不是完整边界身份（`.trellis/spec/backend/quality-guidelines.md` 的 `Scenario: Structured Session Identity`）。

这些证据支持在早期产品阶段统一配置语义，而不是维持两个可能分裂的 user 配置。

## Akashic 参考结论

Akashic 主要使用由 channel/chat 派生的字符串 `session_key`，dashboard API 也直接通过 session key 路径访问会话（例如 `../akashic-agent/bootstrap/dashboard_api.py:877-940,1017-1053`）。它没有与 Amadeus `SessionRef(user_id, session_id)`、PostgreSQL owner scope 对应的统一 owner 配置机制。

因此本任务是 Amadeus-specific extension：

- 可以参考 Akashic“channel adapter 不应决定核心 runtime 身份语义”的边界意识；
- 不应迁移其字符串 session key 或 dashboard 路径身份；
- Amadeus 继续遵守已建立的 structured identity spec。

## 方案比较

### 方案 A：保留两个变量

```text
AMADEUS_OWNER_USER_ID
AMADEUS_MEMORY_USER_ID
```

优点：表面灵活。

缺点：允许 Web 会话 owner 与 memory owner 分裂；单用户产品没有已确认需求需要这种复杂度。拒绝。

### 方案 B：新变量优先、旧变量静默回退

```text
owner = AMADEUS_OWNER_USER_ID ?? AMADEUS_MEMORY_USER_ID ?? 1
```

优点：旧环境无需修改。

缺点：形成长期兼容路径；旧拼写可能永久存在；双变量同时配置时还需优先级与冲突规则。当前本地 `.env` 未设置旧变量，仓库也尚未形成稳定公开版本，收益很小。拒绝。

### 方案 C：统一新变量，旧变量 fail-fast（推荐）

```text
AMADEUS_OWNER_USER_ID=1
```

- `RuntimeConfig.owner_user_id` 取代 `default_memory_user_id`；Web/runtime/memory 共享。
- 如果环境或 dotenv 中仍出现 `AMADEUS_MEMORY_USER_ID`，启动时给出明确重命名错误，不静默忽略，也不把旧值当回退值。
- Docker、示例配置、文档和测试一次同步。

这不是兼容层，而是迁移护栏：既保持单一生产合同，又避免旧变量被静默丢弃后回落到 user 1。

## 推荐 Web 合同

### App factory 与依赖

- `create_app()` 在真实启动路径从 `RuntimeConfig.owner_user_id` 取得 owner。
- store 注入测试路径必须显式传入 `owner_user_id`，避免测试依赖隐藏默认值。
- `app.state.owner_user_id` 只由 app factory 写入；通过 typed FastAPI dependency 读取。

### Bootstrap

- 新增 `GET /api/bootstrap`，响应只含 `owner_user_id` 与明确批准的公开 feature flags。
- 不返回 API key、DSN、模型凭证、环境变量全集或 workspace 路径。

### Owner-scoped routes

- session create/list：移除客户端 `user_id` 输入，由 dependency 注入 owner。
- message history：用 `SessionRef(owner, session_id)` 查询；不接受 `user_id` query。
- message create：请求只含 `session_id/message/metadata`；创建 turn 前通过 session store 验证 `SessionRef(owner, session_id)`。
- turn status/SSE/cancel：读取 turn 后比较 `turn.user_id == owner`；不匹配统一返回 404，避免泄露资源是否存在。
- JSON response 继续输出结构化 `user_id/session_id`，用于可观察性、缓存 key 和完整身份证明。

## 受影响文件候选

- `amadeus/app/bootstrap.py`
- `amadeus/web/app.py`
- `amadeus/web/dependencies.py`
- `amadeus/web/routes.py`
- `amadeus/web/schemas.py`
- `amadeus/web/static/app.js`
- `tests/app/test_bootstrap.py`
- `tests/web/test_postgres_web_app.py`
- `.env.example`
- `docker-compose.yml`
- `docs/postgres-runtime.md`

后续 streaming 子任务会修改 turn/SSE/cancel 契约；identity 子任务应先稳定 owner dependency 与访问校验，避免 streaming 重复设计身份。

## 必需验证

1. 配置：新变量读取、默认 1、环境覆盖 dotenv、旧变量单独出现时 fail-fast、两变量同时出现时 fail-fast。
2. Bootstrap：只返回批准字段。
3. Web owner behavior：客户端不提供 user ID 也能完成 session/message 流程。
4. 越权：非 owner session 创建 turn、已知非 owner turn 的 status/SSE 均返回 404。
5. Store regression：多用户 session/turn/memory store 测试继续通过。
6. 搜索门禁：生产配置、Docker、示例和当前文档中不再出现 `AMADEUS_MEMORY_USER_ID`；允许 migration error 文本和专门回归测试出现该旧名称。

## 研究结论

推荐选择“统一 `AMADEUS_OWNER_USER_ID` + 旧变量 fail-fast 迁移护栏”。这比静默兼容更符合项目既有清理策略，也比直接忽略旧变量更安全。owner scope 必须在 Web adapter 明确验证完整 `SessionRef`；仅更换环境变量或隐藏前端输入，不能修复现有信任边界。

## 用户最终决策

用户在评审研究结论后明确选择：直接删除 `AMADEUS_MEMORY_USER_ID` 与 `default_memory_user_id` 的所有生产、测试、配置和当前文档引用，不实现兼容回退、旧变量检测、fail-fast 报错或迁移提示。后续 design/implement 必须以该决策为准；本文件上方的 fail-fast 内容保留为研究过程和被否决方案记录。
