from __future__ import annotations

import json
from typing import Any

from amadeus.db.mcp_servers import McpServersStore
from amadeus.mcp.config import McpServerConfig


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = rows or []
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._cursor = FakeCursor(rows=rows)
        self.committed = False

    def cursor(self) -> FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class FakeDb:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._conn = FakeConnection(rows=rows)

    def connection(self) -> FakeConnection:
        return self._conn


def test_upsert_inserts_with_jsonb_columns():
    db = FakeDb()
    store = McpServersStore(db=db)  # type: ignore[arg-type]
    config = McpServerConfig(
        name="github",
        transport_type="stdio",
        command=["npx", "mcp-server-github"],
        env={"TOKEN": "x"},
    )

    store.upsert(config)

    query, params = db._conn._cursor.executed[0]
    assert "INSERT INTO mcp_servers" in query
    assert "ON CONFLICT (name) DO UPDATE" in query
    assert params[0] == "github"
    assert params[1] == "stdio"
    assert json.loads(params[2]) == ["npx", "mcp-server-github"]
    assert params[3] is None  # url
    assert json.loads(params[4]) == {"TOKEN": "x"}
    assert db._conn.committed is True


def test_delete_executes_delete_query():
    db = FakeDb()
    store = McpServersStore(db=db)  # type: ignore[arg-type]

    store.delete("github")

    query, params = db._conn._cursor.executed[0]
    assert "DELETE FROM mcp_servers" in query
    assert params == ("github",)


def test_list_authorized_maps_rows_to_configs():
    rows = [
        {
            "name": "github",
            "transport_type": "stdio",
            "command": json.dumps(["npx", "-y", "mcp-server-github"]),
            "url": None,
            "env": json.dumps({"TOKEN": "t"}),
            "cwd": None,
            "headers": None,
            "authorized": True,
        },
        {
            "name": "remote",
            "transport_type": "http",
            "command": None,
            "url": "https://srv.test/mcp",
            "env": None,
            "cwd": None,
            "headers": json.dumps({"Authorization": "Bearer x"}),
            "authorized": True,
        },
    ]
    db = FakeDb(rows=rows)
    store = McpServersStore(db=db)  # type: ignore[arg-type]

    configs = store.list_authorized()

    assert len(configs) == 2
    assert configs[0].name == "github"
    assert configs[0].command == ["npx", "-y", "mcp-server-github"]
    assert configs[0].env == {"TOKEN": "t"}
    assert configs[1].name == "remote"
    assert configs[1].url == "https://srv.test/mcp"
    assert configs[1].headers == {"Authorization": "Bearer x"}
    # list_authorized 查询带 WHERE authorized = TRUE
    query, _ = db._conn._cursor.executed[0]
    assert "authorized = TRUE" in query