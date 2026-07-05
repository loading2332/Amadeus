from __future__ import annotations

import asyncio
import difflib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from amadeus.session.store import (
    SessionStoreProtocol,
    fetch_messages,
    search_messages,
)
from amadeus.tools.base import ToolResult

ToolParameters = dict[str, Any]
_T = TypeVar("_T")


def _optional_string(name: str, value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a string")


def _required_string(name: str, value: object) -> str:
    if isinstance(value, str):
        return value
    raise TypeError(f"{name} must be a string")


def _optional_string_list(name: str, value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list of strings")
    for item in value:
        if not isinstance(item, str):
            raise TypeError(f"{name} must contain only strings")
    return value


def _optional_dict_list(name: str, value: object) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list of objects")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise TypeError(f"{name} must contain only objects")
        result.append(item)
    return result


def _int_arg(name: str, value: object, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    if isinstance(value, int):
        return value
    raise TypeError(f"{name} must be an integer")


# ── Filesystem helpers ────────────────────────────────────────────────────

_FILE_MUTATION_LOCKS: dict[str, asyncio.Lock] = {}


def _resolve_path(path: str, allowed_dir: Path | None = None) -> Path:
    """Resolve *path* relative to *allowed_dir* and guard against escape."""
    p = Path(path)
    if not p.is_absolute() and allowed_dir is not None:
        resolved = (allowed_dir / p).resolve()
    else:
        resolved = p.resolve()
    if allowed_dir is not None:
        try:
            resolved.relative_to(allowed_dir.resolve())
        except ValueError:
            raise PermissionError(
                f"路径 {path} 超出允许目录 {allowed_dir}"
            ) from None
    return resolved


def _build_edit_diff(old_text: str, new_text: str, path: str) -> str:
    lines = list(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            fromfile=f"{path} (before)",
            tofile=f"{path} (after)",
            lineterm="",
            n=2,
        )
    )
    return "\n".join(lines)


def _get_file_mutation_key(file_path: Path) -> str:
    try:
        return str(file_path.resolve(strict=True))
    except FileNotFoundError:
        return os.path.realpath(str(file_path))


async def _run_with_file_mutation_lock(
    file_path: Path,
    fn: Callable[[], Awaitable[_T]],
) -> _T:
    key = _get_file_mutation_key(file_path)
    lock = _FILE_MUTATION_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _FILE_MUTATION_LOCKS[key] = lock
    async with lock:
        result = await fn()
    current = _FILE_MUTATION_LOCKS.get(key)
    if current is lock and not lock.locked():
        _FILE_MUTATION_LOCKS.pop(key, None)
    return result


_READ_MAX_LINES = 400
_READ_MAX_BYTES = 10_000


def _scan_text_file(
    file_path: Path, offset: int, limit: int | None
) -> tuple[list[str], int, int]:
    """Return (sliced_lines, total_lines, total_bytes) for a text file."""
    sliced_lines: list[str] = []
    total_lines = 0
    total_bytes = 0
    with open(file_path, "rb") as fh:
        while True:
            raw_line = fh.readline()
            if raw_line == b"":
                break
            total_lines += 1
            total_bytes += len(raw_line)
            line_idx = total_lines - 1
            if line_idx < offset:
                continue
            if limit is not None and len(sliced_lines) >= limit:
                continue
            try:
                decoded = raw_line.decode("utf-8").rstrip("\n").rstrip("\r")
            except UnicodeDecodeError:
                decoded = raw_line.decode("utf-8", errors="replace").rstrip("\n").rstrip("\r")
            sliced_lines.append(decoded)
    return sliced_lines, total_lines, total_bytes


# ── Session tools ──────────────────────────────────────────────────────────


@dataclass
class FetchMessagesTool:
    store: SessionStoreProtocol
    name: str = "fetch_messages"
    description: str = (
        "Fetch persisted original session messages by ids, source_ref, or recall evidence. "
        "这是 recall_memory、search_messages 和被动记忆注入之后唯一可作为最终证据的原文工具。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "ids": {"type": "array", "items": {"type": "string"}},
                "source_ref": {"type": "string"},
                "source_refs": {"type": "array", "items": {"type": "string"}},
                "evidence": {"type": "array", "items": {"type": "object"}},
                "context": {"type": "integer"},
            },
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        messages = fetch_messages(
            self.store,
            ids=_optional_string_list("ids", kwargs.get("ids")),
            source_ref=_optional_string("source_ref", kwargs.get("source_ref")),
            source_refs=_optional_string_list("source_refs", kwargs.get("source_refs")),
            evidence=_optional_dict_list("evidence", kwargs.get("evidence")),
            context=_int_arg("context", kwargs.get("context"), 0),
        )
        return ToolResult(
            tool_name=self.name,
            output={
                "count": len(messages),
                "matched_count": sum(1 for item in messages if item.get("in_source_ref") is True)
                or len(messages),
                "messages": messages,
            },
        )


@dataclass
class SearchMessagesTool:
    store: SessionStoreProtocol
    name: str = "search_messages"
    description: str = (
        "Search persisted session messages by substring and return candidate previews with source_ref. "
        "预览不是最终证据；使用结果回答前必须调用 fetch_messages(source_ref=...) 读取原文。"
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "session_key": {"type": "string"},
                "role": {"type": "string"},
                "limit": {"type": "integer"},
                "offset": {"type": "integer"},
            },
            "required": ["query"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        payload = search_messages(
            self.store,
            query=_required_string("query", kwargs.get("query")),
            session_key=_optional_string("session_key", kwargs.get("session_key")),
            role=_optional_string("role", kwargs.get("role")),
            limit=_int_arg("limit", kwargs.get("limit"), 10),
            offset=_int_arg("offset", kwargs.get("offset"), 0),
        )
        return ToolResult(tool_name=self.name, output=payload)


# ── Filesystem tools ───────────────────────────────────────────────────────


@dataclass
class ReadFileTool:
    allowed_dir: Path | None = None
    name: str = "read_file"
    description: str = (
        "Read a UTF-8 text file from disk with optional offset/limit pagination. "
        "Large files are automatically truncated to prevent excessive output. "
        "Returned content shows the raw text without line-number prefixes."
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (absolute or relative)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Starting line number (0-based). Default 0.",
                    "minimum": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to return.",
                    "minimum": 1,
                },
            },
            "required": ["path"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        path = _required_string("path", kwargs.get("path"))
        offset = _int_arg("offset", kwargs.get("offset"), 0)
        raw_limit = kwargs.get("limit")
        limit: int | None = None
        if raw_limit is not None:
            limit = _int_arg("limit", raw_limit, 0)
        try:
            file_path = _resolve_path(path, self.allowed_dir)
            if not file_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    output={"error": f"文件不存在：{path}"},
                    is_error=True,
                )
            if not file_path.is_file():
                return ToolResult(
                    tool_name=self.name,
                    output={"error": f"路径不是文件：{path}"},
                    is_error=True,
                )

            sliced, total_lines, total_bytes = _scan_text_file(file_path, offset, limit)
            content = "\n".join(sliced)

            # Apply truncation limits
            truncated = False
            note = ""
            if total_lines > _READ_MAX_LINES and limit is None:
                content_lines = content.split("\n")
                if len(content_lines) > _READ_MAX_LINES:
                    content = "\n".join(content_lines[:_READ_MAX_LINES])
                    truncated = True
            if len(content.encode("utf-8")) > _READ_MAX_BYTES:
                lines = content.split("\n")
                byte_count = 0
                truncated_lines: list[str] = []
                for line in lines:
                    line_bytes = len((line + "\n").encode("utf-8"))
                    if byte_count + line_bytes > _READ_MAX_BYTES:
                        truncated = True
                        break
                    truncated_lines.append(line)
                    byte_count += line_bytes
                content = "\n".join(truncated_lines)

            if truncated:
                note = (
                    f"已截断：文件共 {total_lines} 行 / {total_bytes} 字节，"
                    f"本次返回前 {len(content.split(chr(10)))} 行。"
                    f"建议用 offset/limit 分页读取。"
                )

            return ToolResult(
                tool_name=self.name,
                output={
                    "path": str(file_path),
                    "content": content,
                    "line_count": len(content.split(chr(10))) if content else 0,
                    "size": len(content.encode("utf-8")),
                    "total_lines": total_lines,
                    "total_bytes": total_bytes,
                    "truncated": truncated,
                    "note": note,
                },
            )
        except PermissionError as e:
            return ToolResult(
                tool_name=self.name,
                output={"error": str(e)},
                is_error=True,
            )


@dataclass
class WriteFileTool:
    allowed_dir: Path | None = None
    name: str = "write_file"
    description: str = (
        "Write text content to a file (full overwrite). "
        "Parent directories are created automatically if they don't exist."
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to write to"},
                "content": {"type": "string", "description": "Text content to write"},
            },
            "required": ["path", "content"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        path = _required_string("path", kwargs.get("path"))
        content = _required_string("content", kwargs.get("content"))
        try:
            file_path = _resolve_path(path, self.allowed_dir)

            async def _write() -> ToolResult:
                if file_path.exists() and file_path.is_dir():
                    return ToolResult(
                        tool_name=self.name,
                        output={"error": f"目标路径是目录：{path}"},
                        is_error=True,
                    )
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                return ToolResult(
                    tool_name=self.name,
                    output={
                        "path": str(file_path),
                        "bytes_written": len(content.encode("utf-8")),
                    },
                )

            return await _run_with_file_mutation_lock(file_path, _write)
        except PermissionError as e:
            return ToolResult(
                tool_name=self.name,
                output={"error": str(e)},
                is_error=True,
            )


@dataclass
class EditFileTool:
    allowed_dir: Path | None = None
    name: str = "edit_file"
    description: str = (
        "Replace exact old_text with new_text in a file. "
        "old_text must match the file content exactly. "
        "Use replace_all=true to replace every occurrence."
    )
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to edit"},
                "old_text": {
                    "type": "string",
                    "description": "Exact text to find and replace.",
                },
                "new_text": {"type": "string", "description": "Replacement text"},
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences. Default: false (only first)",
                },
            },
            "required": ["path", "old_text", "new_text"],
        }
    )

    async def execute(self, **kwargs: object) -> ToolResult:
        path = _required_string("path", kwargs.get("path"))
        old_text = _required_string("old_text", kwargs.get("old_text"))
        new_text = _required_string("new_text", kwargs.get("new_text"))
        replace_all = bool(kwargs.get("replace_all", False))
        try:
            file_path = _resolve_path(path, self.allowed_dir)

            async def _edit() -> ToolResult:
                if not file_path.exists():
                    return ToolResult(
                        tool_name=self.name,
                        output={"error": f"文件不存在：{path}"},
                        is_error=True,
                    )

                content = file_path.read_text(encoding="utf-8")

                if old_text not in content:
                    return ToolResult(
                        tool_name=self.name,
                        output={
                            "error": "未找到 old_text，请确保与文件内容完全一致。",
                        },
                        is_error=True,
                    )

                count = content.count(old_text)
                if count > 1 and not replace_all:
                    return ToolResult(
                        tool_name=self.name,
                        output={
                            "error": f"old_text 在文件中出现了 {count} 次。"
                                     "如需全部替换，设 replace_all=true；"
                                     "如需精确定位，请在 old_text 中包含更多上下文。",
                        },
                        is_error=True,
                    )

                new_content = (
                    content.replace(old_text, new_text)
                    if replace_all
                    else content.replace(old_text, new_text, 1)
                )
                replaced_count = count if replace_all else 1
                diff_text = _build_edit_diff(content, new_content, path)
                file_path.write_text(new_content, encoding="utf-8")

                return ToolResult(
                    tool_name=self.name,
                    output={
                        "path": str(file_path),
                        "summary": f"已成功编辑 {path}（替换 {replaced_count} 处）",
                        "replaced_count": replaced_count,
                        "diff": diff_text,
                    },
                )

            return await _run_with_file_mutation_lock(file_path, _edit)
        except PermissionError as e:
            return ToolResult(
                tool_name=self.name,
                output={"error": str(e)},
                is_error=True,
            )


@dataclass
class ListDirTool:
    allowed_dir: Path | None = None
    name: str = "list_dir"
    description: str = "List files and subdirectories in a directory."
    parameters: ToolParameters = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the directory to list"},
            },
            "required": ["path"],
        }
    )

    def execute(self, **kwargs: object) -> ToolResult:
        path = _required_string("path", kwargs.get("path"))
        try:
            dir_path = _resolve_path(path, self.allowed_dir)
            if not dir_path.exists():
                return ToolResult(
                    tool_name=self.name,
                    output={"error": f"目录不存在：{path}"},
                    is_error=True,
                )
            if not dir_path.is_dir():
                return ToolResult(
                    tool_name=self.name,
                    output={"error": f"路径不是目录：{path}"},
                    is_error=True,
                )

            entries: list[dict[str, Any]] = []
            for item in sorted(dir_path.iterdir()):
                entries.append({
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "path": str(item),
                })

            return ToolResult(
                tool_name=self.name,
                output={"path": str(dir_path), "entries": entries},
            )
        except PermissionError as e:
            return ToolResult(
                tool_name=self.name,
                output={"error": str(e)},
                is_error=True,
            )
