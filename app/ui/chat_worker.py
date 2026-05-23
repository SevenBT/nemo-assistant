"""
聊天工作线程，运行完整的 Agent 循环：

1. 向 AI 发送消息（流式）
2. 收集 AI 返回的工具调用
3. 通过 ToolManager 执行工具
4. 将结果反馈给 AI
5. 重复直到无工具调用或达到最大轮次
"""
import json
import queue

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.ai_client import AIClient
from app.core.tool_manager import ToolManager

MAX_TURNS = 10


class ChatWorker(QThread):
    """后台聊天线程，处理流式响应和工具调用循环。"""

    # ── 流式文本 ──────────────────────────────────────────────────────
    text_chunk = pyqtSignal(str)

    # ── 工具生命周期 ──────────────────────────────────────────────────
    tool_started = pyqtSignal(str, str, dict)   # call_id, tool_name, params
    tool_done = pyqtSignal(str, dict)           # call_id, result

    # ── 需要用户手动输入参数后才能执行工具 ────────────────────────────
    need_manual_params = pyqtSignal(str, str, list)  # call_id, tool_name, [param_names]

    # ── 轮次边界（AI 在工具结果后开始新一轮回复）────────────────────
    new_ai_turn = pyqtSignal()

    # ── 完成 / 错误 ──────────────────────────────────────────────────
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(
        self,
        ai_client: AIClient,
        tool_manager: ToolManager,
        api_messages: list[dict],
        tools: list[dict],
        builtin_handlers: dict,  # tool_name -> callable(args) -> dict
        parent=None,
    ):
        super().__init__(parent)
        self._ai = ai_client
        self._tm = tool_manager
        self._messages = list(api_messages)
        self._tools = tools
        self._builtins = builtin_handlers
        self._manual_queue: queue.Queue = queue.Queue()
        self._cancelled = False

    # ── 主线程调用：取消工作线程 ────────────────────────────────────
    def stop(self):
        self._cancelled = True
        self._manual_queue.put({})  # unblock any waiting get()

    # ── 主线程调用：提供手动参数 ────────────────────────────────────
    def supply_manual_params(self, params: dict):
        self._manual_queue.put(params)

    # ── Agent 主循环 ───────────────────────────────────────────────────
    def run(self):
        messages = list(self._messages)

        for _turn in range(MAX_TURNS):
            if self._cancelled:
                return
            full_text = ""
            reasoning_content = None
            tool_calls: list[dict] = []

            for chunk in self._ai.chat_stream(messages, self._tools or None):
                if chunk["type"] == "text":
                    full_text += chunk["delta"]
                    self.text_chunk.emit(chunk["delta"])
                elif chunk["type"] == "tool_call":
                    tool_calls.append(chunk)
                elif chunk["type"] == "error":
                    self.error.emit(chunk["message"])
                    return
                elif chunk["type"] == "done":
                    reasoning_content = chunk.get("reasoning_content")
                    break

            if not tool_calls:
                # 对话完成
                self.finished.emit()
                return

            # 构建 assistant 消息（含 tool_calls）添加到历史记录
            # 对于使用思考模式的模型，必须回传 reasoning_content
            assistant_msg: dict = {
                "role": "assistant",
                "content": full_text or None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ],
            }
            if reasoning_content:
                assistant_msg["reasoning_content"] = reasoning_content
            messages.append(assistant_msg)

            # 执行每个工具调用
            for tc in tool_calls:
                call_id = tc["id"]
                tool_name = tc["name"]
                ai_args = tc["arguments"]

                # 解析参数（优先级：手动 > AI > 配置 > 默认值）
                manual_overrides: dict = {}
                manual_params = self._tm.get_manual_params(tool_name)
                if manual_params:
                    self.need_manual_params.emit(call_id, tool_name, manual_params)
                    try:
                        manual_overrides = self._manual_queue.get(timeout=120)
                    except queue.Empty:
                        manual_overrides = {}

                if tool_name in self._builtins:
                    # 内置工具（如 create_scheduled_task）
                    resolved = {**ai_args, **manual_overrides}
                    self.tool_started.emit(call_id, tool_name, resolved)
                    result = self._builtins[tool_name](resolved)
                else:
                    resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
                    self.tool_started.emit(call_id, tool_name, resolved)
                    result = self._tm.execute(tool_name, resolved)

                self.tool_done.emit(call_id, result)

                # 将工具结果添加到历史记录
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            # 通知 UI 新一轮 AI 回复即将开始
            self.new_ai_turn.emit()

        self.finished.emit()
