"""
内容搜索工具 — 按正则或纯文本搜索文件内容。

功能：
  - 纯 Python 实现，无外部依赖
  - 支持正则和纯文本模式
  - 支持 glob 文件过滤
  - 支持上下文行显示
  - 自动跳过二进制文件和大文件
  - 三种输出模式：content / files / count
"""
from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Bool, Int, Str, tool_params
from app.tools._path_utils import IGNORE_DIRS, is_binary, resolve_safe

if TYPE_CHECKING:
    from app.tools.context import ToolContext

_MAX_FILE_SIZE = 2 * 1024 * 1024  # 2MB
_MAX_OUTPUT_CHARS = 64_000
_DEFAULT_MAX_RESULTS = 100


class GrepTool(BuiltinTool):
    """按正则或纯文本搜索文件内容。"""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()

    @classmethod
    def create(cls, ctx: "ToolContext") -> "GrepTool":
        return cls(workspace=ctx.workspace)

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return "搜索文件内容，支持正则表达式，可按 glob 过滤文件类型"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "pattern",
            pattern=Str("搜索模式（正则表达式或纯文本）"),
            root=Str("搜索起始目录，相对于工作目录，默认根目录"),
            glob=Str("文件过滤 glob，如 '*.py'"),
            case_sensitive=Bool("是否区分大小写，默认 false"),
            fixed_string=Bool("是否按纯文本匹配（非正则），默认 false"),
            context_lines=Int("匹配行前后的上下文行数，默认 0", maximum=10),
            max_results=Int("最大匹配数量，默认 100", maximum=200),
            output_mode=Str("输出模式: content/files/count", enum=["content", "files", "count"]),
        )

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        pattern_str = params.get("pattern", "").strip()
        root_str = params.get("root", ".")
        glob_filter = params.get("glob", "")
        case_sensitive = params.get("case_sensitive", False)
        fixed_string = params.get("fixed_string", False)
        context_lines = params.get("context_lines", 0)
        max_results = params.get("max_results", _DEFAULT_MAX_RESULTS)
        output_mode = params.get("output_mode", "content")

        if not pattern_str:
            return {"status": "error", "data": {"message": "pattern 不能为空"}}

        root, err = resolve_safe(root_str, self._workspace)
        if err:
            return {"status": "error", "data": {"message": err}}
        if not root.exists() or not root.is_dir():
            return {"status": "error", "data": {"message": f"目录不存在: {root_str}"}}

        # 编译正则
        if fixed_string:
            pattern_str = re.escape(pattern_str)
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return {"status": "error", "data": {"message": f"正则表达式错误: {e}"}}

        # 搜索
        files_searched = 0
        total_matches = 0
        results = []
        output_size = 0

        for file_path in self._iter_files(root, glob_filter):
            if total_matches >= max_results:
                break
            if output_size >= _MAX_OUTPUT_CHARS:
                break

            files_searched += 1
            file_matches = self._search_file(
                file_path, regex, context_lines, output_mode,
                max_results - total_matches,
            )
            if file_matches:
                total_matches += len(file_matches) if output_mode != "files" else 1
                rel_path = str(file_path.relative_to(self._workspace)).replace("\\", "/")

                if output_mode == "files":
                    results.append(rel_path)
                elif output_mode == "count":
                    results.append({"file": rel_path, "count": len(file_matches)})
                else:
                    for m in file_matches:
                        m["file"] = rel_path
                        results.append(m)
                        output_size += len(str(m))

        truncated = total_matches >= max_results or output_size >= _MAX_OUTPUT_CHARS
        return {
            "status": "success",
            "data": {
                "matches": results,
                "total_matches": total_matches,
                "files_searched": files_searched,
                "truncated": truncated,
            },
        }

    def _iter_files(self, root: Path, glob_filter: str):
        """遍历目录下所有可搜索的文件。"""
        for dirpath, dirnames, filenames in os.walk(root):
            # 原地修改 dirnames 以跳过忽略目录
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS and not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                if glob_filter and not fnmatch.fnmatch(fname, glob_filter):
                    continue
                fpath = Path(dirpath) / fname
                try:
                    if fpath.stat().st_size > _MAX_FILE_SIZE:
                        continue
                except OSError:
                    continue
                if is_binary(fpath):
                    continue
                yield fpath

    @staticmethod
    def _search_file(
        path: Path, regex: re.Pattern, context_lines: int,
        output_mode: str, remaining: int,
    ) -> list[dict] | list:
        """搜索单个文件，返回匹配结果。"""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []

        matches = []
        for i, line in enumerate(lines):
            if regex.search(line):
                if output_mode == "files":
                    return [{}]  # 只需知道有匹配
                if output_mode == "count":
                    matches.append({})
                else:
                    match = {"line": i + 1, "content": line.rstrip()}
                    if context_lines > 0:
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)
                        match["context_before"] = [l.rstrip() for l in lines[start:i]]
                        match["context_after"] = [l.rstrip() for l in lines[i + 1:end]]
                    matches.append(match)
                if len(matches) >= remaining:
                    break
        return matches
