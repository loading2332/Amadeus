FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY amadeus ./amadeus
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini

RUN pip install --no-cache-dir .

CMD ["uvicorn", "amadeus.web.main:app", "--host", "0.0.0.0", "--port", "8000"]
