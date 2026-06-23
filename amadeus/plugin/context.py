from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from amadeus.events import EventBus
from amadeus.memory_engine import MemoryEngine
from amadeus.plugin.config import PluginConfig
from amadeus.session import SessionManager
from amadeus.tools.registry import ToolRegistry


@dataclass
class PluginContext:
    """Runtime services and plugin-scoped state injected into a plugin."""

    event_bus: EventBus
    tool_registry: ToolRegistry
    plugin_id: str
    plugin_dir: Path
    kv_store: PluginKVStore
    config: PluginConfig | None = None
    workspace: Path | None = None
    session_manager: SessionManager | None = None
    memory_engine: MemoryEngine | None = None


class PluginKVStore:
    """Small JSON-object store scoped to a plugin directory."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, key: str, default: Any = None) -> Any:
        return self._read().get(key, default)

    def set(self, key: str, value: Any) -> None:
        values = self._read()
        values[key] = value
        self._write(values)

    def increment(self, key: str, delta: int = 1) -> Any:
        values = self._read()
        value = values.get(key, 0) + delta
        values[key] = value
        self._write(values)
        return value

    def _read(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}

        values = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(values, dict):
            raise ValueError("Plugin KV JSON must be a JSON object")
        return values

    def _write(self, values: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(values, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
