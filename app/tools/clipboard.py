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


class ClipboardTool(BuiltinTool):
    """系统剪贴板读写工具。"""

    @property
    def name(self) -> str:
        return "clipboard"

    @property
    def description(self) -> str:
        return "读取或写入系统剪贴板。action=get 读取当前内容，action=set 将 content 写入剪贴板"

    @property
    def parameters(self) -> dict[str, Any]:
        return tool_params(
            "action",  # action 是必填参数
            action=Str("操作类型：get（读取剪贴板）或 set（写入剪贴板）", enum=["get", "set"]),
            content=Str("当 action=set 时，要写入剪贴板的文本内容"),
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
                return {"status": "success", "data": {"message": f"已复制 {len(content)} 字符到剪贴板"}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}
