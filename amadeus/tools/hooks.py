from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amadeus.tools.base import (
    HookContext,
    HookOutcome,
)

_FILE_TOOLS = frozenset({"read_file", "write_file", "edit_file", "list_dir"})

# Write/edit operations are restricted to runtime-artifacts/ subdirectory
_WRITE_TOOLS = frozenset({"write_file", "edit_file"})
_ARTIFACTS_SUBDIR = "runtime-artifacts"


@dataclass
class ReadOnlyFilesystemHook:
    """Runtime filesystem policy enforced at the hook boundary.

    - Read/list tools (``read_file``, ``list_dir``) allowed everywhere
      under *workspace_root*.
    - Write/edit tools (``write_file``, ``edit_file``) allowed only under
      ``workspace_root / runtime-artifacts/``.
    - Relative paths are resolved against *workspace_root*.
    - Absolute paths must reside under the allowed scope.

    返回 HookOutcome：
    - 路径越界（写工具写到 artifacts 之外）→ decision="deny" + reason
    - 路径解析成功 → updated_input 含 resolved 绝对路径、decision="pass"（改参放行）
    - 非文件工具 → 默认 pass 不动参
    """

    name: str = "readonly_filesystem"
    event: str = "pre_tool_use"
    workspace_root: Path = None  # type: ignore[assignment]

    def _resolve(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        return (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace_root / candidate).resolve()
        )

    def _check_scope(self, resolved: Path, allowed_base: Path) -> str | None:
        try:
            resolved.relative_to(allowed_base.resolve())
        except ValueError:
            return f"path escapes allowed directory: {resolved}"
        return None

    def matches(self, ctx: HookContext) -> bool:
        return ctx.request.tool_name in _FILE_TOOLS

    def run(self, ctx: HookContext) -> HookOutcome:
        request = ctx.request
        raw_path = str(request.arguments.get("path") or "").strip()
        if not raw_path:
            return HookOutcome(decision="pass")

        resolved = self._resolve(raw_path)
        if request.tool_name in _WRITE_TOOLS:
            artifacts_root = (self.workspace_root / _ARTIFACTS_SUBDIR).resolve()
            error = self._check_scope(resolved, artifacts_root)
        else:
            error = self._check_scope(resolved, self.workspace_root)

        if error is not None:
            return HookOutcome(decision="deny", reason=error)

        return HookOutcome(
            decision="pass",
            updated_input={**request.arguments, "path": str(resolved)},
        )