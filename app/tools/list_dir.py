"""
目录列表工具 — 列出指定目录的内容。

功能：
  - 列出目录下的文件和子目录
  - 支持递归模式
  - 路径限制在 workspace 内
  - 自动跳过 .git 等忽略目录
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Bool, Int, Str, tool_params
from app.tools._path_utils import IGNORE_DIRS, resolve_safe

if TYPE_CHECKING:
    from app.tools.context import ToolContext

_DEFAULT_MAX = 200


class ListDirTool(BuiltinTool):
    """列出目录内容，支持递归。"""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ListDirTool":
        return cls(workspace=ctx.workspace)

    @property
    def name(self) -> str:
        return "list_dir"

    @property
    def description(self) -> str:
        return "列出指定目录的文件和子目录，可递归展示目录结构"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "path",
            path=Str("目录路径，相对于工作目录"),
            recursive=Bool("是否递归列出子目录，默认 false"),
            max_entries=Int("最大返回条目数，默认 200", maximum=500),
            include_hidden=Bool("是否包含隐藏文件（.开头），默认 false"),
        )

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        path_str = params.get("path", ".")
        recursive = params.get("recursive", False)
        max_entries = params.get("max_entries", _DEFAULT_MAX)
        include_hidden = params.get("include_hidden", False)

        target, err = resolve_safe(path_str, self._workspace)
        if err:
            return {"status": "error", "data": {"message": err}}
        if not target.exists():
            return {"status": "error", "data": {"message": f"目录不存在: {path_str}"}}
        if not target.is_dir():
            return {"status": "error", "data": {"message": f"路径不是目录: {path_str}"}}

        entries = []
        if recursive:
            entries = self._walk_recursive(target, include_hidden, max_entries)
        else:
            entries = self._list_flat(target, include_hidden, max_entries)

        truncated = len(entries) >= max_entries
        return {
            "status": "success",
            "data": {
                "path": path_str,
                "entries": entries,
                "total": len(entries),
                "truncated": truncated,
            },
        }

    def _list_flat(self, target: Path, include_hidden: bool, limit: int) -> list[dict]:
        entries = []
        try:
            items = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return []

        for item in items:
            if len(entries) >= limit:
                break
            if not include_hidden and item.name.startswith("."):
                continue
            if item.is_dir() and item.name in IGNORE_DIRS:
                continue
            entry = {"name": item.name, "type": "dir" if item.is_dir() else "file"}
            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    pass
            entries.append(entry)
        return entries

    def _walk_recursive(self, target: Path, include_hidden: bool, limit: int) -> list[dict]:
        entries = []
        for item in self._iter_tree(target):
            if len(entries) >= limit:
                break
            rel = item.relative_to(target)
            if not include_hidden and any(p.startswith(".") for p in rel.parts):
                continue
            if any(p in IGNORE_DIRS for p in rel.parts):
                continue
            entry = {"name": str(rel).replace("\\", "/"), "type": "dir" if item.is_dir() else "file"}
            if item.is_file():
                try:
                    entry["size"] = item.stat().st_size
                except OSError:
                    pass
            entries.append(entry)
        return entries

    @staticmethod
    def _iter_tree(root: Path):
        """深度优先遍历，目录优先。"""
        try:
            items = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return
        for item in items:
            yield item
            if item.is_dir() and item.name not in IGNORE_DIRS:
                yield from ListDirTool._iter_tree(item)
