# FastAPI 网页对话 turn 框架实施计划

## 范围

实现一个窄的垂直切片：

1. Turn 状态和 store 契约。
2. FastAPI 提交、状态查询、SSE API。
3. 调用现有 `PassiveRuntime` 的独立 worker 命令。
4. 原生 HTML/CSS/JS 验证页。
5. 使用 deterministic fake 的聚焦测试。

本任务不做 PostgreSQL、auth、React、Telegram、QQ、proactive、scheduler 或 Drift 工作。

## 执行清单

- [x] 如果缺失，增加 FastAPI 运行依赖：
  - `fastapi`
  - `uvicorn`
  - 如果测试需要 FastAPI `TestClient`，增加 `httpx`。
- [x] 创建 `amadeus/turns/`：
  - `models.py` 或等价 dataclass/constants，定义 turn status 和 `Turn`。
  - `store.py`，实现第一版 SQLite-backed store。
  - 如确有需要再增加 `get_turn_store(...)` factory，配置保持最小。
- [x] 增加 `conversation_turns` SQLite schema。
  - 优先使用 workspace root 下单独 turn DB 或清晰命名的 DB 文件。
  - 除非必要，不改现有 session/message persistence。
- [x] 创建 worker service：
  - claim 下一个 pending turn；
  - 标记 `processing`；
  - 调用 injected runner 或 `PassiveRuntime.run_turn`；
  - 标记 `done` 或 `failed`。
- [x] 增加 worker 命令/module：
  - 独立进程入口，例如 `python -m amadeus.worker.turn_worker`；
  - 如果直接，支持 `--workspace-root`、`--env` 和 poll interval。
- [x] 创建 `amadeus/web/` FastAPI app：
  - `POST /api/messages`；
  - `GET /api/turns/{turn_id}`；
  - `GET /api/turns/{turn_id}/events`；
  - `GET /api/health`；
  - serve static validation page。
- [x] 按 FastAPI 分层实践拆分 Web 层：
  - `app.py` 只做 app factory 和 router/static 组装；
  - `routes.py` 使用 `APIRouter` 承载 `/api` 端点；
  - `schemas.py` 放请求/响应模型；
  - `dependencies.py` 放 FastAPI 依赖注入；
  - `sse.py` 放 turn event stream。
- [x] 增加临时静态页面：
  - `index.html`；
  - `styles.css`；
  - `app.js`；
  - 提交消息、订阅 SSE、显示状态和回答。
- [x] 增加测试：
  - turn store 成功路径和同 session 序列化；
  - worker 成功/失败；
  - API submit/status；
  - SSE terminal event 行为。
- [x] 只有当新命令/env var 需要可发现性时，更新 docs 或 `.env.example`。

## 验证命令

先跑窄测试：

```powershell
pytest tests/web tests/worker tests/turns
```

如果测试目录不同，就运行实际新增的测试文件。

如果触及 runtime/app 行为，再扩大：

```powershell
pytest tests/app/test_bootstrap.py tests/runtime/test_runtime.py
```

如果改了共享配置或依赖，再跑完整检查：

```powershell
pytest
ruff check amadeus tests
mypy
```

## 手动 smoke

实现后开两个终端：

```powershell
uvicorn amadeus.web.main:app --reload
python -m amadeus.worker.turn_worker
```

打开页面并验证：

- 发送消息会创建 queued turn；
- 状态变成 processing；
- 最终助手回复出现；
- 如果 worker 不能调用 provider，失败状态可见。

## 回滚点

- 如果 FastAPI 依赖造成 packaging 问题，保留 turn store 和 worker tests，暂停 API wiring，不改 runtime internals。
- 如果真实 `PassiveApp` worker 生命周期不稳定，保留 worker service 可注入，并先用 fake runner 验证。
- 如果 SSE 测试脆弱，保持 endpoint 行为简单，直接测试 async generator。

## 开始实现前 review gate

执行 `task.py start` 前确认：

- PRD 已记录临时原生前端决定。
- Design 保持 FastAPI 和 worker 解耦。
- Implementation plan 没有 PostgreSQL/auth/React 范围膨胀。
