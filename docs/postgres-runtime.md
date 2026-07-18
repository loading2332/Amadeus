# PostgreSQL Runtime

Amadeus now uses PostgreSQL as the production runtime state backend. SQLite
stores remain only as legacy test fixtures and historical local implementations;
production bootstrap fails fast when `AMADEUS_POSTGRES_DSN` is missing or when
the PostgreSQL `vector` extension is unavailable.

## Docker Compose

Start the default local stack:

```powershell
docker compose up --build postgres migrate api worker
```

Services:

- `postgres`: `pgvector/pgvector:pg16`, stores database state in the
  `postgres-data` volume.
- `migrate`: runs `alembic upgrade head` after PostgreSQL is healthy.
- `api`: runs `uvicorn amadeus.web.main:app --host 0.0.0.0 --port 8000`.
- `worker`: runs `python -m amadeus.worker.turn_worker --workspace-root /workspace`.
- `amadeus-workspace`: shared Markdown memory and runtime workspace volume.

The API is exposed on `http://localhost:8000`.

## Local Commands

When running outside Docker:

```powershell
$env:AMADEUS_POSTGRES_DSN="postgresql://amadeus:amadeus@localhost:5432/amadeus"
uv run alembic upgrade head
uv run uvicorn amadeus.web.main:app --host 0.0.0.0 --port 8000
uv run python -m amadeus.worker.turn_worker
```

Useful checks:

```powershell
docker compose ps
uv run alembic current
uv run pytest -q tests/db tests/session tests/turns tests/web/test_postgres_web_app.py tests/worker/test_turn_worker.py
uv run pytest -q tests/memory/test_postgres_memory_store.py tests/memory/test_session_memory_runtime.py
```

## Configuration

Required:

- `AMADEUS_POSTGRES_DSN`
- `AMADEUS_OWNER_USER_ID=1`：Amadeus 所有者的结构化用户 ID。Web API、被动运行时与长期记忆共同使用此身份；浏览器只能通过 `/api/bootstrap` 读取，不能在业务请求中覆盖。
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`

Long-term memory:

- `AMADEUS_LONG_TERM_MEMORY_ENABLED=1`
- `OPENAI_EMBEDDING_MODEL=text-embedding-v4`

Turn 流式运行时：

- `AMADEUS_TURN_STREAM_FLUSH_CHARACTERS=128`：累计新增正文达到该字符数时写入快照。
- `AMADEUS_TURN_STREAM_FLUSH_INTERVAL_SECONDS=0.1`：有新正文时允许按时间阈值批量刷新；不会逐 token 写库。
- `AMADEUS_TURN_HEARTBEAT_INTERVAL_SECONDS=10`：worker 续租和检查取消请求的周期。
- `AMADEUS_TURN_STALE_AFTER_SECONDS=120`：processing turn 超过此时间无心跳后进入中断对账；必须大于心跳周期。

浏览器通过 `GET /api/turns/{turn_id}/events` 读取 PostgreSQL 中的持久化事件。SSE 使用单调 `id` 与统一的 `turn_event` envelope；重连时可传 `Last-Event-ID` 或 `after_seq`。SSE 断开不会取消执行，只有 `POST /api/turns/{turn_id}/cancel` 会发出持久化取消请求。

Docker services use `postgres` as the database host:

```text
postgresql://amadeus:amadeus@postgres:5432/amadeus
```

Host-local commands use `localhost`:

```text
postgresql://amadeus:amadeus@localhost:5432/amadeus
```

## Non-Goals

- Existing SQLite data is not migrated.
- Historical planning docs may mention older SQLite paths; they are not the
  current production runtime.
- Real LLM, Telegram, Scheduler, ProactiveLoop, and DriftRunner smoke tests are
  outside this PostgreSQL runtime cleanup.
