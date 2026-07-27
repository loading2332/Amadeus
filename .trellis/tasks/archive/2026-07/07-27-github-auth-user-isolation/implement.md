# GitHub 登录与端到端用户运行时隔离实施计划

1. 建立认证数据与配置。
   - Alembic 新增 identity、refresh-session 表与索引。
   - 新增 GitHub OAuth、JWT、Cookie、refresh rotation 与 auth store 的 focused 模块/测试。
2. 接入 Web 登录和授权。
   - 用 `get_current_user()` 替代固定 owner scope；实现 login/callback/refresh/logout。
   - 认证矩阵覆盖普通 HTTP、SSE、跨用户资源和匿名 health。
3. 让 worker 只构造用户运行时。
   - worker 启动只加载无用户状态的 runtime config，不预构造固定 owner `PassiveApp`。
   - `PassiveAppTurnRunner` 每个 turn 以 `turn.user_id` 调用 `build_passive_app(user_id=...)`；不改写或复用其他用户 runtime 的状态。
4. 实现 workspace 与 Markdown memory 物理隔离。
   - 服务端派生 `<base>/<user_id>`，将 Markdown runtime 与文件工具绑定该路径。
   - 补 root containment、path traversal、symlink 与双用户 worker regression tests。
5. 禁用公网 MCP。
   - production Web worker 不注册 `local_trusted` add/remove/list 或宿主 MCP client；保留后续 sandbox 的明确扩展点。
6. 改造 React。
   - landing/login/logout、central refresh、SSE 认证恢复和 cache cleanup。
7. 部署与质量门。
   - 更新 `.env.example` 与 Compose 环境变量；README 按用户要求保持不变。
   - 运行 Web/worker/memory tests、Ruff、Mypy、前端 typecheck/lint/test/build；有生产 secret 后进行真实 OAuth/SSE smoke。

## 风险门

| 风险 | 必须证明 |
|---|---|
| Web 认证成功但 worker memory 仍是固定 owner | 同一 worker 两个 user 的检索和写入 trace 与文件路径均不同 |
| 修改共享 runtime 导致并发串用户 | context 不附着/覆盖共享 runtime；按调用显式传递 |
| 文件工具路径逃逸 | 路径解析与 symlink regression 测试拒绝跨 root 访问 |
| token 轮换竞争 | 事务条件更新/行锁加并发测试 |
| SSE token 到期丢内容 | 以 `after_seq` 重连并验证无重复事件 |

## 验证命令

```powershell
uv run pytest tests/web tests/worker tests/memory -q
uv run pytest tests/session tests/turns -q
uv run ruff check amadeus tests
uv run mypy
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
```

真实 PostgreSQL 测试保持单一 pytest 进程，避免共享 `clean_postgres()` 竞争。真实 GitHub OAuth 只在 secrets 已配置的部署环境执行人工 smoke。
