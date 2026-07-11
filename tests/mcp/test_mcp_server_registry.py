from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from amadeus.mcp.client import McpCallResult, McpToolInfo
from amadeus.mcp.config import McpServerConfig
from amadeus.mcp.registry import (
    McpServerNotFoundError,
    McpServerRegistry,
    McpServerStatus,
)
from amadeus.tools.base import ToolResult
from amadeus.tools.registry import ToolRegistry

_VALID_TOOLS = [
    McpToolInfo(
        name="echo",
        description="Echo text",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    ),
    McpToolInfo(
        name="add",
        description="Add numbers",
        input_schema={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    ),
]


class _FakeClient:
    def __init__(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        *,
        tool_infos: list[McpToolInfo] | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.env = env
        self.cwd = cwd
        self.tool_infos = list(_VALID_TOOLS if tool_infos is None else tool_infos)
        self.connect_calls = 0
        self.disconnect_calls = 0
        self._is_alive = False

    @property
    def is_alive(self) -> bool:
        return self._is_alive

    async def connect(self) -> list[McpToolInfo]:
        self.connect_calls += 1
        self._is_alive = True
        return list(self.tool_infos)

    async def call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> McpCallResult:
        del timeout
        return McpCallResult(
            content=[{"type": "text", "text": f"{tool_name}:{arguments}"}],
            structured_content=None,
            is_error=False,
        )

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self._is_alive = False


class _ClientFactory:
    def __init__(
        self,
        tool_infos: list[McpToolInfo] | None = None,
        *,
        builder: Callable[..., _FakeClient] | None = None,
    ) -> None:
        self.tool_infos = tool_infos
        self.builder = builder
        self.instances: list[_FakeClient] = []

    def __call__(
        self,
        name: str,
        command: list[str],
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> _FakeClient:
        if self.builder is None:
            client = _FakeClient(
                name,
                command,
                env,
                cwd,
                tool_infos=self.tool_infos,
            )
        else:
            client = self.builder(name, command, env, cwd)
        self.instances.append(client)
        return client


def _install_client_factory(monkeypatch: pytest.MonkeyPatch, factory: _ClientFactory) -> None:
    monkeypatch.setattr("amadeus.mcp.registry.McpClient", factory)


def _config(name: str = "fake") -> McpServerConfig:
    return McpServerConfig(
        name=name,
        command=["fake-mcp-server", name],
        env={"SERVER_ONLY": name},
        cwd="workspace",
    )


def test_add_registers_wrappers_with_deferred_mcp_metadata(
    monkeypatch: pytest.MonkeyPatch,
):
    factory = _ClientFactory()
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> tuple[
        list[str],
        list[tuple[str, list[str]]],
        dict[str, object],
    ]:
        try:
            registered, skipped = await servers.add(_config())
            metadata = {
                name: tools.get_metadata(name)
                for name in registered
            }
            return registered, skipped, metadata
        finally:
            await servers.shutdown()

    registered, skipped, metadata_by_name = asyncio.run(run())

    assert registered == ["mcp_fake__echo", "mcp_fake__add"]
    assert skipped == []
    assert factory.instances[0].command == ["fake-mcp-server", "fake"]
    assert factory.instances[0].env == {"SERVER_ONLY": "fake"}
    assert factory.instances[0].cwd == "workspace"
    for name in registered:
        metadata = metadata_by_name[name]
        assert metadata is not None
        assert metadata.source_type == "mcp"
        assert metadata.source_name == "fake"
        assert metadata.risk == "external-side-effect"
        assert metadata.always_on is False


def test_add_skips_only_tools_with_invalid_schema(
    monkeypatch: pytest.MonkeyPatch,
):
    bad = McpToolInfo(
        name="bad",
        description="unsupported schema",
        input_schema={"type": "object", "$ref": "#/$defs/Input"},
    )
    factory = _ClientFactory([_VALID_TOOLS[0], bad])
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> tuple[list[str], list[tuple[str, list[str]]]]:
        try:
            return await servers.add(_config())
        finally:
            await servers.shutdown()

    registered, skipped = asyncio.run(run())

    assert registered == ["mcp_fake__echo"]
    assert len(skipped) == 1
    assert skipped[0][0] == "bad"
    assert any("$ref" in message for message in skipped[0][1])
    assert tools.get("mcp_fake__bad") is None


def test_add_with_zero_valid_tools_rolls_back_client_and_server_state(
    monkeypatch: pytest.MonkeyPatch,
):
    factory = _ClientFactory(
        [
            McpToolInfo(
                name="bad",
                description="unsupported schema",
                input_schema={"type": "string"},
            )
        ]
    )
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> None:
        with pytest.raises(ValueError):
            await servers.add(_config())

    asyncio.run(run())

    assert tools.get_registered_names() == set()
    assert servers.list_servers() == []
    assert len(factory.instances) == 1
    assert factory.instances[0].disconnect_calls == 1


@dataclass
class _ExistingTool:
    name: str
    description: str = "existing"
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(tool_name=self.name, output=kwargs)


def test_add_name_collision_rolls_back_without_replacing_existing_tool(
    monkeypatch: pytest.MonkeyPatch,
):
    factory = _ClientFactory()
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    existing = _ExistingTool(name="mcp_fake__echo")
    tools.register(existing)
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> None:
        with pytest.raises(ValueError):
            await servers.add(_config())

    asyncio.run(run())

    assert tools.get("mcp_fake__echo") is existing
    assert tools.get("mcp_fake__add") is None
    assert servers.list_servers() == []
    assert factory.instances[0].disconnect_calls == 1


def test_concurrent_adds_with_same_name_publish_exactly_one_server(
    monkeypatch: pytest.MonkeyPatch,
):
    async def run() -> tuple[list[object], _ClientFactory, list[str]]:
        connect_started = asyncio.Event()
        connect_release = asyncio.Event()

        class _SlowConnectClient(_FakeClient):
            async def connect(self) -> list[McpToolInfo]:
                connect_started.set()
                await connect_release.wait()
                return await super().connect()

        factory = _ClientFactory(builder=_SlowConnectClient)
        _install_client_factory(monkeypatch, factory)
        servers = McpServerRegistry(tool_registry=ToolRegistry())
        first = asyncio.create_task(servers.add(_config()))
        await connect_started.wait()
        second = asyncio.create_task(servers.add(_config()))
        await asyncio.sleep(0)
        connect_release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        published_names = [status.name for status in servers.list_servers()]
        await servers.shutdown()
        return results, factory, published_names

    results, factory, published_names = asyncio.run(run())
    successes = [result for result in results if isinstance(result, tuple)]
    failures = [result for result in results if isinstance(result, Exception)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], ValueError)
    assert len(factory.instances) == 1
    assert published_names == ["fake"]


def test_shutdown_waits_for_in_flight_add_and_prevents_late_publish(
    monkeypatch: pytest.MonkeyPatch,
):
    async def run() -> tuple[object, ToolRegistry, McpServerRegistry, _FakeClient]:
        connect_started = asyncio.Event()
        connect_release = asyncio.Event()

        class _SlowConnectClient(_FakeClient):
            async def connect(self) -> list[McpToolInfo]:
                connect_started.set()
                await connect_release.wait()
                return await super().connect()

        factory = _ClientFactory(builder=_SlowConnectClient)
        _install_client_factory(monkeypatch, factory)
        tools = ToolRegistry()
        servers = McpServerRegistry(tool_registry=tools)
        add_task = asyncio.create_task(servers.add(_config("race")))
        await connect_started.wait()
        shutdown_task = asyncio.create_task(servers.shutdown())
        await asyncio.sleep(0)
        assert not shutdown_task.done()
        connect_release.set()
        add_result = (await asyncio.gather(add_task, return_exceptions=True))[0]
        await shutdown_task
        return add_result, tools, servers, factory.instances[0]

    add_result, tools, servers, client = asyncio.run(run())

    assert isinstance(add_result, RuntimeError)
    assert tools.get_registered_names() == set()
    assert servers.list_servers() == []
    assert client.disconnect_calls == 1


def test_config_and_registry_repr_do_not_expose_credentials(
    monkeypatch: pytest.MonkeyPatch,
):
    secret = "SECRET_VALUE_MUST_NOT_APPEAR"
    config = McpServerConfig(
        name="safe",
        command=["server", "--token", secret],
        env={"TOKEN": secret},
        cwd=f"workspace/{secret}",
    )
    factory = _ClientFactory()
    _install_client_factory(monkeypatch, factory)
    servers = McpServerRegistry(tool_registry=ToolRegistry())

    async def run() -> str:
        try:
            await servers.add(config)
            return repr(servers)
        finally:
            await servers.shutdown()

    registry_repr = asyncio.run(run())

    assert secret not in repr(config)
    assert secret not in registry_repr


def test_remove_unregisters_first_then_waits_for_in_flight_call(
    monkeypatch: pytest.MonkeyPatch,
):
    async def run() -> tuple[list[str], ToolRegistry, _FakeClient]:
        call_started = asyncio.Event()
        call_release = asyncio.Event()
        call_finished = asyncio.Event()
        disconnect_started = asyncio.Event()

        class _BlockingClient(_FakeClient):
            async def call(
                self,
                tool_name: str,
                arguments: dict[str, Any],
                *,
                timeout: float | None = None,
            ) -> McpCallResult:
                del tool_name, arguments, timeout
                call_started.set()
                try:
                    await call_release.wait()
                finally:
                    call_finished.set()
                return McpCallResult(
                    content=[{"type": "text", "text": "finished"}],
                    structured_content=None,
                    is_error=False,
                )

            async def disconnect(self) -> None:
                disconnect_started.set()
                await call_finished.wait()
                await super().disconnect()

        factory = _ClientFactory(builder=_BlockingClient)
        _install_client_factory(monkeypatch, factory)
        tools = ToolRegistry()
        servers = McpServerRegistry(tool_registry=tools)
        await servers.add(_config())
        wrapper = tools.get("mcp_fake__echo")
        assert wrapper is not None
        call_task = asyncio.create_task(wrapper.execute(text="hello"))
        await call_started.wait()
        remove_task = asyncio.create_task(servers.remove("fake"))
        await disconnect_started.wait()

        assert tools.get("mcp_fake__echo") is None
        assert tools.get("mcp_fake__add") is None
        assert not remove_task.done()

        call_release.set()
        await call_task
        removed = await remove_task
        return removed, tools, factory.instances[0]

    removed, tools, client = asyncio.run(run())

    assert removed == ["mcp_fake__echo", "mcp_fake__add"]
    assert tools.get_registered_names() == set()
    assert client.disconnect_calls == 1


def test_list_servers_projects_live_connected_or_disconnected_status(
    monkeypatch: pytest.MonkeyPatch,
):
    factory = _ClientFactory()
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> tuple[McpServerStatus, McpServerStatus, bool]:
        await servers.add(_config())
        connected = servers.list_servers()[0]
        factory.instances[0]._is_alive = False
        disconnected = servers.list_servers()[0]
        wrapper_retained = tools.get("mcp_fake__echo") is not None
        await servers.shutdown()
        return connected, disconnected, wrapper_retained

    connected, disconnected, wrapper_retained = asyncio.run(run())
    assert connected.name == "fake"
    assert connected.status == "connected"
    assert connected.tools == ("mcp_fake__echo", "mcp_fake__add")
    assert disconnected.status == "disconnected"
    assert wrapper_retained is True


def test_remove_unknown_server_is_a_domain_error():
    servers = McpServerRegistry(tool_registry=ToolRegistry())

    async def run() -> None:
        with pytest.raises(McpServerNotFoundError):
            await servers.remove("missing")

    asyncio.run(run())


def test_remove_failure_keeps_client_owned_for_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    class _RetryDisconnectClient(_FakeClient):
        async def disconnect(self) -> None:
            self.disconnect_calls += 1
            if self.disconnect_calls == 1:
                raise OSError("temporary close failure")
            self._is_alive = False

    factory = _ClientFactory(builder=_RetryDisconnectClient)
    _install_client_factory(monkeypatch, factory)
    tools = ToolRegistry()
    servers = McpServerRegistry(tool_registry=tools)

    async def run() -> tuple[McpServerStatus, list[str]]:
        await servers.add(_config())
        with pytest.raises(OSError, match="close failure"):
            await servers.remove("fake")
        status_after_failure = servers.list_servers()[0]
        removed = await servers.remove("fake")
        return status_after_failure, removed

    status, removed = asyncio.run(run())

    assert status.status == "disconnected"
    assert status.tools == ()
    assert removed == ["mcp_fake__echo", "mcp_fake__add"]
    assert servers.list_servers() == []
    assert factory.instances[0].disconnect_calls == 2


def test_shutdown_disconnects_different_servers_in_parallel_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
):
    async def run() -> tuple[ToolRegistry, _ClientFactory, McpServerRegistry]:
        disconnect_started: set[str] = set()
        both_started = asyncio.Event()
        disconnect_release = asyncio.Event()

        class _BlockingDisconnectClient(_FakeClient):
            async def disconnect(self) -> None:
                disconnect_started.add(self.name)
                if disconnect_started == {"one", "two"}:
                    both_started.set()
                await disconnect_release.wait()
                await super().disconnect()

        factory = _ClientFactory(builder=_BlockingDisconnectClient)
        _install_client_factory(monkeypatch, factory)
        tools = ToolRegistry()
        servers = McpServerRegistry(tool_registry=tools)
        await servers.add(_config("one"))
        await servers.add(_config("two"))

        shutdown_task = asyncio.create_task(servers.shutdown())
        await asyncio.wait_for(both_started.wait(), timeout=1.0)
        assert tools.get_registered_names() == set()
        assert not shutdown_task.done()
        disconnect_release.set()
        await shutdown_task
        await servers.shutdown()
        return tools, factory, servers

    tools, factory, servers = asyncio.run(run())

    assert tools.get_registered_names() == set()
    assert servers.list_servers() == []
    assert [client.disconnect_calls for client in factory.instances] == [1, 1]
