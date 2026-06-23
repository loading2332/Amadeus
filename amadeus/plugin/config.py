from __future__ import annotations

from typing import Any


class PluginConfig:
    """Read-only-style access to a snapshot of plugin configuration values."""

    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values.copy()

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return self._values.copy()

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(name) from None
