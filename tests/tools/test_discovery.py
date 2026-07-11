from __future__ import annotations

from amadeus.session.identity import SessionRef
from amadeus.tools.discovery.visible_set import (
    SessionToolDiscoveryStore,
    ToolDiscoveryState,
    TurnVisibleSet,
)


def test_always_on_tools_always_visible():
    discovery = ToolDiscoveryState()
    visible = TurnVisibleSet(always_on={"tool_search", "memory_recall"}, discovery_state=discovery)

    assert visible.is_visible("tool_search") is True
    assert visible.is_visible("memory_recall") is True
    assert visible.is_visible("unknown") is False


def test_add_unlocked_extends_visible_set():
    discovery = ToolDiscoveryState()
    visible = TurnVisibleSet(always_on=set(), discovery_state=discovery)

    visible.add_unlocked("read_file")

    assert visible.is_visible("read_file") is True
    assert visible.visible_names() == {"read_file"}


def test_add_unlocked_also_remembers_in_discovery_state():
    discovery = ToolDiscoveryState()
    visible = TurnVisibleSet(always_on=set(), discovery_state=discovery)

    visible.add_unlocked("read_file")

    assert "read_file" in discovery


def test_consume_unlock_targets_parses_json_list_of_names():
    import json

    discovery = ToolDiscoveryState()
    visible = TurnVisibleSet(always_on=set(), discovery_state=discovery)

    payload = json.dumps([{"name": "read_file"}, {"name": "write_file"}])
    unlocked = visible.consume_unlock_targets(payload)

    assert unlocked == ["read_file", "write_file"]
    assert visible.is_visible("read_file")
    assert visible.is_visible("write_file")


def test_consume_unlock_targets_skips_already_visible():
    import json

    discovery = ToolDiscoveryState()
    visible = TurnVisibleSet(always_on={"tool_search"}, discovery_state=discovery)

    payload = json.dumps([{"name": "tool_search"}, {"name": "read_file"}])
    unlocked = visible.consume_unlock_targets(payload)

    # tool_search 已 always_on，不算新解锁
    assert unlocked == ["read_file"]


def test_discovery_state_lru_capacity():
    state = ToolDiscoveryState(capacity=3)
    for name in ["a", "b", "c"]:
        state.remember(name)
    state.remember("d")  # 超容量，a 应被淘汰

    assert "a" not in state
    assert "d" in state
    assert len(state) == 3


def test_discovery_state_warm_up_seeds_visible_set():
    state = ToolDiscoveryState()
    state.remember("read_file")
    state.remember("write_file")

    visible = TurnVisibleSet(always_on=set(), discovery_state=state)
    state.warm_up(visible)

    assert visible.is_visible("read_file")
    assert visible.is_visible("write_file")


def test_discovery_state_remember_moves_to_end_on_repeat():
    state = ToolDiscoveryState(capacity=2)
    state.remember("a")
    state.remember("b")
    state.remember("a")  # a 移到末尾

    # 现在 a 是最新，再添 c 应淘汰 b（最旧）
    state.remember("c")
    assert "b" not in state
    assert "a" in state


def test_session_discovery_store_isolates_sessions_and_evicts_lru_session():
    store = SessionToolDiscoveryStore(session_capacity=2, tool_capacity=3)
    first = SessionRef(user_id=1, session_id=1)
    second = SessionRef(user_id=1, session_id=2)
    third = SessionRef(user_id=1, session_id=3)

    store.for_session(first).remember("read_file")
    assert "read_file" not in store.for_session(second)
    store.for_session(third)

    assert len(store) == 2
    assert "read_file" not in store.for_session(first)
