# FastAPI 网页对话 turn 框架设计

## 问题

Amadeus 已经能运行被动 LLM turn，但入口主要是本地 CLI/runtime。浏览器客户端需要一个非阻塞 HTTP 契约，因为一次 LLM turn 可能远长于普通请求响应。第一版 Web 切片要引入这个契约，但不能把 Web 细节混进 `PassiveRuntime`。

FastAPI 的定位是新增 Web channel：让用户除了 Telegram、QQ 等 IM 软件之外，也可以直接在网页端使用 Amadeus。它不是替代 IM adapter，而是把“输入通道”和“agent runtime 执行”分层。

## 架构

```text
浏览器 HTML/JS
  -> FastAPI app
  -> TurnStore.create_turn(status=pending)
  -> 立即返回 turn_id

独立 worker 进程
  -> TurnStore.claim_next_pending()
  -> PassiveApp.start()
  -> PassiveRuntime.run_turn(session_key, user_message)
  -> TurnStore.mark_done(answer) 或 mark_failed(error)

浏览器
  -> GET /api/turns/{turn_id}
  -> GET /api/turns/{turn_id}/events
```

## 模块边界

- `amadeus/web/`
  - 拥有 FastAPI app 构建、请求/响应模型、临时静态验证页面和 SSE 格式化。
  - 采用 `APIRouter` 分层：`app.py` 只负责 app factory 和 router/static 组装，`routes.py` 承载 `/api` 端点，`schemas.py` 承载 Pydantic 模型，`dependencies.py` 从 app state 注入 store/static dir，`sse.py` 承载事件流格式化。
  - 不能拥有 LLM provider 初始化，也不能执行 runtime turn。
- `amadeus/worker/`
  - 拥有独立 worker 命令和 worker loop。
  - 构建 `PassiveApp`，启动 plugins，消费 turns，并关闭 app 生命周期。
- `amadeus/turns/`
  - 拥有 turn 状态契约和第一版存储实现。
  - store 接口要按后续 PostgreSQL 实现可替换的形状设计。
- 现有 `amadeus/runtime/`、`amadeus/app/bootstrap.py`、`amadeus/session/`
  - 继续作为 agent 执行和 session 持久化的真实来源。

## 数据契约

### Turn 状态

允许状态：

- `pending`：API 已接收用户消息，但还没有 worker 执行。
- `processing`：worker 已 claim 该 turn，正在运行 passive runtime。
- `done`：runtime 完成，并产生助手回答。
- `failed`：worker 捕获 runtime 或生命周期失败。

### 提交请求

必填字段：

- `message: str`

可选字段：

- `session_key: str | None`
- `metadata: dict[str, Any] | None`

如果 `session_key` 缺失，临时网页可以发送 localStorage 生成的 key。后端可以为本地手动使用提供默认值，但测试应使用显式 `session_key`。

### 提交响应 / Turn 响应

稳定字段：

- `turn_id`
- `session_key`
- `status`
- `answer`
- `error`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `metadata`

响应不能暴露 provider secret 或原始 plugin 异常细节。

## 存储设计

第一版可以用 SQLite，因为本任务明确推迟 PostgreSQL。但它仍然要表现得像队列：

- `create_turn(...)`
- `get_turn(turn_id)`
- `claim_next_pending()`
- `mark_done(turn_id, answer)`
- `mark_failed(turn_id, error)`

Session 序列化规则：

- `claim_next_pending()` 不能 claim 一个已有 `processing` turn 的同 session pending turn。
- `mark_done()` 和 `mark_failed()` 只能从 `processing` 状态转出；如果 turn 已经是 `done` 或 `failed`，迟到的终态写入不能覆盖已有结果。
- 在单进程 SQLite worker 中，可以用进程内 lock 保证 claim 原子性。
- 后续 PostgreSQL store 中，等价 claim 应使用 `FOR UPDATE SKIP LOCKED`，并保留“同 session 不存在 active turn”的谓词。

## Runtime 执行

worker 应使用和 CLI 相同的 `PassiveApp` 组合路径：

```python
app = build_passive_app(...)
await app.start()
result = await app.runtime.run_turn(session_key=turn.session_key, user_message=turn.content)
await app.aclose()
```

对 `run_forever` 来说，worker 进程应只构建一次 app，并在进程退出时关闭。测试可以注入 fake runner/service，然后直接调用 `run_once()`。

## API 设计

最小接口：

- `GET /api/health`
- `POST /api/messages`
- `GET /api/turns/{turn_id}`
- `GET /api/turns/{turn_id}/events`
- `GET /`
- 临时验证页面静态文件

SSE 事件：

- event name 与 turn status 一致。
- event data 是完整 turn response JSON。
- `done` 或 `failed` 后关闭连接。
- 只有 payload 变化时才发送，避免 UI 重复更新。

## 临时前端

只使用原生 HTML/CSS/JS：

- 不使用 React；
- 不使用 bundler；
- 不做 auth；
- localStorage 可以保存生成的 `session_key`；
- 显示消息和当前 turn 状态；
- 优先使用 `EventSource`，必要时 fallback 到 polling。

该页面只是验证工具，不代表后续前端架构。

## 兼容与迁移

- 第一版 store 不依赖 PostgreSQL。
- Turn store 接口和状态名要兼容后续 `PostgresTurnStore`。
- 本任务不迁移 memory 或 session tables。
- 不要把 `SessionStore` 改成 telegram-bot 的 JSON session 模型；Amadeus 已经有按行存储的 message persistence。

## 失败边界

- API 校验错误走 FastAPI 标准 4xx 响应。
- turn id 不存在返回 404。
- runtime 失败由 worker 捕获，并存成 `failed`。
- cleanup 失败不应覆盖原始 turn failure。
- SSE 遇到 missing turn 时发 `failed` 并关闭。

## 验证策略

- Turn store 单元测试：create/get/claim/done/failed 和同 session 序列化。
- Worker 测试：用 fake runtime/service 覆盖成功和失败。
- API 测试：用注入 fake store 覆盖 submit/status 和 SSE。
- 静态页面第一版只做本地 dev server 手动验证，不要求复杂浏览器自动化。
