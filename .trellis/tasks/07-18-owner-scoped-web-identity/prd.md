# 建立所有者限定的 Web 身份边界

## Goal

为 Amadeus 单用户产品建立由服务器拥有的 owner identity，使浏览器不能自行选择 `user_id`，同时保留底层 session、turn 和 memory store 的结构化多用户能力。

## Background

- 当前原生 Web 页把 `DEFAULT_USER_ID = 1` 写死在浏览器代码中（`amadeus/web/static/app.js:1`）。
- Web 请求模型和查询参数允许客户端传入任意 `user_id`（`amadeus/web/schemas.py:14-25`、`amadeus/web/routes.py:30-77`）。
- runtime 只有 `AMADEUS_MEMORY_USER_ID` / `default_memory_user_id`，该名称只表达记忆默认用户，不足以代表整个产品的所有者身份（`amadeus/app/bootstrap.py:72-78,292-293`）。
- `PostgresSessionStore` 已按显式 `user_id/session_id` 隔离数据；单用户假设不应下沉并破坏该存储能力。

## Requirements

- R1. 引入服务器端 `AMADEUS_OWNER_USER_ID`，作为 Web、runtime 默认会话和长期记忆的统一所有者身份。
- R2. 提供只返回安全公开配置的 bootstrap API，使浏览器能够读取 owner ID 和经批准的功能开关，但不能提交或覆盖 owner ID。
- R3. Web 创建/列表/历史/消息/turn/SSE/取消接口由服务器注入 owner ID，不再信任客户端请求体或查询参数中的 `user_id`。
- R4. Web 对 session 和 turn 的访问必须同时校验 owner ID；只凭裸 `session_id` 或 `turn_id` 不得越过所有者边界。
- R5. JSON 响应继续显式包含结构化 `user_id/session_id`，底层 store 继续接受显式多用户身份。
- R6. 现有原生验证页在 React 替换前改为消费 bootstrap API，不继续写死用户 ID。
- R7. Docker、`.env.example`、运行文档和配置测试同步使用统一 owner 配置。
- R8. 直接删除 `AMADEUS_MEMORY_USER_ID`、`default_memory_user_id` 及其所有兼容、回退、检测、报错和迁移提示逻辑；生产配置只存在 `AMADEUS_OWNER_USER_ID` / `owner_user_id`。
- R9. Web adapter 拥有 `channel="web"` 等保留 metadata；客户端 metadata 不得覆盖服务器身份或通道字段。

## Acceptance Criteria

- [x] 浏览器不提供 `user_id` 也能创建、列出和使用 owner 会话。
- [x] 伪造请求体、查询参数或不属于 owner 的 session/turn 不能读取或写入其他用户数据。
- [x] bootstrap API 只暴露公开配置，不返回密钥、DSN、模型凭证或内部路径。
- [x] memory/runtime/Web 使用同一 owner ID，相关配置和集成测试通过。
- [x] `PostgresSessionStore`、`PostgresTurnStore` 和 memory store 的多用户隔离测试保持通过。
- [x] 在 `amadeus`、`tests`、`.env.example`、`docker-compose.yml` 和当前 `docs` 中搜索 `AMADEUS_MEMORY_USER_ID|default_memory_user_id` 无匹配。
- [x] 客户端提交 `metadata.channel` 或其他保留身份字段时，持久化的 turn 仍使用服务器定义的 Web 通道和 owner identity。

## Out of Scope

- 登录、注册、Cookie/JWT、密码和多租户授权。
- 把 PostgreSQL store 改成单用户存储。

## Research

- [`research/owner-identity-and-config-migration.md`](./research/owner-identity-and-config-migration.md)：确认 Web 客户端身份信任缺陷、独立外键无法证明复合所有权、Akashic 无直接 owner 配置机制。研究曾推荐旧变量 fail-fast，但用户最终明确选择直接删除旧变量及全部迁移逻辑。
