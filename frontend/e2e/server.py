from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import uvicorn
from alembic import command
from alembic.config import Config
from psycopg import sql

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from amadeus.runtime.streaming import TurnStreamSink  # noqa: E402
from amadeus.session import PostgresSessionStore  # noqa: E402
from amadeus.turns import PostgresTurnStore, Turn  # noqa: E402
from amadeus.web.app import create_app  # noqa: E402
from amadeus.worker.turn_worker import TurnWorker  # noqa: E402

OWNER_USER_ID = 991_337
E2E_DATABASE = "amadeus_e2e"


class DeterministicRunner:
    async def run(self, turn: Turn, stream_sink: TurnStreamSink) -> str:
        if "[slow]" in turn.content:
            answer = ""
            for chunk in ("慢速", "回答", "仍在", "继续"):
                await stream_sink.publish_content(chunk)
                answer += chunk
                await asyncio.sleep(0.35)
                await stream_sink.check_cancelled()
            return answer

        if "[fail]" in turn.content and turn.retry_of_turn_id is None:
            await stream_sink.publish_content("失败前的部分回答")
            raise TimeoutError("deterministic provider timeout")

        if "[markdown]" in turn.content:
            answer = (
                "## Markdown 验证\n\n"
                "| 列 | 很长的内容 |\n| --- | --- |\n"
                "| 一 | long-long-long-long-long-long-long-long |\n\n"
                "```ts\nconst answer = 42;\n```"
            )
            await stream_sink.publish_content(answer)
            return answer

        await stream_sink.publish_content("确定性")
        await stream_sink.publish_tool_activity(
            activity_id=f"tool-{turn.id}", tool_name="lookup_fixture", state="started"
        )
        await asyncio.sleep(0.1)
        await stream_sink.publish_tool_activity(
            activity_id=f"tool-{turn.id}", tool_name="lookup_fixture", state="completed"
        )
        await asyncio.sleep(0.3)
        await stream_sink.publish_content("回答")
        return "确定性回答"


def worker_main(dsn: str) -> None:
    async def loop() -> None:
        store = PostgresTurnStore(dsn)
        worker = TurnWorker(
            store=store,
            runner=DeterministicRunner(),
            poll_interval=0.05,
            heartbeat_interval=0.1,
            flush_characters=1,
            flush_interval=0.01,
        )
        try:
            while True:
                if not await worker.run_once():
                    await asyncio.sleep(0.05)
        finally:
            store.close()

    asyncio.run(loop())


def main() -> None:
    dsn = prepare_database()
    sessions = PostgresSessionStore(dsn)
    turns = PostgresTurnStore(dsn)
    threading.Thread(target=worker_main, args=(dsn,), daemon=True).start()
    app = create_app(
        store=turns,
        session_store=sessions,
        owner_user_id=OWNER_USER_ID,
        static_dir=ROOT / "frontend" / "dist",
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("AMADEUS_E2E_PORT", "18001")),
        log_level="warning",
    )


def prepare_database() -> str:
    base_dsn = os.environ.get(
        "AMADEUS_POSTGRES_DSN",
        "postgresql://amadeus:amadeus@localhost:5432/amadeus",
    )
    admin_dsn = database_dsn(base_dsn, "postgres")
    with psycopg.connect(admin_dsn, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (E2E_DATABASE,)
            )
            if cursor.fetchone() is None:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(E2E_DATABASE))
                )
    e2e_dsn = database_dsn(base_dsn, E2E_DATABASE)
    os.environ["AMADEUS_POSTGRES_DSN"] = e2e_dsn
    alembic = Config(str(ROOT / "alembic.ini"))
    alembic.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(alembic, "head")
    with psycopg.connect(e2e_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE
                    memory_markdown_state,
                    memory_markdown_writes,
                    memory_replacements,
                    memory_items,
                    conversation_turn_events,
                    conversation_turns,
                    conversation_messages,
                    conversation_sessions,
                    users
                RESTART IDENTITY CASCADE
                """
            )
    return e2e_dsn


def database_dsn(base_dsn: str, database: str) -> str:
    parsed = urlsplit(base_dsn)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.netloc:
        raise RuntimeError(
            "Playwright requires AMADEUS_POSTGRES_DSN as a PostgreSQL URL"
        )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, f"/{database}", parsed.query, parsed.fragment)
    )


if __name__ == "__main__":
    main()
