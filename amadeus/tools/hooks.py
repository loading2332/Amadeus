from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutionDenied

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
    """

    workspace_root: Path

    def _resolve(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        return (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace_root / candidate).resolve()
        )

    def _check_scope(self, resolved: Path, allowed_base: Path) -> None:
        try:
            resolved.relative_to(allowed_base.resolve())
        except ValueError as error:
            raise ToolExecutionDenied(
                f"path escapes allowed directory: {resolved}"
            ) from error

    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.tool_name not in _FILE_TOOLS:
            return request

        raw_path = str(request.arguments.get("path") or "").strip()
        if not raw_path:
            return request

        resolved = self._resolve(raw_path)

        if request.tool_name in _WRITE_TOOLS:
            artifacts_root = (self.workspace_root / _ARTIFACTS_SUBDIR).resolve()
            self._check_scope(resolved, artifacts_root)
        else:
            # Read/list: allowed under workspace_root
            self._check_scope(resolved, self.workspace_root)

        return ToolExecutionRequest(
            tool_name=request.tool_name,
            arguments={**request.arguments, "path": str(resolved)},
        )

    def after_execute(
        self,
        request: ToolExecutionRequest,
        result: ToolResult,
    ) -> ToolResult:
        return result
