from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from amadeus.tools.base import ToolExecutionRequest, ToolResult
from amadeus.tools.executor import ToolExecutionDenied


@dataclass
class ReadOnlyFilesystemHook:
    workspace_root: Path

    def before_execute(self, request: ToolExecutionRequest) -> ToolExecutionRequest:
        if request.tool_name != "read_file":
            return request
        raw_path = str(request.arguments.get("path") or "").strip()
        candidate = Path(raw_path)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.workspace_root / candidate).resolve()
        )
        try:
            resolved.relative_to(self.workspace_root.resolve())
        except ValueError as error:
            raise ToolExecutionDenied(f"path escapes workspace: {resolved}") from error
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
