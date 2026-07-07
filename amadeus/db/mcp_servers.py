from __future__ import annotations

# ruff: noqa: I001
# McpServerConfig 用 TYPE_CHECKING + 延迟 import 避免模块级触发 amadeus.mcp
# 包初始化（amadeus.mcp.__init__ → tools.base → tools.defaults → session.store
# 会与 memory 包形成预存在循环 import）。

import json
from typing import TYPE_CHECKING, Any

from amadeus.db.postgres import PostgresDatabase

if TYPE_CHECKING:
    from amadeus.mcp.config import McpServerConfig


class McpServersStore:
    """mcp_servers 表的 CRUD（postgres 持久化，MD3）。

    McpServerRegistry 内存跟踪 active 连接，本 store 负责 server 配置
    的持久化与启动时加载。

    McpServerConfig 用延迟 import 避免在模块级触发 amadeus.mcp 包初始化
    （amadeus.mcp.__init__ → tools.base → tools.defaults → session.store
    会与 memory 包形成预存在循环 import）。
    """

    def __init__(self, db: PostgresDatabase) -> None:
        self.db = db

    def upsert(self, config: McpServerConfig, *, authorized: bool = True) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO mcp_servers
                        (name, transport_type, command, url, env, cwd, headers,
                         authorized, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (name) DO UPDATE SET
                        transport_type = EXCLUDED.transport_type,
                        command = EXCLUDED.command,
                        url = EXCLUDED.url,
                        env = EXCLUDED.env,
                        cwd = EXCLUDED.cwd,
                        headers = EXCLUDED.headers,
                        authorized = EXCLUDED.authorized,
                        updated_at = now()
                    """,
                    (
                        config.name,
                        config.transport_type,
                        json.dumps(config.command) if config.command else None,
                        config.url,
                        json.dumps(config.env) if config.env else None,
                        config.cwd,
                        json.dumps(config.headers) if config.headers else None,
                        authorized,
                    ),
                )
            conn.commit()

    def delete(self, name: str) -> None:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM mcp_servers WHERE name = %s",
                    (name,),
                )
            conn.commit()

    def list_all(self) -> list[McpServerConfig]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT name, transport_type, command, url, env, cwd,
                           headers, authorized
                    FROM mcp_servers
                    ORDER BY name
                    """
                )
                rows = cursor.fetchall()
        return [self._row_to_config(row) for row in rows]

    def list_authorized(self) -> list[McpServerConfig]:
        with self.db.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT name, transport_type, command, url, env, cwd,
                           headers, authorized
                    FROM mcp_servers
                    WHERE authorized = TRUE
                    ORDER BY name
                    """
                )
                rows = cursor.fetchall()
        return [self._row_to_config(row) for row in rows]

    @staticmethod
    def _row_to_config(row: dict[str, Any]) -> McpServerConfig:
        from amadeus.mcp.config import McpServerConfig

        command = row.get("command")
        env = row.get("env")
        headers = row.get("headers")
        return McpServerConfig(
            name=row["name"],
            transport_type=row["transport_type"],  # type: ignore[arg-type]
            command=json.loads(command) if isinstance(command, str) else command,
            url=row.get("url"),
            env=json.loads(env) if isinstance(env, str) else env,
            cwd=row.get("cwd"),
            headers=json.loads(headers) if isinstance(headers, str) else headers,
        )