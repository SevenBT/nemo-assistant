"""
剪贴板工具 — 读取或写入系统剪贴板。

这是一个简单工具的示例：
  - 不需要 ToolContext 依赖
  - 使用 pyperclip 库实现跨平台剪贴板操作
  - 通过 action 参数区分读/写操作
"""
from typing import Any

from app.tools.base import BuiltinTool
from app.tools.schema import Str, tool_params
from app.i18n import t


class ClipboardTool(BuiltinTool):
    """系统剪贴板读写工具。"""

    @property
    def name(self) -> str:
        return "clipboard"

    @property
    def description(self) -> str:
        return t("tool.clipboard.description")

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",  # action 是必填参数
            action=Str(t("tool.clipboard.param.action"), enum=["get", "set"]),
            content=Str(t("tool.clipboard.param.content")),
        )

    def execute(self, params: dict[str, Any]) -> dict[str, Any]:
        action = params.get("action", "get")
        content = params.get("content", "")
        try:
            import pyperclip
            if action == "get":
                text = pyperclip.paste()
                return {"status": "success", "data": {"content": text, "length": len(text)}}
            else:
                pyperclip.copy(content)
                return {"status": "success", "data": {"message": t("tool.clipboard.msg.copied", count=len(content))}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
