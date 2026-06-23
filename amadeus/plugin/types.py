from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PluginLoadStatus(str, Enum):  # noqa: UP042
    """Stable outcome values exposed by plugin discovery and loading."""

    LOADED = "loaded"
    DISABLED = "disabled"
    DUPLICATE = "duplicate"
    ALREADY_LOADED = "already_loaded"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginCandidate:
    """A plugin module discovered on disk but not imported yet."""

    name: str
    source: str
    plugin_dir: Path
    module_path: Path
    import_path: str


@dataclass(frozen=True)
class PluginLoadRecord:
    """One safe, structured discovery or load outcome."""

    name: str
    source: str
    import_path: str
    status: PluginLoadStatus
    stage: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class PluginDiscoveryResult:
    """Immutable discovery snapshot and any records produced while scanning."""

    candidates: tuple[PluginCandidate, ...]
    records: tuple[PluginLoadRecord, ...]


@dataclass(frozen=True)
class PluginLoadReport:
    """Immutable load outcomes with order-preserving status views."""

    records: tuple[PluginLoadRecord, ...]

    def _with_status(
        self,
        status: PluginLoadStatus,
    ) -> tuple[PluginLoadRecord, ...]:
        return tuple(record for record in self.records if record.status is status)

    @property
    def loaded(self) -> tuple[PluginLoadRecord, ...]:
        return self._with_status(PluginLoadStatus.LOADED)

    @property
    def failed(self) -> tuple[PluginLoadRecord, ...]:
        return self._with_status(PluginLoadStatus.FAILED)

    @property
    def disabled(self) -> tuple[PluginLoadRecord, ...]:
        return self._with_status(PluginLoadStatus.DISABLED)

    @property
    def duplicate(self) -> tuple[PluginLoadRecord, ...]:
        return self._with_status(PluginLoadStatus.DUPLICATE)

    @property
    def already_loaded(self) -> tuple[PluginLoadRecord, ...]:
        return self._with_status(PluginLoadStatus.ALREADY_LOADED)
