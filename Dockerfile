FROM node:22-alpine AS frontend-build

WORKDIR /frontend

RUN corepack enable && corepack prepare pnpm@10.26.0 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile

COPY frontend ./
RUN pnpm run build


FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY amadeus ./amadeus
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
COPY --from=frontend-build /frontend/dist ./amadeus/web/static

RUN pip install --no-cache-dir .

CMD ["uvicorn", "amadeus.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
