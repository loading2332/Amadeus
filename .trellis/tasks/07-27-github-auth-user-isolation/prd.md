# GitHub 登录与端到端用户运行时隔离

## 目标

为公网 Amadeus Web 增加 GitHub 登录与标准双 token 会话。服务端从已验证 JWT 得到的本地 `user_id` 必须贯穿 Web API、turn queue、worker、长期记忆、Markdown memory 与用户 workspace；匿名访问者不能调用聊天，且任意认证用户只能访问和驱动归属自己的状态与工具上下文。

## 已确认事实

- 生产 Compose 的 API 已绑定 `127.0.0.1:8000`，PostgreSQL 不对公网发布；反向代理是 Web 入口。
- 当前 Web `get_owner_scope()` 无条件使用 `AMADEUS_OWNER_USER_ID`；所有访问者共享 owner。数字 `session_id` 只是资源编号，不是身份凭证。
- session、message、turn、Postgres long-term memory 均已以 `user_id` 关联或过滤；worker 已从 `turn.user_id` 创建 `SessionRef`。
- `build_passive_app()` 却在 worker 启动时用固定 `AMADEUS_OWNER_USER_ID` 预构造长短期 memory 与共享 workspace，导致实际运行时身份链在 memory/workspace 边界断裂。
- `local_trusted` MCP 允许宿主机任意子进程，不具备公网多用户隔离合同。

## 本期需求

1. 根路径展示轻量公开介绍页与“使用 GitHub 登录开始体验”入口；不加载聊天历史或聊天数据。
2. 仅支持 GitHub OAuth。首次合法回调自动创建本地用户与稳定身份映射；不提供邀请制、审核、密码注册、Google OAuth 或 RBAC。
3. GitHub 身份映射使用稳定 provider subject，不能依赖可变用户名或邮箱。
4. 登录成功后签发 15 分钟 JWT access token 与 7 天随机不透明 refresh token。两者通过 `HttpOnly`、`Secure`、`SameSite=Lax` Cookie 发送；refresh token 每次刷新轮换，旧 token 重用撤销其所属登录会话。
5. 业务 API 仅从验签 access JWT 解析用户；不接受请求中的 `user_id`。未登录业务 API 一致拒绝，health 保持匿名可用。
6. 认证用户仅能经 Web API 列出、读取、创建、删除、发送、取消、重试或 SSE 订阅其 session/turn；跨用户资源不得泄露存在性。
7. worker 的唯一运行时用户来源是已持久化 `turn.user_id`，不得用 `AMADEUS_OWNER_USER_ID` 预构造单例用户记忆。共享 LLM client、数据库连接池与运行时框架可复用；用户相关 store、memory engine、Markdown runtime、session context 和文件工具根目录必须按 turn 动态构造。
8. 每个用户 workspace 由服务端从内部 user id 派生，客户端、模型与工具参数不得选择或越过其根路径；Markdown memory 与 workspace 在物理路径和数据库归属上均隔离。
9. 前端提供登录、登出和未登录状态；access token 过期时仅重试一次安全可重放的普通 HTTP 请求。SSE 重连前恢复有效 access token，并使用现有 `after_seq` 恢复语义。
10. 当前固定 owner 的生产数据不迁移；新 GitHub 用户从新身份开始。

## 明确不属于本期

- 任意 MCP、MCP sandbox、宿主进程隔离与公网 MCP；公网 MCP 保持关闭。
- 配额、速率限制、验证码、邀请码、账号审核、管理后台与设备管理。
- refresh token 跨设备全局撤销、Google OAuth、密码登录与 RBAC。

## 技术约束

- 使用成熟 OAuth/OIDC 客户端库完成授权码流程与 `state` 校验，不手写 OAuth 协议。
- JWT 只由服务端签发/验证，至少校验 `sub`、`iss`、`aud`、`iat` 与 `exp`；refresh token 非 JWT，数据库只保存其哈希、状态与替换关系。
- 生产启动须校验 GitHub client id/client secret、JWT 签名密钥、公开站点 URL 与 HTTPS 配置；缺失或示例值必须失败。
- 数据库变更使用 Alembic migration；PostgreSQL store 保持 focused 边界与参数化 SQL。
- Web 或工具公开错误不得暴露 token、client secret、第三方响应、内部路径或跨用户资源存在性。
- `AMADEUS_OWNER_USER_ID` 只能保留给已明确的旧单用户/CLI 兼容入口，不能再作为生产多用户 worker 的身份来源。

## 验收标准

- [x] 未登录访问聊天 API、创建 session、发送消息、读取 SSE、取消或重试 turn 一律被拒绝，`/api/health` 保持可用。
- [x] GitHub 回调创建或复用唯一的本地用户及稳定身份映射；业务身份唯一来自有效 access JWT，前端伪造 `user_id` 无效。
- [x] access JWT 过期后有效 refresh token 可轮换续发；旧 refresh token 重用撤销其登录会话。登出撤销 refresh session、清 Cookie，之后 API 变为未认证。
- [x] 两个认证用户只可通过 Web API 访问各自资源；猜测其他用户 session id 或 turn id 得到不泄露存在性的拒绝。
- [x] worker 依次处理两个用户 turn 时，以各自 `turn.user_id` 构造长期记忆、Markdown memory 与 workspace 上下文；检索、写入和文件工具均无跨用户残留。
- [x] 浏览器请求、模型工具参数和工具路径均不能使运行时跳出当前用户的服务端派生 workspace 根。
- [x] 前端登录、登出、refresh 单次重试、SSE 认证恢复有 focused tests；后端 OAuth/JWT/rotation、Web 授权与 worker 多用户 memory/workspace 有 focused tests。
- [x] 受影响的 Web、worker、memory、session 测试，Ruff、本次改动 Mypy、前端 typecheck/lint/test/build 与必要 PostgreSQL 集成测试通过。
