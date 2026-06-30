"""
文件搜索工具 — 按文件名或 glob 模式查找文件。

功能：
  - 支持 glob 模式（*.py, **/*.md）
  - 支持文件名模糊匹配
  - 路径限制在 workspace 内
  - 自动跳过忽略目录
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Int, Str, tool_params
from app.tools._path_utils import IGNORE_DIRS, resolve_safe
from app.i18n import t

if TYPE_CHECKING:
    from app.tools.context import ToolContext

_DEFAULT_MAX = 100
_GLOB_CHARS = set("*?[]")


class FindFilesTool(BuiltinTool):
    """按文件名或 glob 模式搜索文件。"""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()

    @classmethod
    def create(cls, ctx: "ToolContext") -> "FindFilesTool":
        return cls(workspace=ctx.workspace)

    @property
    def name(self) -> str:
        return "find_files"

    @property
    def description(self) -> str:
        return t("tool.find_files.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "query",
            query=Str(t("tool.find_files.param.query")),
            root=Str(t("tool.find_files.param.root")),
            max_results=Int(t("tool.find_files.param.max_results"), maximum=200),
        )

    @property
    def read_only(self) -> bool:
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        query = params.get("query", "").strip()
        root_str = params.get("root", ".")
        max_results = params.get("max_results", _DEFAULT_MAX)

        if not query:
            return {"status": "error", "data": {"message": t("tool.find_files.msg.query_empty")}}

        root, err = resolve_safe(root_str, self._workspace)
        if err:
            return {"status": "error", "data": {"message": err}}
        if not root.exists() or not root.is_dir():
            return {"status": "error", "data": {"message": t("tool.find_files.msg.dir_not_found", path=root_str)}}

        is_glob = bool(_GLOB_CHARS & set(query))
        matches = []

        if is_glob:
            matches = self._search_glob(root, query, max_results)
        else:
            matches = self._search_fuzzy(root, query, max_results)

        truncated = len(matches) >= max_results
        return {
            "status": "success",
            "data": {
                "matches": matches,
                "total": len(matches),
                "truncated": truncated,
            },
        }

    def _search_glob(self, root: Path, pattern: str, limit: int) -> list[dict]:
        results = []
        try:
            for item in root.rglob(pattern):
                if len(results) >= limit:
                    break
                rel = item.relative_to(self._workspace)
                if any(p in IGNORE_DIRS for p in rel.parts):
                    continue
                entry = {"path": str(rel).replace("\\", "/")}
                if item.is_file():
                    try:
                        entry["size"] = item.stat().st_size
                    except OSError:
                        pass
                results.append(entry)
        except (OSError, ValueError):
            pass
        return results

    def _search_fuzzy(self, root: Path, query: str, limit: int) -> list[dict]:
        results = []
        query_lower = query.lower()
        for item in self._walk(root):
            if len(results) >= limit:
                break
            if query_lower in item.name.lower():
                rel = item.relative_to(self._workspace)
                entry = {"path": str(rel).replace("\\", "/")}
                if item.is_file():
                    try:
                        entry["size"] = item.stat().st_size
                    except OSError:
                        pass
                results.append(entry)
        return results

    @staticmethod
    def _walk(root: Path):
        """递归遍历，跳过忽略目录。"""
        try:
            for item in root.iterdir():
                if item.name in IGNORE_DIRS:
                    continue
                yield item
                if item.is_dir():
                    yield from FindFilesTool._walk(item)
        except PermissionError:
            return
