"""
读取本地文件工具 — 支持多种文本格式和编码。

特点：
  - 自动尝试多种编码（utf-8 → gbk → latin-1）
  - 支持最大字符数限制，防止超大文件撑爆内存
  - 标记为 read_only，可并发执行
  - 不需要 ToolContext 依赖
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Num, Str, tool_params
from app.tools._path_utils import resolve_safe
from app.i18n import t

if TYPE_CHECKING:
    from app.tools.context import ToolContext

# 默认最大读取字符数
_MAX_DEFAULT = 50_000


class ReadFileTool(BuiltinTool):
    """本地文件读取工具。"""

    def __init__(self, workspace: Path):
        self._workspace = workspace.resolve()

    @classmethod
    def create(cls, ctx: "ToolContext") -> "ReadFileTool":
        return cls(workspace=ctx.workspace)

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return t("tool.read_file.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "file_path",  # file_path 是必填参数
            file_path=Str(t("tool.read_file.param.file_path")),
            max_chars=Num(t("tool.read_file.param.max_chars")),
        )

    @property
    def read_only(self) -> bool:
        """只读操作，可并发执行。"""
        return True

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        raw_path = params.get("file_path", "").strip()
        max_chars = int(params.get("max_chars", _MAX_DEFAULT))

        if not raw_path:
            return {"status": "error", "data": {"message": "file_path is required"}}

        # 限制在 workspace 内，避免 AI 读取任意系统文件（.ssh、凭据等）
        path, err = resolve_safe(raw_path, self._workspace)
        if err:
            return {"status": "error", "data": {"message": err}}

        if not path.exists():
            return {"status": "error", "data": {"message": t("tool.read_file.msg.not_found", path=path)}}
        if not path.is_file():
            return {"status": "error", "data": {"message": t("tool.read_file.msg.not_a_file", path=path)}}

        file_size = path.stat().st_size

        # 尝试多种编码读取（中文 Windows 常见 gbk 编码）
        content = None
        for enc in ("utf-8", "gbk", "latin-1"):
            try:
                content = path.read_text(encoding=enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if content is None:
            return {"status": "error", "data": {"message": t("tool.read_file.msg.decode_failed")}}

        # 超长截断
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return {
            "status": "success",
            "data": {
                "path": str(path), "filename": path.name,
                "size_bytes": file_size, "content": content,
                "truncated": truncated, "chars_read": len(content),
            },
        }
