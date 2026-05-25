"""
AgentLoop — 状态机驱动的 Agent 执行循环。

替代原 ChatWorker 的线性 for 循环，提供：
- 显式状态流转和追踪
- Checkpoint 崩溃恢复
- Mid-turn 消息注入
- 可配置最大轮次

整体架构：
    AgentLoop 继承 QThread，在后台线程中运行状态机。
    状态机包含 5 个状态：PREPARE → STREAM → EXECUTE → FEEDBACK → DONE
    每个状态对应一个 _state_xxx 方法，返回事件字符串触发状态转移。
    通过 Qt 信号与 UI 层通信，保持线程安全。
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
    TRANSITIONS,       # 状态转移表：(当前状态, 事件) → 下一状态
    StateTraceEntry,   # 状态追踪条目（用于调试和日志）
    TurnContext,       # 单次 turn 的上下文容器
    TurnState,         # 状态枚举：PREPARE, STREAM, EXECUTE, FEEDBACK, FINALIZE, DONE
)

logger = logging.getLogger(__name__)


class AgentLoop(QThread):
    """
    状态机驱动的 Agent 循环，每次 turn 一个实例。

    生命周期：
        1. 外部创建 AgentLoop 实例，传入 AI 客户端、工具管理器、消息历史等
        2. 调用 start() 启动后台线程，进入 run() 方法
        3. 状态机循环执行，通过信号通知 UI 层进度
        4. 循环结束后发出 done 信号，线程退出

    线程安全：
        - 所有与 UI 的通信通过 pyqtSignal（跨线程安全）
        - 外部控制通过 queue.Queue（线程安全的阻塞队列）
    """

    # ── Qt 信号定义 ──────────────────────────────────────────────────

    # 流式文本：每收到一个 token 片段就发射，UI 层拼接显示
    text_chunk = pyqtSignal(str)

    # 状态变化：每次进入新状态时发射状态名，用于 UI 状态指示器
    state_changed = pyqtSignal(str)  # state name

    # 工具事件：通知 UI 工具执行的生命周期
    # 参数：call_id（工具调用唯一标识）, phase("start"|"done"|"error"), payload（详情字典）
    tool_event = pyqtSignal(str, str, dict)

    # 需要用户手动输入参数：某些工具需要用户提供额外参数（如密码、确认等）
    # 参数：call_id, tool_name, param_names（需要用户填写的参数名列表）
    need_input = pyqtSignal(str, str, list)

    # 新一轮 AI 回复开始：用于 UI 显示轮次计数
    new_turn = pyqtSignal(int)  # turn_count

    # 终止信号（统一出口）：无论成功还是失败，最终都通过此信号通知外部
    # payload: {"ok": bool, "error": str|None, "trace": list}
    done = pyqtSignal(dict)

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
        """
        初始化 AgentLoop。

        Args:
            ai_client: AI 客户端，负责与 LLM API 通信
            tool_manager: 工具管理器，负责工具注册、参数解析和执行
            api_messages: 当前对话的消息历史（OpenAI 格式）
            tools: 工具定义列表（JSON Schema 格式），传给 LLM 让它知道可用工具
            builtin_handlers: 内置工具处理函数字典，key=工具名, value=处理函数
                             内置工具不经过 tool_manager，直接调用对应函数
            session_id: 会话 ID，用于 checkpoint 持久化（空字符串表示不保存）
            max_turns: 最大轮次限制，防止 Agent 无限循环
            parent: Qt 父对象
        """
        super().__init__(parent)
        self._ai = ai_client
        self._tm = tool_manager
        self._messages = api_messages
        self._tools = tools
        self._builtins = builtin_handlers
        self._session_id = session_id
        self._max_turns = max_turns

        self._cancelled = False                        # 取消标志，外部调用 cancel() 设置
        self._input_queue: queue.Queue = queue.Queue() # 用户手动输入参数的阻塞队列
        self._inject_queue: queue.Queue = queue.Queue()  # Mid-turn 消息注入队列

    # ── 外部控制接口 ──────────────────────────────────────────────────
    # 这些方法由 UI 线程调用，通过线程安全的队列/标志与后台线程通信

    def cancel(self):
        """
        请求取消当前 turn。

        设置取消标志并向 input_queue 放入空字典以解除可能的阻塞等待。
        状态机主循环会在每次迭代开始检查此标志。
        """
        self._cancelled = True
        self._input_queue.put({})  # 解除 supply_input 的阻塞等待

    def supply_input(self, params: dict):
        """
        提供手动参数（响应 need_input 信号）。

        当某个工具需要用户手动输入参数时，UI 层收到 need_input 信号后
        弹出输入对话框，用户填写后调用此方法将参数传回后台线程。
        """
        self._input_queue.put(params)

    def inject_message(self, message: dict):
        """
        Mid-turn 注入用户消息。

        允许用户在 Agent 执行工具期间追加新消息，这些消息会在下一轮
        STREAM 之前被插入到消息历史中，让 AI 能看到用户的补充指令。
        """
        self._inject_queue.put(message)

    # ── 状态机主驱动 ─────────────────────────────────────────────────
    # 核心循环：根据当前状态调用对应 handler，handler 返回事件，
    # 事件 + 当前状态查表得到下一状态，循环直到 DONE。

    def run(self):
        """
        QThread 入口点 — 状态机主循环。

        流程：
            1. 创建 TurnContext 作为本次执行的上下文容器
            2. 循环：检查取消 → 调用状态处理器 → 记录 trace → 查表转移状态
            3. 异常兜底：未捕获的异常通过 done 信号报告错误
        """
        ctx = TurnContext(
            messages=list(self._messages),  # 复制消息列表，避免修改外部引用
            tools=self._tools,
            max_turns=self._max_turns,
        )
        try:
            while ctx.state is not TurnState.DONE:
                # 检查取消标志：如果被取消，跳转到 FINALIZE 状态清理退出
                if self._cancelled:
                    ctx.error_message = None  # 取消不算错误
                    ctx.state = TurnState.FINALIZE
                    if ctx.state is TurnState.DONE:
                        break

                # 通过反射找到当前状态对应的处理方法（如 _state_stream）
                handler = getattr(self, f"_state_{ctx.state.name.lower()}")
                # 通知 UI 当前状态
                self.state_changed.emit(ctx.state.name)

                # 执行状态处理器并计时
                t0 = time.perf_counter()
                event = handler(ctx)
                elapsed_ms = (time.perf_counter() - t0) * 1000

                # 记录状态追踪信息（用于调试和性能分析）
                ctx.trace.append(StateTraceEntry(
                    state=ctx.state, event=event, duration_ms=elapsed_ms
                ))
                logger.debug(
                    "[AgentLoop] %s -> %s (%.1fms)",
                    ctx.state.name, event, elapsed_ms,
                )

                # 查状态转移表，确定下一状态
                next_state = TRANSITIONS.get((ctx.state, event))
                if next_state is None:
                    # 无效转移：说明状态机定义有遗漏，进入错误处理
                    logger.error(
                        "[AgentLoop] No transition for (%s, %s)", ctx.state.name, event
                    )
                    ctx.state = TurnState.FINALIZE
                    ctx.error_message = f"Invalid transition: ({ctx.state.name}, {event})"
                    # 直接执行 finalize 并手动转移到 DONE
                    event = self._state_finalize(ctx)
                    ctx.state = TRANSITIONS[(TurnState.FINALIZE, event)]
                else:
                    ctx.state = next_state
        except Exception as e:
            # 兜底异常处理：确保任何未预期的错误都能通知 UI
            logger.exception("[AgentLoop] Unhandled exception")
            self.done.emit({"ok": False, "error": str(e), "trace": self._serialize_trace(ctx)})
            return

        # 正常结束：done 信号已由 _state_finalize 发出

    # ── State Handlers ───────────────────────────────────────────────
    # 每个 handler 对应一个状态，返回事件字符串用于查表转移。
    # 命名规则：_state_{状态名小写}

    def _state_prepare(self, ctx: TurnContext) -> str:
        """
        PREPARE 状态：校验输入，准备首轮。

        检查消息列表是否为空：
        - 空消息 → 返回 "empty" 事件，转移到 FINALIZE
        - 有消息 → 重置 turn 级别的临时变量，返回 "ok" 转移到 STREAM
        """
        if not ctx.messages:
            return "empty"
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        """
        STREAM 状态：调用 LLM 流式对话，收集文本和工具调用。

        通过 ai_client.chat_stream() 获取流式响应，逐 chunk 处理：
        - "text" chunk：累积到 full_text，同时通过信号实时推送给 UI
        - "tool_call" chunk：收集到 tool_calls 列表
        - "error" chunk：记录错误信息，返回 "error"
        - "done" chunk：流结束，保存 reasoning_content（思维链内容）

        返回事件：
        - "has_tools"：AI 请求调用工具 → 转移到 EXECUTE
        - "no_tools"：AI 纯文本回复 → 转移到 FINALIZE（本轮结束）
        - "error"：出错或被取消 → 转移到 FINALIZE
        """
        ctx.reset_turn()  # 清空上一轮的 full_text 和 tool_calls

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
        """
        EXECUTE 状态：执行所有工具调用，逐个发出事件，写 checkpoint。

        执行流程：
            1. 构建 assistant 消息（包含文本 + tool_calls），追加到消息历史
            2. 遍历每个工具调用：
               a. 检查是否需要用户手动输入参数（如密码）
               b. 区分内置工具和外部工具，分别执行
               c. 发射 tool_event 信号通知 UI 执行进度
               d. 将工具结果作为 tool 消息追加到消息历史
               e. 保存 checkpoint（用于崩溃恢复）
            3. 全部执行完毕后清除 checkpoint

        Checkpoint 机制：
            每完成一个工具后保存当前进度（已完成的结果 + 待执行的工具列表）。
            如果进程崩溃，下次启动时可以从 checkpoint 恢复，跳过已完成的工具。

        返回事件：
        - "ok"：所有工具执行完毕 → 转移到 FEEDBACK
        - "cancelled"：执行过程中被取消 → 转移到 FINALIZE
        """
        # 构建 assistant 消息（OpenAI 格式：content + tool_calls）
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
        # 如果有思维链内容，也保存到消息中（用于调试和日志）
        if ctx.reasoning_content:
            assistant_msg["reasoning_content"] = ctx.reasoning_content
        ctx.messages.append(assistant_msg)

        completed_results: list[dict] = []  # 已完成的工具结果，用于 checkpoint

        for i, tc in enumerate(ctx.tool_calls):
            if self._cancelled:
                return "cancelled"

            call_id = tc["id"]       # 工具调用的唯一标识（由 LLM 生成）
            tool_name = tc["name"]   # 工具名称
            ai_args = tc["arguments"]  # LLM 提供的参数

            # ── 手动参数处理 ──
            # 某些工具的部分参数需要用户手动输入（如 API key、确认操作等）
            manual_overrides: dict = {}
            manual_params = self._tm.get_manual_params(tool_name)
            if manual_params:
                # 发信号通知 UI 弹出输入框，然后阻塞等待用户输入
                self.need_input.emit(call_id, tool_name, manual_params)
                try:
                    manual_overrides = self._input_queue.get(timeout=120)  # 最多等 2 分钟
                except queue.Empty:
                    manual_overrides = {}
                if self._cancelled:
                    return "cancelled"

            # ── 执行工具 ──
            if tool_name in self._builtins:
                # 内置工具：直接合并参数后调用处理函数
                resolved = {**ai_args, **manual_overrides}
                self.tool_event.emit(call_id, "start", {"name": tool_name, "params": resolved})
                result = self._builtins[tool_name](resolved)
            else:
                # 外部工具：通过 tool_manager 解析参数并执行
                resolved = self._tm.resolve_params(tool_name, ai_args, manual_overrides)
                self.tool_event.emit(call_id, "start", {"name": tool_name, "params": resolved})
                result = self._tm.execute(tool_name, resolved)

            # 通知 UI 工具执行完成
            self.tool_event.emit(call_id, "done", {"name": tool_name, "result": result})

            # ── 构建工具结果消息并追加到消息历史 ──
            tool_msg = {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result, ensure_ascii=False),
            }
            ctx.messages.append(tool_msg)
            completed_results.append(tool_msg)

            # ── Checkpoint：每完成一个工具后保存进度 ──
            # 只在还有待执行工具时保存（最后一个工具完成后直接清除）
            pending = ctx.tool_calls[i + 1:]
            if self._session_id and pending:
                save_checkpoint(
                    self._session_id,
                    ctx.messages,
                    assistant_msg,
                    completed_results,
                    [{"id": t["id"], "name": t["name"]} for t in pending],
                )

        # 所有工具执行完毕，清除 checkpoint（表示本轮工具执行已完整完成）
        if self._session_id:
            clear_checkpoint(self._session_id)

        return "ok"

    def _state_feedback(self, ctx: TurnContext) -> str:
        """
        FEEDBACK 状态：工具执行完毕后的反馈处理。

        职责：
            1. 递增轮次计数
            2. 处理 mid-turn 注入的用户消息（从注入队列中取出并追加到消息历史）
            3. 检查是否达到最大轮次限制

        返回事件：
        - "max_turns"：达到最大轮次 → 转移到 FINALIZE（强制结束）
        - "continue"：未达上限 → 转移回 STREAM（开始下一轮 AI 对话）
        """
        ctx.turn_count += 1

        # Mid-turn 注入：将用户在工具执行期间追加的消息插入消息历史
        # 这样下一轮 STREAM 时 AI 能看到这些补充指令
        while not self._inject_queue.empty():
            try:
                msg = self._inject_queue.get_nowait()
                ctx.messages.append(msg)
            except queue.Empty:
                break

        # 轮次限制检查：防止 Agent 陷入无限工具调用循环
        if ctx.turn_count >= ctx.max_turns:
            return "max_turns"

        # 通知 UI 新一轮开始
        self.new_turn.emit(ctx.turn_count)
        return "continue"

    def _state_finalize(self, ctx: TurnContext) -> str:
        """
        FINALIZE 状态：发出终止信号，清理资源。

        这是状态机的统一出口，无论成功、失败还是取消都会经过这里。
        通过 done 信号将最终结果通知 UI 层。

        返回事件：
        - "ok"：始终返回 "ok" → 转移到 DONE（状态机终止）
        """
        trace_data = self._serialize_trace(ctx)
        if ctx.error_message:
            self.done.emit({"ok": False, "error": ctx.error_message, "trace": trace_data})
        else:
            self.done.emit({"ok": True, "error": None, "trace": trace_data})
        return "ok"

    # ── 工具方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _serialize_trace(ctx: TurnContext) -> list[dict]:
        """
        将状态追踪记录序列化为可 JSON 化的字典列表。

        用于 done 信号的 payload，方便 UI 层或日志系统记录完整的状态流转历史。
        """
        return [
            {
                "state": entry.state.name,
                "event": entry.event,
                "duration_ms": round(entry.duration_ms, 1),
            }
            for entry in ctx.trace
        ]