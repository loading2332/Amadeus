## 快速开始

```powershell
cp .env.example .env
wsl docker compose up --build
```

访问 <http://localhost:8000>

## 本地开发

后端(Python 3.11+,用 [uv](https://docs.astral.sh/uv/) 管理):

```powershell
$env:AMADEUS_POSTGRES_DSN="postgresql://amadeus:amadeus@localhost:5432/amadeus"
uv run alembic upgrade head
uv run uvicorn amadeus.web.main:app --host 0.0.0.0 --port 8000
uv run python -m amadeus.worker.turn_worker
uv run python -m amadeus.worker.post_response_memory_worker
```

前端(pnpm + Vite,`/api` 代理到 127.0.0.1:8000):

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

## 测试与质量检查

```powershell
# 后端
uv run pytest -q
uv run ruff check
uv run mypy

# 前端(在 frontend/ 下)
pnpm typecheck
pnpm lint
pnpm test -- --run
pnpm run test:e2e   # 首次先 pnpm exec playwright install chromium
```

`test:e2e` 会在同一 PostgreSQL 实例里建独立的 `amadeus_e2e` 库,跑真实的 FastAPI 与 worker;回答由确定性 fixture 提供

## 目录

```
amadeus/          Python 包
  web/            FastAPI 路由、SSE、静态托管
  worker/         turn worker 与独立后台 memory worker
  runtime/        推理循环(tool loop)
  memory/         长期记忆:检索、整理、Markdown 记忆
  session/ turns/ 会话与 turn 的存储层
  tools/ mcp/ plugin/  工具系统与 MCP 接入
frontend/         React + MUI 前端(pnpm workspace)
migrations/       Alembic 迁移
tests/            pytest 测试
docs/             运行时与实验文档
```

## 更多文档

- `docs/postgres-runtime.md` — PostgreSQL 运行时、Docker 服务与 turn 流式契约
- `docs/prompt-cache-benchmark.md` — 提示词缓存实验
- `.trellis/spec/` — 项目编码规范(后端/前端)
