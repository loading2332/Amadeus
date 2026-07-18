# 所有者限定 Web 身份实施计划

## Review status

- 2026-07-18：用户已批准 `prd.md`、`design.md` 与本实施计划。
- 2026-07-18：已完成实现与 Trellis 质量检查；等待工作提交后归档。

## 验证结果

- 聚焦配置与真实 PostgreSQL Web 测试：36 passed。
- session、turn、PostgreSQL memory 回归：26 passed。
- Ruff：`amadeus tests` 全通过。
- 触及文件 mypy：全通过。
- 旧变量零残留搜索：无匹配。
- 全量 pytest：612 passed、1 个既有失败；旧评测测试引用已不存在的 `07-11-memory-retrieval-parameter-evaluation/review/dataset-freeze.md`。
- 全量 mypy：本次触及文件以外的既有 MCP/tool 测试共有 24 个错误。

## 依赖与执行顺序

本子任务是父任务的第一个实施目标。完成并归档后，`07-17-streaming-runtime-sse` 才能基于稳定 owner seam 实现 status/SSE/cancel；React 子任务最后执行。

## 实施清单

1. 配置合同
   - 将 `RuntimeConfig.default_memory_user_id` 重命名为 `owner_user_id`。
   - 只读取 `AMADEUS_OWNER_USER_ID`，默认 `1`，拒绝非整数和非正数。
   - 更新 memory runtime/service 组装使用新字段。
   - 直接删除旧变量所有生产与测试引用，不增加兼容或检测代码。

2. OwnerScope module
   - 在 `amadeus/web/` 建立 `OwnerScope`、`OwnerResourceNotFound`。
   - `require_session()` 通过 `SessionRef(owner, session_id)` 和 session store 验证复合所有权。
   - `require_turn()` 统一验证 turn 存在且属于 owner。
   - 添加聚焦 module interface 测试，覆盖 match/mismatch/missing。

3. App factory 与 FastAPI dependency
   - `create_app()` 正常路径读取 `config.owner_user_id`。
   - store 注入路径要求显式 `owner_user_id`。
   - app state 保存 owner，dependency 构造 `OwnerScope`。
   - 将 module not-found 统一映射为不泄露资源存在性的 404。

4. Web schemas 与 routes
   - 新增强类型 `BootstrapResponse(owner_user_id)`。
   - request models 移除 `user_id`，优先启用严格 extra-field 拒绝。
   - session create/list、history、message create、turn status/SSE 全部改用 `OwnerScope`。
   - message create 在写 turn 前验证 session owner。
   - 修正 metadata 合并顺序，服务器固定 `channel="web"`。
   - response models 继续输出结构化身份。

5. 原生验证页
   - 启动先获取 `/api/bootstrap`。
   - 不在普通 API request 中发送 `user_id`。
   - localStorage 恢复时比较 stored user 与 bootstrap owner；不一致则清理并创建新 session。
   - 不增加 React 或新的产品 UI。

6. 配置与文档
   - 更新 `.env.example`、`docker-compose.yml`、`docs/postgres-runtime.md`。
   - 明确 owner 是 Web/runtime/memory 统一身份，不是认证系统。

7. 公共行为验证
   - Web TestClient：bootstrap allowlist、owner session flow、非 owner session、非 owner turn status/SSE、伪造 user ID、metadata channel 覆盖。
   - 配置测试：默认、dotenv、环境覆盖、非法值。
   - 保持 PostgreSQL store 多用户回归测试通过。
   - 运行旧变量零残留搜索门禁。

## 验证命令

先窄后宽，PostgreSQL 相关测试在同一进程串行运行：

```powershell
uv run pytest -q tests/app/test_bootstrap.py tests/web/test_postgres_web_app.py
uv run pytest -q tests/session tests/turns tests/memory/test_postgres_memory_store.py
uv run ruff check amadeus/app/bootstrap.py amadeus/web tests/app/test_bootstrap.py tests/web/test_postgres_web_app.py
uv run mypy amadeus tests
uv run pytest -q
rg -n "AMADEUS_MEMORY_USER_ID|default_memory_user_id" amadeus tests .env.example docker-compose.yml docs
```

最后一条搜索命令预期无输出并返回无匹配状态。

## Review gates

- Gate 1：`OwnerScope` 是 routes 共用的真实 seam，没有把校验复制到每条 route。
- Gate 2：浏览器无法通过 body/query/metadata 改变 owner 或 channel。
- Gate 3：非 owner session/turn 对外统一 404。
- Gate 4：store 保留多用户能力，单用户假设只存在于 Web adapter/config composition。
- Gate 5：旧变量零残留，且没有兼容、检测或迁移提示实现。

## 风险与 rollback points

- 配置重命名：若新字段没有贯通 memory 组装，可能造成运行时身份分裂；在进入 Web 修改前先完成配置测试。
- App factory 注入：若测试使用隐藏默认 owner，会掩盖真实 wiring 缺陷；注入 store 时必须显式 owner。
- Session/turn 校验：独立外键不是所有权证明；任何直接 `create_turn(session_id)` 的 Web 路径都应阻止合并。
- 静态页恢复：bootstrap owner 变化时必须清理旧 session，而不是继续请求旧 ID。
- 无数据库 migration；每个阶段可通过还原本子任务代码回滚，最终交付以整任务 git revert 为主。
