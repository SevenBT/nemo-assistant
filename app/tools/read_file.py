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
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Num, Str, tool_params

# 默认最大读取字符数
_MAX_DEFAULT = 50_000


class ReadFileTool(BuiltinTool):
    """本地文件读取工具。"""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return "读取本地文本文件内容，支持 txt、md、py、json、csv 等格式"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "file_path",  # file_path 是必填参数
            file_path=Str("文件绝对路径，或以 ~/ 开头的路径"),
            max_chars=Num("最大读取字符数，默认 50000"),
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

        # 展开 ~ 为用户主目录
        path = Path(raw_path).expanduser()

        if not path.exists():
            return {"status": "error", "data": {"message": f"文件不存在: {path}"}}
        if not path.is_file():
            return {"status": "error", "data": {"message": f"路径不是文件: {path}"}}

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
            return {"status": "error", "data": {"message": "无法解码文件，可能是二进制文件"}}

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
