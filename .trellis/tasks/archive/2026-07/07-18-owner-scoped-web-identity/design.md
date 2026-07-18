# 所有者限定 Web 身份设计

## 1. 设计目标

把 owner identity 从浏览器输入提升为服务器配置，并在 FastAPI Web adapter 内形成一个可测试的 owner scope module。该 module 隐藏 session/turn 复合所有权校验，routes 只组合 HTTP 输入输出，不重复实现授权判断。

本设计支持父任务的第一层能力：先稳定 Web 身份与信任 seam，再由 streaming 子任务扩展 SSE/cancel，再由 React 子任务消费最终合同。

## 2. 第一性原理与不变量

1. PostgreSQL 是 session/turn/message 的权威数据源，浏览器不是身份权威。
2. `SessionRef(user_id, session_id)` 是完整内部 session identity；裸 `session_id` 不完整。
3. 单用户是 Web 产品假设，不是 store 限制；PostgreSQL adapters 继续支持多用户。
4. 任意客户端字段都可被篡改；owner ID、channel 和保留 metadata 必须由服务器写入。
5. 不属于 owner 与不存在的资源对 Web 调用者都表现为 404，避免资源存在性泄露。
6. JSON response 保留 `user_id/session_id`，便于观察完整身份；request 不允许选择 owner。

## 3. Module 与 seam

### 3.1 RuntimeConfig module

外部 interface：

```python
@dataclass(frozen=True)
class RuntimeConfig:
    owner_user_id: int = 1
    ...
```

- `AMADEUS_OWNER_USER_ID` 是唯一配置名称。
- 值必须是正整数。
- `AMADEUS_MEMORY_USER_ID`、`default_memory_user_id` 被直接删除；没有 alias、fallback、检测或迁移错误。
- memory runtime 和 Web app 都读取同一个 `owner_user_id`。

### 3.2 OwnerScope module

在 `amadeus/web/` 中建立 owner scope module，external interface 保持小而明确：

```python
@dataclass(frozen=True)
class OwnerScope:
    user_id: int
    session_store: PostgresSessionStore
    turn_store: PostgresTurnStore

    def require_session(self, session_id: int) -> SessionRef: ...
    def require_turn(self, turn_id: str) -> Turn: ...
```

实现隐藏：

- `require_session()` 构造 `SessionRef(owner, session_id)`，通过 `get_session_meta()` 验证复合所有权；失败抛出统一 `OwnerResourceNotFound`。
- `require_turn()` 读取 turn，再比较 `turn.user_id == owner`；missing/mismatch 都抛相同异常。
- routes 只需要学习一个 module interface；完整校验逻辑集中，后续 status/SSE/cancel 复用。

这是一个有实际 depth 的 module：如果删除它，复合身份验证、404 语义和 owner 注入会散落到 message/history/turn/SSE/cancel 多个调用点。依赖是本地 PostgreSQL adapter，使用真实测试数据库验证，不额外制造 hypothetical port。

### 3.3 FastAPI dependency adapter

`create_app()` 把 `owner_user_id`、session store 和 turn store 写入 app state。`get_owner_scope(request)` 构造 `OwnerScope`：

- 正常启动：从 `load_runtime_config()` 取得 owner。
- 注入 store 的测试路径：必须显式传 `owner_user_id`，禁止隐藏默认值让测试绕过配置 seam。
- FastAPI exception handler 或 route-level mapper 把 `OwnerResourceNotFound` 统一映射为 `HTTP 404 {"detail": "Resource not found"}`。

## 4. HTTP 合同

### 4.1 Bootstrap

```http
GET /api/bootstrap
```

```json
{
  "owner_user_id": 1
}
```

本子任务不创建通用 feature flag 字典。将来只有经产品确认的公开能力才可增加强类型字段。禁止序列化 `RuntimeConfig` 全对象。

### 4.2 Sessions

```http
POST /api/sessions
{ "title": "...", "metadata": {} }

GET /api/sessions
```

- request/query 不包含 `user_id`。
- routes 使用 `scope.user_id` 调用 store。
- response 继续包含 `user_id/session_id`。

### 4.3 Messages

```http
GET /api/sessions/{session_id}/messages

POST /api/messages
{
  "session_id": 10,
  "message": "hello",
  "metadata": {}
}
```

- history 先调用 `scope.require_session(session_id)`，再按完整 identity 查询。
- create turn 先验证 session；随后使用 `scope.user_id`。
- metadata 合并采用客户端字段在前、服务器字段在后：`{**payload.metadata, "channel": "web"}`。后续若增加保留字段，集中在同一 sanitizer/module 中处理。

### 4.4 Turn status 与 SSE

- `GET /api/turns/{turn_id}` 先调用 `scope.require_turn()`。
- `GET /api/turns/{turn_id}/events` 在建立流前调用 `scope.require_turn()`。
- streaming 子任务新增 cancel route 时必须复用相同 interface。
- 本子任务不改变现有 SSE event schema；只稳定访问 seam。

## 5. 原生验证页过渡

React 尚未接管前，`amadeus/web/static/app.js`：

1. 启动时请求 `/api/bootstrap`；
2. owner ID 只用于显示、完整 cache key 和检查本地 session 是否仍属于当前 owner；
3. session/message HTTP request 不再发送 `user_id`；
4. localStorage 可以保留 `{user_id, session_id}` 作为恢复证据，但 stored user 不参与服务器身份选择；与 bootstrap owner 不一致时清除旧 session。

该过渡页仍是 smoke adapter，不扩展产品 UI。

## 6. 数据与数据库影响

- 无 Alembic migration。
- 不修改 users/sessions/messages/turns 表结构。
- 不把 owner ID 做成全局数据库常量。
- 独立外键不能证明复合所有权，因此 Web 必须显式使用 `SessionRef` 校验；本任务不借机做宽泛 schema 重构。

## 7. Akashic 参考与差异

Akashic 以 channel/chat 派生字符串 `session_key`，没有对应的 PostgreSQL owner 配置机制。Amadeus 只迁移“adapter 不应随意定义核心身份”的设计意识，继续采用自身已验证的 `SessionRef` 合同。这是项目特定扩展，不复制 Akashic dashboard 的字符串路径身份。

## 8. 兼容与破坏面

- Web request 移除 `user_id`，属于明确破坏性合同变更。
- 环境变量直接改为 `AMADEUS_OWNER_USER_ID`；旧名称完全删除，无兼容和提示。
- response 结构保持兼容。
- store interface 保持多用户兼容。
- 现有原生页面与 Web tests 在同一提交内更新，避免中间状态不可运行。

## 9. 错误矩阵

| 场景 | 行为 |
|---|---|
| owner 配置缺省 | 使用默认正整数 `1` |
| owner 配置非整数或非正数 | 启动失败并指出新变量无效 |
| session 不存在或属于其他 user | 404，不能创建 turn/读取历史 |
| turn 不存在或属于其他 user | status/SSE 返回相同 404 |
| 客户端仍发送额外 `user_id` | Pydantic schema 按严格输入策略拒绝，或至少完全忽略且测试证明不能改变 owner；实现阶段优先选择 `extra="forbid"` |
| 客户端 metadata 覆盖 `channel` | 服务器强制写回 `web` |
| bootstrap 请求 | 只返回 `owner_user_id` |

## 10. 测试 seam

- `RuntimeConfig` interface：dotenv/env/default/正整数测试。
- `OwnerScope` interface：真实 PostgreSQL 下 session/turn owner match 与 mismatch。
- HTTP public behavior：TestClient 证明无 client user ID 的完整 flow、伪造字段拒绝、bootstrap allowlist、owner 404。
- store regression：保留现有多用户 store 行为测试，不把 store 测试改写成单用户。
- 静态过渡页：只检查 bootstrap、无 request user ID、localStorage owner mismatch 恢复逻辑；不测试私有函数细节。

## 11. Rollout 与 rollback

Rollout 顺序：配置模型与 app state → owner module/dependency → schemas/routes/bootstrap → 静态页 → Docker/docs/tests。所有变化一起交付，不发布同时接受新旧身份合同的中间版本。

Rollback 为 git 级回滚整个子任务。由于没有数据库 migration，回滚不会改变已存数据；但回滚后部署配置需同步恢复旧版本所需变量。
