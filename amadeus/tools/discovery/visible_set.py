from __future__ import annotations

from collections import OrderedDict


class TurnVisibleSet:
    """本轮可见工具集：always_on ∪ 本轮已解锁。

    与 ToolDiscoveryState 区分：本轮集每 turn 重建，跨轮缓存由
    ToolDiscoveryState 管。reasoner 只负责"什么时候调它们的什么方法"，
    不再自己维护 set.update。
    """

    def __init__(
        self,
        always_on: set[str],
        discovery_state: ToolDiscoveryState,
    ) -> None:
        self._always_on = set(always_on)
        self._discovery = discovery_state
        self._unlocked: set[str] = set()

    def is_visible(self, name: str) -> bool:
        return name in self._always_on or name in self._unlocked

    def add_unlocked(self, name: str) -> None:
        if name and not self.is_visible(name):
            self._unlocked.add(name)
            self._discovery.remember(name)

    def visible_names(self) -> set[str]:
        return self._always_on | self._unlocked

    def consume_unlock_targets(self, tool_search_result_text: str) -> list[str]:
        """解析 tool_search 返回的 JSON 里的工具名（select: 即解锁单个，
        普通 search 返回候选可按 always_on=False 阈值考虑解锁候选，本实现保守只把
        action=='select' 的结果里的工具名加入解锁集）。"""
        import json

        try:
            payload = json.loads(tool_search_result_text)
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(payload, list):
            # 兼容 output 形态——如果直接传的是 list
            if isinstance(tool_search_result_text, list):
                payload = tool_search_result_text
            else:
                return []
        unlocked: list[str] = []
        for entry in payload:
            if isinstance(entry, dict) and "name" in entry:
                name = entry["name"]
                if name and not self.is_visible(name):
                    self._unlocked.add(name)
                    self._discovery.remember(name)
                    unlocked.append(name)
        return unlocked


class ToolDiscoveryState:
    """session 级 LRU 缓存：跨轮"上个 session 解锁过啥"。

    新 turn 开始时用 warm_up 给 TurnVisibleSet 垫底，避免每次都从头搜。
    容量 64 是 design 默认值，可在装配时配置。
    """

    def __init__(self, capacity: int = 64) -> None:
        self._capacity = capacity
        self._cache: OrderedDict[str, None] = OrderedDict()

    def warm_up(self, visible_set: TurnVisibleSet) -> None:
        """新 turn 开始用 LRU 内容给本轮集垫底。"""
        for name in list(self._cache.keys()):
            visible_set.add_unlocked(name)

    def remember(self, name: str) -> None:
        if name in self._cache:
            self._cache.move_to_end(name)
        else:
            self._cache[name] = None
            if len(self._cache) > self._capacity:
                self._cache.popitem(last=False)

    def __contains__(self, name: str) -> bool:
        return name in self._cache

    def __len__(self) -> int:
        return len(self._cache)