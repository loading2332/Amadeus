from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest
from amadeus.phase import Phase, PhaseFrame, inspect_phase, topo_sort_modules


@dataclass
class _TextFrame(PhaseFrame[str, str]):
    pass


class _PrepareText:
    slot = "test.prepare"
    produces = ("text:value",)

    async def run(self, frame: _TextFrame) -> _TextFrame:
        frame.slots["text:value"] = f"prepared:{frame.input}"
        return frame


class _ReturnText:
    slot = "test.return"
    requires = ("test.prepare", "text:value")

    async def run(self, frame: _TextFrame) -> _TextFrame:
        frame.output = str(frame.slots["text:value"])
        return frame


def test_phase_modules_share_frame_and_produce_output() -> None:
    phase = Phase[str, str, _TextFrame](
        [_PrepareText(), _ReturnText()],
        frame_factory=_TextFrame,
    )

    result = asyncio.run(phase.run("hello"))

    assert result == "prepared:hello"


class _OrderedModule:
    def __init__(self, slot: str, requires: tuple[str, ...] = ()) -> None:
        self.slot = slot
        self.requires = requires


def test_topo_sort_orders_module_dependencies() -> None:
    prepare = _OrderedModule("before_turn.prepare")
    build = _OrderedModule("before_turn.build", ("before_turn.prepare",))
    emit = _OrderedModule("before_turn.emit", ("before_turn.build",))

    result = topo_sort_modules([emit, build, prepare])

    assert [module.slot for module in result] == [
        "before_turn.prepare",
        "before_turn.build",
        "before_turn.emit",
    ]


def test_data_slot_does_not_create_topological_edge() -> None:
    consumer = _OrderedModule("before_turn.consumer", ("session:value",))
    producer = _OrderedModule("before_turn.producer")

    result = topo_sort_modules([consumer, producer])

    assert [module.slot for module in result] == [
        "before_turn.consumer",
        "before_turn.producer",
    ]


def test_ready_plugin_module_runs_before_ready_builtin() -> None:
    acquire = _OrderedModule("before_turn.acquire_session")
    prepare = _OrderedModule(
        "before_turn.prepare_context",
        ("before_turn.acquire_session",),
    )
    plugin = _OrderedModule("plugin.marker", ("before_turn.acquire_session",))

    result = topo_sort_modules([acquire, prepare, plugin])

    assert [module.slot for module in result] == [
        "before_turn.acquire_session",
        "plugin.marker",
        "before_turn.prepare_context",
    ]


def test_missing_plugin_dependency_disables_downstream_recursively(
    caplog: pytest.LogCaptureFixture,
) -> None:
    consumer = _OrderedModule("plugin.consumer", ("plugin.missing",))
    downstream = _OrderedModule("plugin.downstream", ("plugin.consumer",))

    with caplog.at_level("WARNING", logger="amadeus.phase"):
        result = topo_sort_modules([consumer, downstream])

    assert result == []
    assert "plugin.consumer" in caplog.text
    assert "plugin.downstream" in caplog.text


class _NeedsMissingData:
    slot = "before_turn.needs_data"
    requires = ("session:missing",)

    async def run(self, frame: _TextFrame) -> _TextFrame:
        frame.output = frame.input
        return frame


def test_phase_warns_when_data_slot_is_not_closed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="amadeus.phase"):
        Phase[str, str, _TextFrame](
            [_NeedsMissingData()],
            frame_factory=_TextFrame,
        )

    assert "Phase slot 未闭合" in caplog.text
    assert "session:missing" in caplog.text


def test_inspect_phase_reports_order_dependencies_and_contracts() -> None:
    prepare = _OrderedModule("before_turn.prepare")
    prepare.produces = ("session:value",)
    plugin = _OrderedModule(
        "plugin.marker",
        ("before_turn.prepare", "session:value"),
    )
    plugin.produces = ("session:marked",)

    report = inspect_phase([plugin, prepare])

    assert "执行顺序" in report
    assert "before_turn.prepare" in report
    assert "plugin.marker" in report
    assert "requires: before_turn.prepare, session:value" in report
    assert "produces: session:marked" in report


@pytest.mark.parametrize(
    ("modules", "message"),
    [
        ([object()], "模块缺少 slot 声明"),
        (
            [_OrderedModule("plugin.same"), _OrderedModule("plugin.same")],
            "模块 slot 重复",
        ),
        (
            [
                _OrderedModule("plugin.a", ("plugin.b",)),
                _OrderedModule("plugin.b", ("plugin.a",)),
            ],
            "模块循环依赖",
        ),
    ],
)
def test_topo_sort_rejects_invalid_graphs(
    modules: list[object],
    message: str,
) -> None:
    with pytest.raises(RuntimeError, match=message):
        topo_sort_modules(modules)


class _FailingModule:
    slot = "test.fail"

    async def run(self, frame: _TextFrame) -> _TextFrame:
        raise ValueError("module exploded")


def test_phase_propagates_module_exception() -> None:
    phase = Phase[str, str, _TextFrame](
        [_FailingModule()],
        frame_factory=_TextFrame,
    )

    with pytest.raises(ValueError, match="module exploded"):
        asyncio.run(phase.run("hello"))


class _NoOutputModule:
    slot = "test.no_output"

    async def run(self, frame: _TextFrame) -> _TextFrame:
        return frame


def test_phase_rejects_chain_without_output() -> None:
    phase = Phase[str, str, _TextFrame](
        [_NoOutputModule()],
        frame_factory=_TextFrame,
    )

    with pytest.raises(RuntimeError, match="Phase 模块链未产生 output"):
        asyncio.run(phase.run("hello"))
