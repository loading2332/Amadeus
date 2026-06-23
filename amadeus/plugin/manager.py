from __future__ import annotations

import asyncio
import functools
import hashlib
import importlib.util
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, cast

import yaml

from amadeus.events import EventBus
from amadeus.lifecycle import AfterTurnContext, BeforeTurnContext, PromptRenderContext
from amadeus.memory_engine import MemoryEngine
from amadeus.plugin.base import Plugin
from amadeus.plugin.config import PluginConfig
from amadeus.plugin.context import PluginContext, PluginKVStore
from amadeus.plugin.registry import MetadataKind, PluginEventType, plugin_registry
from amadeus.plugin.types import (
    PluginCandidate,
    PluginDiscoveryResult,
    PluginLoadRecord,
    PluginLoadReport,
    PluginLoadStatus,
)
from amadeus.session import SessionManager
from amadeus.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_EVENT_TYPE_MAP: dict[PluginEventType, type[Any]] = {
    PluginEventType.BEFORE_TURN: BeforeTurnContext,
    PluginEventType.PROMPT_RENDER: PromptRenderContext,
    PluginEventType.AFTER_TURN: AfterTurnContext,
}
_MANIFEST_FIELDS = ("name", "version", "desc", "author")
_Binding = tuple[type[Any], Any]


class PluginManager:
    """Discover and load trusted plugins through an atomic host transaction."""

    def __init__(
        self,
        plugin_roots: list[tuple[str, Path]],
        event_bus: EventBus,
        tool_registry: ToolRegistry,
        workspace: Path,
        session_manager: SessionManager | None = None,
        memory_engine: MemoryEngine | None = None,
    ) -> None:
        self._plugin_roots = plugin_roots
        self._event_bus = event_bus
        self._tool_registry = tool_registry
        self._workspace = workspace
        self._session_manager = session_manager
        self._memory_engine = memory_engine
        self._loaded: set[str] = set()
        self._load_order: list[str] = []
        self._loaded_names: dict[str, str] = {}
        self._plugin_ids: dict[str, str] = {}
        self._bindings: dict[str, list[_Binding]] = {}
        self._owner_token = object()
        self._operation_lock = asyncio.Lock()

    def discover(self) -> PluginDiscoveryResult:
        """Describe candidates without reading manifests or executing code."""
        candidates: list[PluginCandidate] = []
        records: list[PluginLoadRecord] = []
        seen_names: set[str] = set()

        for source, root in self._plugin_roots:
            if not root.is_dir():
                continue
            for child in sorted(root.iterdir(), key=lambda path: path.name):
                if not child.is_dir():
                    continue
                module_path = child / "plugin.py"
                if not module_path.is_file():
                    continue
                import_path = _import_path(source, child.name, module_path)
                if child.name in seen_names:
                    records.append(
                        PluginLoadRecord(
                            name=child.name,
                            source=source,
                            import_path=import_path,
                            status=PluginLoadStatus.DUPLICATE,
                            message="duplicate directory name; first candidate retained",
                        )
                    )
                    logger.warning(
                        "plugin candidate skipped name=%s source=%s stage=duplicate",
                        child.name,
                        source,
                    )
                    continue
                seen_names.add(child.name)
                candidates.append(
                    PluginCandidate(
                        name=child.name,
                        source=source,
                        plugin_dir=child.resolve(),
                        module_path=module_path.resolve(),
                        import_path=import_path,
                    )
                )

        return PluginDiscoveryResult(tuple(candidates), tuple(records))

    async def load_all(self) -> PluginLoadReport:
        async with self._operation_lock:
            return await self._load_all()

    async def _load_all(self) -> PluginLoadReport:
        discovery = self.discover()
        records = list(discovery.records)
        for candidate in discovery.candidates:
            if candidate.import_path in self._loaded:
                records.append(self._record(candidate, PluginLoadStatus.ALREADY_LOADED))
                continue
            if (candidate.plugin_dir / "plugin.disabled").exists():
                records.append(self._record(candidate, PluginLoadStatus.DISABLED))
                continue
            records.append(await self._load_candidate(candidate))
        return PluginLoadReport(tuple(records))

    async def _load_candidate(self, candidate: PluginCandidate) -> PluginLoadRecord:
        stage = "ownership"
        instance: Plugin | None = None
        plugin_id: str | None = None
        owns_import_path = plugin_registry.claim_import_path(
            candidate.import_path, self._owner_token
        )
        if not owns_import_path:
            logger.warning(
                "plugin load failed name=%s source=%s stage=ownership",
                candidate.name,
                candidate.source,
            )
            return self._record(
                candidate,
                PluginLoadStatus.FAILED,
                stage="ownership",
                message="ownership failed (import path already in use)",
            )
        try:
            stage = "import"
            self._import_plugin(candidate)

            stage = "register"
            classes = plugin_registry.get_classes(candidate.import_path)
            if len(classes) != 1:
                raise RuntimeError("plugin class cardinality violation")
            plugin_class = classes[0]
            if not issubclass(plugin_class, Plugin):
                raise TypeError("registered class is not a Plugin")

            stage = "instantiate"
            instance = plugin_class()

            stage = "manifest"
            _apply_manifest(instance, candidate)

            stage = "identity"
            raw_name = instance.name
            plugin_id = str(raw_name) if raw_name else candidate.name
            owner = self._plugin_ids.get(plugin_id)
            if owner is not None and owner != candidate.import_path:
                raise RuntimeError("plugin id collision")

            stage = "config"
            config = _load_plugin_config(candidate)
            instance.context = PluginContext(
                event_bus=self._event_bus,
                tool_registry=self._tool_registry,
                plugin_id=plugin_id,
                plugin_dir=candidate.plugin_dir,
                kv_store=PluginKVStore(candidate.plugin_dir / ".kv.json"),
                config=config,
                workspace=self._workspace,
                session_manager=self._session_manager,
                memory_engine=self._memory_engine,
            )
            plugin_registry.register_instance(candidate.import_path, instance)

            stage = "bind"
            self._bind_handlers(instance, candidate.import_path)

            stage = "initialize"
            await instance.initialize()

            self._loaded.add(candidate.import_path)
            self._load_order.append(candidate.import_path)
            self._loaded_names[candidate.import_path] = candidate.name
            self._plugin_ids[plugin_id] = candidate.import_path
            logger.info(
                "plugin loaded name=%s source=%s", candidate.name, candidate.source
            )
            return self._record(candidate, PluginLoadStatus.LOADED)
        except asyncio.CancelledError:
            if owns_import_path:
                await self._cleanup_plugin(candidate.import_path, instance, plugin_id)
            raise
        except Exception as error:
            if owns_import_path:
                await self._cleanup_plugin(candidate.import_path, instance, plugin_id)
            error_type = type(error).__name__
            logger.warning(
                "plugin load failed name=%s source=%s stage=%s exception=%s frames=%s",
                candidate.name,
                candidate.source,
                stage,
                error_type,
                _safe_traceback(error),
            )
            return self._record(
                candidate,
                PluginLoadStatus.FAILED,
                stage=stage,
                message=f"{stage} failed ({error_type})",
            )

    def _import_plugin(self, candidate: PluginCandidate) -> None:
        spec = importlib.util.spec_from_file_location(
            candidate.import_path,
            candidate.module_path,
            submodule_search_locations=[str(candidate.plugin_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError("plugin module spec unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[candidate.import_path] = module
        spec.loader.exec_module(module)

    def _bind_handlers(self, instance: Plugin, import_path: str) -> None:
        ledger = self._bindings.setdefault(import_path, [])
        for metadata in plugin_registry.get_handlers_by_module_path(import_path):
            if metadata.kind is not MetadataKind.LIFECYCLE:
                continue
            context_type = _EVENT_TYPE_MAP.get(metadata.event_type)
            if context_type is None:
                continue
            bound = functools.partial(metadata.handler, instance)
            ledger.append((context_type, bound))
            self._event_bus.on(context_type, bound, priority=metadata.priority)

    async def _cleanup_plugin(
        self,
        import_path: str,
        instance: Plugin | None,
        plugin_id: str | None,
    ) -> None:
        if instance is not None:
            try:
                await instance.terminate()
            except Exception as error:
                logger.warning(
                    "plugin terminate failed import_path=%s exception=%s frames=%s",
                    import_path,
                    type(error).__name__,
                    _safe_traceback(error),
                )

        for event_type, handler in reversed(self._bindings.pop(import_path, [])):
            self._event_bus.off(event_type, handler)

        plugin_registry.remove_plugin_tree(import_path)
        for module_name in tuple(sys.modules):
            if module_name == import_path or module_name.startswith(f"{import_path}."):
                sys.modules.pop(module_name, None)

        self._loaded.discard(import_path)
        self._load_order = [path for path in self._load_order if path != import_path]
        self._loaded_names.pop(import_path, None)
        if plugin_id is not None and self._plugin_ids.get(plugin_id) == import_path:
            self._plugin_ids.pop(plugin_id, None)
        plugin_registry.release_import_path(import_path, self._owner_token)

    async def terminate_all(self) -> None:
        async with self._operation_lock:
            await self._terminate_all()

    async def _terminate_all(self) -> None:
        for import_path in reversed(tuple(self._load_order)):
            raw_instance = plugin_registry.get_instance(import_path)
            instance = raw_instance if isinstance(raw_instance, Plugin) else None
            plugin_id = next(
                (
                    current_id
                    for current_id, owner in self._plugin_ids.items()
                    if owner == import_path
                ),
                None,
            )
            await self._cleanup_plugin(import_path, instance, plugin_id)

    @property
    def loaded_names(self) -> list[str]:
        return [
            self._loaded_names[import_path]
            for import_path in self._load_order
            if import_path in self._loaded_names
        ]

    @staticmethod
    def _record(
        candidate: PluginCandidate,
        status: PluginLoadStatus,
        *,
        stage: str | None = None,
        message: str | None = None,
    ) -> PluginLoadRecord:
        return PluginLoadRecord(
            name=candidate.name,
            source=candidate.source,
            import_path=candidate.import_path,
            status=status,
            stage=stage,
            message=message,
        )


def _import_path(source: str, directory_name: str, module_path: Path) -> str:
    def sanitize(value: str) -> str:
        return "".join(
            char
            if char.isascii() and (char.isalnum() or char == "_")
            else "_"
            for char in value
        )

    identity = f"{source}\0{module_path.resolve()}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:12]
    return f"amadeus_plugin_{sanitize(source)}_{sanitize(directory_name)}_{digest}"


def _safe_traceback(error: Exception) -> str:
    """Render stack locations without exception messages or source text."""
    frames = traceback.extract_tb(error.__traceback__)
    return " | ".join(
        f"file={frame.filename} line={frame.lineno} function={frame.name}"
        for frame in frames
    )


def _warn_optional_failure(
    candidate: PluginCandidate,
    stage: str,
    error: Exception | None = None,
) -> None:
    if error is None:
        logger.warning(
            "plugin optional data ignored name=%s source=%s stage=%s",
            candidate.name,
            candidate.source,
            stage,
        )
    else:
        logger.warning(
            "plugin optional data ignored name=%s source=%s stage=%s exception=%s",
            candidate.name,
            candidate.source,
            stage,
            type(error).__name__,
        )


def _apply_manifest(instance: Plugin, candidate: PluginCandidate) -> None:
    manifest_path = candidate.plugin_dir / "manifest.yaml"
    if not manifest_path.exists():
        _warn_optional_failure(candidate, "manifest")
        return
    try:
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    except Exception as error:
        _warn_optional_failure(candidate, "manifest", error)
        return
    if not isinstance(loaded, dict):
        _warn_optional_failure(candidate, "manifest")
        return
    manifest = cast(dict[object, object], loaded)
    for field in _MANIFEST_FIELDS:
        value = manifest.get(field)
        if value is not None:
            setattr(instance, field, str(value))


def _load_plugin_config(candidate: PluginCandidate) -> PluginConfig | None:
    schema_path = candidate.plugin_dir / "_conf_schema.json"
    if not schema_path.exists():
        return None
    try:
        loaded = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as error:
        _warn_optional_failure(candidate, "config-schema", error)
        return None
    if not isinstance(loaded, dict):
        _warn_optional_failure(candidate, "config-schema")
        return None

    schema = cast(dict[object, object], loaded)
    values: dict[str, Any] = {}
    for key, field_spec in schema.items():
        if isinstance(key, str) and isinstance(field_spec, dict) and "default" in field_spec:
            values[key] = field_spec["default"]

    override_path = candidate.plugin_dir / "plugin_config.json"
    if override_path.exists():
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
        except Exception as error:
            _warn_optional_failure(candidate, "config-override", error)
        else:
            if isinstance(override, dict):
                values.update(
                    {
                        key: value
                        for key, value in cast(dict[object, object], override).items()
                        if isinstance(key, str)
                    }
                )
            else:
                _warn_optional_failure(candidate, "config-override")
    return PluginConfig(values)
