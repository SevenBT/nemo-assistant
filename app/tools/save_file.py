"""
保存文件工具 — 将内容写入本地文件。

特点：
  - 从 ToolContext 获取用户配置的保存目录（默认 ~/Downloads）
  - 自动处理文件名冲突（追加 _1、_2 后缀）
  - 保存后自动打开所在目录（Windows 资源管理器）
  - 安全措施：只取文件名部分，防止路径穿越攻击
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params

if TYPE_CHECKING:
    from app.tools.context import ToolContext


class SaveFileTool(BuiltinTool):
    """本地文件保存工具。"""

    def __init__(self, save_dir: str = ""):
        # 用户配置的保存目录，为空则使用 ~/Downloads
        self._save_dir = save_dir

    @classmethod
    def create(cls, ctx: "ToolContext") -> "SaveFileTool":
        """从配置中读取用户设置的文件保存目录。"""
        from app.core.config import cfg
        return cls(save_dir=cfg.get(cfg.saveDir))

    @property
    def name(self) -> str:
        return "save_file"

    @property
    def description(self) -> str:
        return "将内容保存为本地文件（txt/md/json/csv/py 等），完成后在资源管理器中打开所在目录"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "filename", "content",
            filename=Str("文件名（含扩展名），如 'report.md'、'data.csv'"),
            content=Str("要写入文件的文本内容"),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        filename = params.get("filename", "").strip()
        content = params.get("content", "")

        if not filename:
            return {"status": "error", "data": {"message": "filename is required"}}

        # 安全措施：只取文件名部分，防止 "../../../etc/passwd" 之类的路径穿越
        filename = Path(filename).name
        if not filename:
            return {"status": "error", "data": {"message": "invalid filename"}}

        # 确定保存目录
        target_dir = Path(self._save_dir) if self._save_dir else Path.home() / "Downloads"
        target_dir.mkdir(parents=True, exist_ok=True)

        # 处理文件名冲突：已存在则追加 _1、_2... 后缀
        file_path = target_dir / filename
        counter = 1
        stem = file_path.stem
        suffix = file_path.suffix
        while file_path.exists():
            file_path = target_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        file_path.write_text(content, encoding="utf-8")

        # 保存后打开所在目录（仅 Windows）
        try:
            os.startfile(str(target_dir))
        except Exception:
            pass  # 非 Windows 平台或权限问题，静默忽略

        return {
            "status": "success",
            "data": {
                "path": str(file_path), "filename": file_path.name,
                "size_bytes": len(content.encode("utf-8")),
                "message": f"已保存到 {file_path}",
            },
        }
