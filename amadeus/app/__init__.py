"""Application wiring for CLI, bootstrap, and workspace initialization."""

from amadeus.app.bootstrap import (
    AppState,
    PassiveApp,
    RuntimeConfig,
    build_passive_app,
    default_workspace_root,
    load_runtime_config,
)
from amadeus.app.cli import main
from amadeus.app.workspace import DEFAULT_SELF_MD, initialize_workspace

__all__ = [
    "AppState",
    "DEFAULT_SELF_MD",
    "PassiveApp",
    "RuntimeConfig",
    "build_passive_app",
    "default_workspace_root",
    "initialize_workspace",
    "load_runtime_config",
    "main",
]
