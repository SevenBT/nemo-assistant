"""
ChatWorker runs the full agentic loop in a background thread:
  1. Send messages to AI (streaming)
  2. Collect tool calls from AI response
  3. Execute tools via ToolManager
  4. Feed results back to AI
  5. Repeat until no more tool calls (or max iterations)
"""
import json
import queue

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.ai_client import AIClient
from app.core.tool_manager import ToolManager

MAX_TURNS = 10


class ChatWorker(QThread):
    # ── Streaming text ─────────────────────────────────────────────────
    text_chunk = pyqtSignal(str)

    # ── Tool lifecycle ─────────────────────────────────────────────────
    tool_started = pyqtSignal(str, str, dict)   # call_id, tool_name, params
    tool_done = pyqtSignal(str, dict)           # call_id, result

    # ── Needs manual input from UI before executing a tool ─────────────
    need_manual_params = pyqtSignal(str, str, list)  # call_id, tool_name, [param_names]

    # ── Turn boundary (AI started a new response after tool results) ───
    new_ai_turn = pyqtSignal()

    # ── Completion / error ─────────────────────────────────────────────
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

    # ── Called from main thread to cancel the worker ───────────────────
    def stop(self):
        self._cancelled = True
        self._manual_queue.put({})  # unblock any waiting get()

    # ── Called from main thread to supply manual params ────────────────
    def supply_manual_params(self, params: dict):
        self._manual_queue.put(params)

    # ── Main loop ──────────────────────────────────────────────────────
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
                # Conversation complete
                self.finished.emit()
                return

            # Build assistant message (with tool_calls) for history
            # reasoning_content must be passed back for models that use thinking mode
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

            # Execute every tool call
            for tc in tool_calls:
                call_id = tc["id"]
                tool_name = tc["name"]
                ai_args = tc["arguments"]

                # Resolve params (manual > ai > config > default)
                manual_overrides: dict = {}
                manual_params = self._tm.get_manual_params(tool_name)
                if manual_params:
                    self.need_manual_params.emit(call_id, tool_name, manual_params)
                    try:
                        manual_overrides = self._manual_queue.get(timeout=120)
                    except queue.Empty:
                        manual_overrides = {}

                if tool_name in self._builtins:
                    # Built-in tool (e.g. create_scheduled_task)
                    resolved = {**ai_args, **manual_overrides}
                    self.tool_started.emit(call_id, tool_name, resolved)
                    result = self._builtins[tool_name](resolved)
                else:
                    resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
                    self.tool_started.emit(call_id, tool_name, resolved)
                    result = self._tm.execute(tool_name, resolved)

                self.tool_done.emit(call_id, result)

                # Add tool result to history
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )

            # Signal UI that AI is about to respond again
            self.new_ai_turn.emit()

        self.finished.emit()
