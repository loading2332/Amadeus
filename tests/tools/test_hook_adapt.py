from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from amadeus.tools.base import HookContext, ToolExecutionRequest
from amadeus.tools.hooks import ReadOnlyFilesystemHook
from amadeus.tools.registry import ToolRegistry


def _make_ctx(tool_name: str, args: dict) -> HookContext:
    return HookContext(
        event="pre_tool_use",
        request=ToolExecutionRequest(tool_name=tool_name, arguments=args),
        current_arguments=dict(args),
    )


def test_hook_rewrites_relative_path_for_read_tool():
    with TemporaryDirectory() as tmp:
        hook = ReadOnlyFilesystemHook(workspace_root=Path(tmp))
        ctx = _make_ctx("read_file", {"path": "config.py"})

        outcome = hook.run(ctx)

        assert outcome.decision == "pass"
        assert outcome.updated_input is not None
        # 相对路径被解析为绝对路径
        assert Path(outcome.updated_input["path"]).name == "config.py"
        assert Path(outcome.updated_input["path"]).is_absolute()


def test_hook_denies_write_tool_outside_artifacts():
    with TemporaryDirectory() as tmp:
        hook = ReadOnlyFilesystemHook(workspace_root=Path(tmp))
        ctx = _make_ctx("write_file", {"path": "config.py"})

        outcome = hook.run(ctx)

        assert outcome.decision == "deny"
        assert "escapes allowed directory" in outcome.reason


def test_hook_allows_write_tool_inside_artifacts():
    with TemporaryDirectory() as tmp:
        hook = ReadOnlyFilesystemHook(workspace_root=Path(tmp))
        ctx = _make_ctx("write_file", {"path": "runtime-artifacts/out.txt"})

        outcome = hook.run(ctx)

        assert outcome.decision == "pass"
        assert outcome.updated_input is not None
        resolved = Path(outcome.updated_input["path"])
        assert resolved.name == "out.txt"
        assert resolved.is_absolute()


def test_hook_does_not_match_non_file_tool():
    with TemporaryDirectory() as tmp:
        hook = ReadOnlyFilesystemHook(workspace_root=Path(tmp))
        ctx = _make_ctx("recall_memory", {"query": "x"})

        assert hook.matches(ctx) is False


def test_hook_passes_when_no_path_argument():
    with TemporaryDirectory() as tmp:
        hook = ReadOnlyFilesystemHook(workspace_root=Path(tmp))
        ctx = _make_ctx("read_file", {})

        outcome = hook.run(ctx)

        assert outcome.decision == "pass"
        assert outcome.updated_input is None