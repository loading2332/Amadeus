from __future__ import annotations

import asyncio
from pathlib import Path

from amadeus.tools.base import ToolResult
from amadeus.tools.defaults import (
    EditFileTool,
    ListDirTool,
    ReadFileTool,
    WriteFileTool,
)

# ── ListDirTool ────────────────────────────────────────────────────────────

class TestListDirTool:
    def test_lists_directory_contents(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        sub = tmp_path / "sub"
        sub.mkdir()

        tool = ListDirTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path))

        assert result.is_error is False
        entries = result.output["entries"]
        assert len(entries) == 3
        assert any(e["name"] == "a.txt" and not e["is_dir"] for e in entries)
        assert any(e["name"] == "b.txt" and not e["is_dir"] for e in entries)
        assert any(e["name"] == "sub" and e["is_dir"] for e in entries)

    def test_rejects_nonexistent_path(self, tmp_path: Path) -> None:
        tool = ListDirTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path / "nonexistent"))
        assert result.is_error
        assert "不存在" in result.output.get("error", "")

    def test_rejects_file_path(self, tmp_path: Path) -> None:
        path = tmp_path / "file.txt"
        path.write_text("content")
        tool = ListDirTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(path))
        assert result.is_error
        assert "不是目录" in result.output.get("error", "")

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        tool = ListDirTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path.parent))
        assert result.is_error
        assert "超出允许目录" in result.output.get("error", "")


# ── ReadFileTool ───────────────────────────────────────────────────────────

class TestReadFileTool:
    def test_reads_utf8_text(self, tmp_path: Path) -> None:
        path = tmp_path / "hello.txt"
        path.write_text("hello world", encoding="utf-8")

        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(path))

        assert result.is_error is False
        assert result.output["content"] == "hello world"

    def test_supports_offset_and_limit(self, tmp_path: Path) -> None:
        path = tmp_path / "lines.txt"
        path.write_text("\n".join(f"line-{i}" for i in range(10)), encoding="utf-8")

        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(path), offset=2, limit=3)

        assert result.is_error is False
        assert result.output["content"] == "line-2\nline-3\nline-4"

    def test_truncates_large_content(self, tmp_path: Path) -> None:
        """ReadFileTool truncates content that exceeds max lines."""
        path = tmp_path / "big.txt"
        path.write_text("\n".join(f"data-{i}" for i in range(500)), encoding="utf-8")

        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(path))

        assert result.is_error is False
        assert result.output["truncated"] is True
        assert "已截断" in result.output.get("note", "")

    def test_rejects_directory_path(self, tmp_path: Path) -> None:
        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path))
        assert result.is_error
        assert "不是文件" in result.output.get("error", "")

    def test_rejects_nonexistent_path(self, tmp_path: Path) -> None:
        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path / "missing.txt"))
        assert result.is_error
        assert "不存在" in result.output.get("error", "")

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(tmp_path.parent / "outside.txt"))
        assert result.is_error
        assert "超出允许目录" in result.output.get("error", "")

    def test_returns_metadata(self, tmp_path: Path) -> None:
        path = tmp_path / "meta.txt"
        path.write_text("hello", encoding="utf-8")

        tool = ReadFileTool(allowed_dir=tmp_path)
        result = tool.execute(path=str(path))

        assert result.is_error is False
        assert result.output["path"] == str(path)
        assert result.output["size"] == 5
        assert result.output["line_count"] == 1


# ── WriteFileTool ──────────────────────────────────────────────────────────

class TestWriteFileTool:
    def _run(self, tool: WriteFileTool, **kwargs: object) -> ToolResult:
        return asyncio.run(tool.execute(**kwargs))

    def test_creates_new_file(self, tmp_path: Path) -> None:
        target = tmp_path / "output.txt"
        tool = WriteFileTool(allowed_dir=tmp_path)
        result = self._run(tool, path=str(target), content="hello")

        assert result.is_error is False
        assert target.read_text(encoding="utf-8") == "hello"
        assert result.output["bytes_written"] == 5

    def test_creates_parent_directories(self, tmp_path: Path) -> None:
        target = tmp_path / "sub" / "nested" / "out.txt"
        tool = WriteFileTool(allowed_dir=tmp_path)
        result = self._run(tool, path=str(target), content="nested")

        assert result.is_error is False
        assert target.read_text(encoding="utf-8") == "nested"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("old content", encoding="utf-8")
        tool = WriteFileTool(allowed_dir=tmp_path)
        result = self._run(tool, path=str(target), content="new content")

        assert result.is_error is False
        assert target.read_text(encoding="utf-8") == "new content"

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        tool = WriteFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(tmp_path.parent / "outside.txt"),
            content="test",
        )
        assert result.is_error
        assert "超出允许目录" in result.output.get("error", "")


# ── EditFileTool ───────────────────────────────────────────────────────────

class TestEditFileTool:
    def _run(self, tool: EditFileTool, **kwargs: object) -> ToolResult:
        return asyncio.run(tool.execute(**kwargs))

    def test_replaces_exact_text(self, tmp_path: Path) -> None:
        target = tmp_path / "edit.txt"
        target.write_text("hello world", encoding="utf-8")

        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(target),
            old_text="world",
            new_text="there",
        )

        assert result.is_error is False
        assert target.read_text(encoding="utf-8") == "hello there"
        assert "替换 1 处" in result.output["summary"]

    def test_returns_diff_summary(self, tmp_path: Path) -> None:
        target = tmp_path / "diff.txt"
        target.write_text("before", encoding="utf-8")

        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(target),
            old_text="before",
            new_text="after",
        )

        assert result.is_error is False
        assert "diff" in result.output
        assert "before" in result.output["diff"] or "-before" in result.output["diff"]

    def test_fails_on_non_matching_old_text(self, tmp_path: Path) -> None:
        target = tmp_path / "nomatch.txt"
        target.write_text("hello", encoding="utf-8")

        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(target),
            old_text="nonexistent",
            new_text="anything",
        )

        assert result.is_error
        assert "未找到" in result.output.get("error", "")

    def test_warns_on_multiple_matches(self, tmp_path: Path) -> None:
        target = tmp_path / "multi.txt"
        target.write_text("a b a b", encoding="utf-8")

        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(target),
            old_text="a",
            new_text="x",
        )

        assert result.is_error is True
        assert "出现了" in result.output.get("error", "")

    def test_replace_all_works(self, tmp_path: Path) -> None:
        target = tmp_path / "replace_all.txt"
        target.write_text("a b a b", encoding="utf-8")

        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(target),
            old_text="a",
            new_text="x",
            replace_all=True,
        )

        assert result.is_error is False
        assert target.read_text(encoding="utf-8") == "x b x b"
        assert "替换 2 处" in result.output["summary"]

    def test_fails_on_nonexistent_file(self, tmp_path: Path) -> None:
        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(tmp_path / "missing.txt"),
            old_text="anything",
            new_text="nothing",
        )

        assert result.is_error
        assert "不存在" in result.output.get("error", "")

    def test_rejects_path_escape(self, tmp_path: Path) -> None:
        tool = EditFileTool(allowed_dir=tmp_path)
        result = self._run(
            tool,
            path=str(tmp_path.parent / "outside.txt"),
            old_text="old",
            new_text="new",
        )
        assert result.is_error
        assert "超出允许目录" in result.output.get("error", "")
