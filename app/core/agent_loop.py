"""
AgentLoop — 状态机驱动的 Agent 执行循环。

替代原 ChatWorker 的线性 for 循环，提供：
- 显式状态流转和追踪
- Checkpoint 崩溃恢复
- Mid-turn 消息注入
- 可配置最大轮次
"""
import json
import logging
import queue
import time

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.ai_client import AIClient
from app.core.checkpoint import clear_checkpoint, save_checkpoint
from app.core.tool_manager import ToolManager
from app.core.turn_context import (
    TRANSITIONS,
    StateTraceEntry,
    TurnContext,
    TurnState,
)

logger = logging.getLogger(__name__)


class AgentLoop(QThread):
    """状态机驱动的 Agent 循环，每次 turn 一个实例。"""

    # ── 流式文本 ──
    text_chunk = pyqtSignal(str)

    # ── 状态变化 ──
    state_changed = pyqtSignal(str)  # state name

    # ── 工具事件：call_id, phase("start"|"done"|"error"), payload ──
    tool_event = pyqtSignal(str, str, dict)

    # ── 需要用户手动输入参数 ──
    need_input = pyqtSignal(str, str, list)  # call_id, tool_name, param_names

    # ── 新一轮 AI 回复开始 ──
    new_turn = pyqtSignal(int)  # turn_count

    # ── 终止（统一出口）──
    done = pyqtSignal(dict)  # {"ok": bool, "error": str|None, "trace": list}

    def __init__(
        self,
        ai_client: AIClient,
        tool_manager: ToolManager,
        api_messages: list[dict],
        tools: list[dict] | None,
        builtin_handlers: dict[str, callable],
        session_id: str = "",
        max_turns: int = 10,
        parent=None,
    ):
        super().__init__(parent)
        self._ai = ai_client
        self._tm = tool_manager
        self._messages = api_messages
        self._tools = tools
        self._builtins = builtin_handlers
        self._session_id = session_id
        self._max_turns = max_turns

        self._cancelled = False
        self._input_queue: queue.Queue = queue.Queue()
        self._inject_queue: queue.Queue = queue.Queue()

    # ── 外部控制接口 ──────────────────────────────────────────────────

    def cancel(self):
        """请求取消当前 turn。"""
        self._cancelled = True
        self._input_queue.put({})  # unblock waiting get()

    def supply_input(self, params: dict):
        """提供手动参数（响应 need_input 信号）。"""
        self._input_queue.put(params)

    def inject_message(self, message: dict):
        """Mid-turn 注入用户消息，下一轮 STREAM 时会包含。"""
        self._inject_queue.put(message)

    # ── 状态机主驱动 ─────────────────────────────────────────────────

    def run(self):
        ctx = TurnContext(
            messages=list(self._messages),
            tools=self._tools,
            max_turns=self._max_turns,
        )
        try:
            while ctx.state is not TurnState.DONE:
                if self._cancelled:
                    ctx.error_message = None
                    ctx.state = TurnState.FINALIZE
                    if ctx.state is TurnState.DONE:
                        break

                handler = getattr(self, f"_state_{ctx.state.name.lower()}")
                self.state_changed.emit(ctx.state.name)

                t0 = time.perf_counter()
                event = handler(ctx)
                elapsed_ms = (time.perf_counter() - t0) * 1000

                ctx.trace.append(StateTraceEntry(
                    state=ctx.state, event=event, duration_ms=elapsed_ms
                ))
                logger.debug(
                    "[AgentLoop] %s -> %s (%.1fms)",
                    ctx.state.name, event, elapsed_ms,
                )

                next_state = TRANSITIONS.get((ctx.state, event))
                if next_state is None:
                    logger.error(
                        "[AgentLoop] No transition for (%s, %s)", ctx.state.name, event
                    )
                    ctx.state = TurnState.FINALIZE
                    ctx.error_message = f"Invalid transition: ({ctx.state.name}, {event})"
                    # finalize 会处理
                    event = self._state_finalize(ctx)
                    ctx.state = TRANSITIONS[(TurnState.FINALIZE, event)]
                else:
                    ctx.state = next_state
        except Exception as e:
            logger.exception("[AgentLoop] Unhandled exception")
            self.done.emit({"ok": False, "error": str(e), "trace": self._serialize_trace(ctx)})
            return

        # 正常结束已由 _state_finalize 发出 done 信号

    # ── State Handlers ───────────────────────────────────────────────

    def _state_prepare(self, ctx: TurnContext) -> str:
        """校验输入，准备首轮。"""
        if not ctx.messages:
            return "empty"
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        """调用 LLM 流式对话，收集文本和工具调用。"""
        ctx.reset_turn()

        for chunk in self._ai.chat_stream(ctx.messages, ctx.tools):
            if self._cancelled:
                return "error"

            if chunk["type"] == "text":
                ctx.full_text += chunk["delta"]
                self.text_chunk.emit(chunk["delta"])
            elif chunk["type"] == "tool_call":
                ctx.tool_calls.append(chunk)
            elif chunk["type"] == "error":
                ctx.error_message = chunk["message"]
                return "error"
            elif chunk["type"] == "done":
                ctx.reasoning_content = chunk.get("reasoning_content")
                break

        if not ctx.tool_calls:
            return "no_tools"
        return "has_tools"

    def _state_execute(self, ctx: TurnContext) -> str:
        """执行所有工具调用，逐个发出事件，写 checkpoint。"""
        # 构建 assistant 消息
        assistant_msg: dict = {
            "role": "assistant",
            "content": ctx.full_text or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in ctx.tool_calls
            ],
        }
        if ctx.reasoning_content:
            assistant_msg["reasoning_content"] = ctx.reasoning_content
        ctx.messages.append(assistant_msg)

        completed_results: list[dict] = []

        for i, tc in enumerate(ctx.tool_calls):
            if self._cancelled:
                return "cancelled"

            call_id = tc["id"]
            tool_name = tc["name"]
            ai_args = tc["arguments"]

            # 手动参数
            manual_overrides: dict = {}
            manual_params = self._tm.get_manual_params(tool_name)
            if manual_params:
                self.need_input.emit(call_id, tool_name, manual_params)
                try:
                    manual_overrides = self._input_queue.get(timeout=120)
                except queue.Empty:
                    manual_overrides = {}
                if self._cancelled:
                    return "cancelled"

            # 执行
            if tool_name in self._builtins:
                resolved = {**ai_args, **manual_overrides}
                self.tool_event.emit(call_id, "start", {"name": tool_name, "params": resolved})
                result = self._builtins[tool_name](resolved)
            else:
                resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
                self.tool_event.emit(call_id, "start", {"name": tool_name, "params": resolved})
                result = self._tm.execute(tool_name, resolved)

            self.tool_event.emit(call_id, "done", {"name": tool_name, "result": result})

            # 工具结果消息
            tool_msg = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            }
            ctx.messages.append(tool_msg)
            completed_results.append(tool_msg)

            # Checkpoint：每完成一个工具后保存
            pending = ctx.tool_calls[i + 1:]
            if self._session_id and pending:
                save_checkpoint(
                    self._session_id,
                    ctx.messages,
                    assistant_msg,
                    completed_results,
                    [{"id": t["id"], "name": t["name"]} for t in pending],
                )

        # 所有工具执行完毕，清除 checkpoint
        if self._session_id:
            clear_checkpoint(self._session_id)

        return "ok"

    def _state_feedback(self, ctx: TurnContext) -> str:
        """将工具结果反馈给 AI，检查轮次和注入消息。"""
        ctx.turn_count += 1

        # Mid-turn 注入：将用户追加的消息插入
        while not self._inject_queue.empty():
            try:
                msg = self._inject_queue.get_nowait()
                ctx.messages.append(msg)
            except queue.Empty:
                break

        if ctx.turn_count >= ctx.max_turns:
            return "max_turns"

        self.new_turn.emit(ctx.turn_count)
        return "continue"

    def _state_finalize(self, ctx: TurnContext) -> str:
        """发出终止信号。"""
        trace_data = self._serialize_trace(ctx)
        if ctx.error_message:
            self.done.emit({"ok": False, "error": ctx.error_message, "trace": trace_data})
        else:
            self.done.emit({"ok": True, "error": None, "trace": trace_data})
        return "ok"

    # ── 工具方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _serialize_trace(ctx: TurnContext) -> list[dict]:
        return [
            {
                "state": entry.state.name,
                "event": entry.event,
                "duration_ms": round(entry.duration_ms, 1),
            }
            for entry in ctx.trace
        ]