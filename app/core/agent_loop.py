"""
AgentLoop — 状态机驱动的 Agent 执行循环。

整体架构：
    AgentLoop 继承 QThread，在后台线程中运行状态机。
    状态机包含 5 个状态：PREPARE → STREAM → EXECUTE → FEEDBACK → DONE
    每个状态对应一个 _state_xxx 方法，返回事件字符串触发状态转移。
    通过 Qt 信号与 UI 层通信，保持线程安全。

工具执行：
    所有工具（内置 + 外部脚本）统一通过 ToolManager 调度。
    只读工具自动并发执行，有副作用工具串行执行。
"""
import json
import logging
import queue
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.llm_gateway import CancellationToken, LLMGateway
from app.core.checkpoint import clear_checkpoint, save_checkpoint
from app.tools.registry import ToolErrorType, ToolRegistry
from app.core.turn_context import (
    TRANSITIONS,
    StateTraceEntry,
    TurnContext,
    TurnState,
)

logger = logging.getLogger(__name__)

_MAX_WORKERS = 4

# 单工具连续失败超过此次数后强制终止 loop
_MAX_TOOL_FAILURES = 5

# 致命错误类型：检测到后终止 loop，不再进入下一轮 LLM 调用
_FATAL_ERROR_TYPES = {ToolErrorType.TOOL_NOT_FOUND, ToolErrorType.PERMISSION}


class AgentLoop(QThread):
    """
    状态机驱动的 Agent 循环，每次 turn 一个实例。

    所有工具统一通过 ToolRegistry 执行。
    """

    # ── Qt 信号 ──────────────────────────────────────────────────────────
    text_chunk = pyqtSignal(str)
    state_changed = pyqtSignal(str)
    tool_event = pyqtSignal(str, str, dict)
    need_input = pyqtSignal(str, str, list)
    new_turn = pyqtSignal(int)
    done = pyqtSignal(dict)

    def __init__(
        self,
        llm_gateway: LLMGateway,
        registry: ToolRegistry,
        api_messages: list[dict],
        session_id: str = "",
        max_turns: int = 10,
        parent=None,
    ):
        super().__init__(parent)
        self._llm = llm_gateway
        self._registry = registry
        self._messages = api_messages
        self._session_id = session_id
        self._max_turns = max_turns

        self._cancelled = False
        self._cancel_token = CancellationToken()
        self._input_queue: queue.Queue = queue.Queue()
        self._inject_queue: queue.Queue = queue.Queue()
        # 工具连续失败计数：{tool_name: count}
        self._tool_failure_counts: dict[str, int] = {}

    # ── 外部控制接口 ──────────────────────────────────────────────────────

    def cancel(self):
        """请求取消当前 turn。"""
        self._cancelled = True
        self._cancel_token.cancel()
        self._input_queue.put({})

    def supply_input(self, params: dict):
        """提供手动参数（响应 need_input 信号）。"""
        self._input_queue.put(params)

    def inject_message(self, message: dict):
        """Mid-turn 注入用户消息。"""
        self._inject_queue.put(message)

    # ── 状态机主驱动 ─────────────────────────────────────────────────────

    def run(self):
        """QThread 入口点 — 状态机主循环。"""
        ctx = TurnContext(
            messages=list(self._messages),
            tools=self._registry.get_openai_functions(),
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
                logger.debug("[AgentLoop] %s -> %s (%.1fms)", ctx.state.name, event, elapsed_ms)

                next_state = TRANSITIONS.get((ctx.state, event))
                if next_state is None:
                    logger.error("[AgentLoop] No transition for (%s, %s)", ctx.state.name, event)
                    ctx.state = TurnState.FINALIZE
                    ctx.error_message = f"Invalid transition: ({ctx.state.name}, {event})"
                    event = self._state_finalize(ctx)
                    ctx.state = TRANSITIONS[(TurnState.FINALIZE, event)]
                else:
                    ctx.state = next_state
        except Exception as e:
            logger.exception("[AgentLoop] Unhandled exception")
            self.done.emit({"ok": False, "error": str(e), "trace": self._serialize_trace(ctx)})
            return

    # ── State Handlers ───────────────────────────────────────────────────

    def _state_prepare(self, ctx: TurnContext) -> str:
        if not ctx.messages:
            return "empty"
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        ctx.reset_turn()

        for chunk in self._llm.chat_stream(
            ctx.messages,
            ctx.tools,
            cancel_token=self._cancel_token,
        ):
            if self._cancelled:
                return "cancelled"

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
        """执行工具调用：自动分区并发/串行，统一走 ToolRegistry。"""
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

        batches = self._partition_batches(ctx.tool_calls)
        completed_results: list[dict] = []

        for mode, batch in batches:
            if self._cancelled:
                return "cancelled"

            if mode == "concurrent" and len(batch) > 1:
                batch_results = self._execute_concurrent_batch(batch)
            else:
                batch_results = []
                for tc in batch:
                    if self._cancelled:
                        return "cancelled"
                    result = self._execute_one(tc)
                    if result is None:
                        return "cancelled"
                    batch_results.append((tc, result))

            for tc, result in batch_results:
                tool_name = tc["name"]
                if result.get("status") == "error":
                    self._tool_failure_counts[tool_name] = (
                        self._tool_failure_counts.get(tool_name, 0) + 1
                    )
                    error_type_val = result.get("data", {}).get("error_type", "")
                    try:
                        error_type = ToolErrorType(error_type_val)
                    except ValueError:
                        error_type = ToolErrorType.RUNTIME

                    if error_type in _FATAL_ERROR_TYPES:
                        logger.error(
                            "[AgentLoop] Fatal tool error (%s): %s — %s",
                            error_type.value, tool_name, result["data"].get("message"),
                        )
                        ctx.messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": ToolRegistry.format_result(result),
                        })
                        ctx.error_message = (
                            f"工具 {tool_name} 发生致命错误 ({error_type.value}): "
                            f"{result['data'].get('message', '')}"
                        )
                        return "error"

                    if self._tool_failure_counts[tool_name] >= _MAX_TOOL_FAILURES:
                        logger.error(
                            "[AgentLoop] Tool %s failed %d times, terminating loop",
                            tool_name, _MAX_TOOL_FAILURES,
                        )
                        ctx.error_message = (
                            f"工具 {tool_name} 连续失败 {_MAX_TOOL_FAILURES} 次，终止执行"
                        )
                        return "error"
                else:
                    self._tool_failure_counts.pop(tool_name, None)

                content = ToolRegistry.format_result(result)
                tool_msg = {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": content,
                }
                ctx.messages.append(tool_msg)
                completed_results.append(tool_msg)

            if self._session_id:
                remaining = self._get_remaining_calls(ctx.tool_calls, batch, batches)
                if remaining:
                    save_checkpoint(
                        self._session_id,
                        ctx.messages,
                        assistant_msg,
                        completed_results,
                        [{"id": t["id"], "name": t["name"]} for t in remaining],
                    )

        if self._session_id:
            clear_checkpoint(self._session_id)

        return "ok"

    def _state_feedback(self, ctx: TurnContext) -> str:
        ctx.turn_count += 1

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
        trace_data = self._serialize_trace(ctx)
        if ctx.error_message:
            self.done.emit({"ok": False, "error": ctx.error_message, "trace": trace_data})
        else:
            self.done.emit({"ok": True, "error": None, "trace": trace_data})
        return "ok"

    # ── 工具执行辅助 ─────────────────────────────────────────────────────

    def _partition_batches(self, tool_calls: list[dict]) -> list[tuple[str, list[dict]]]:
        """将工具调用分区为并发/串行批次。"""
        batches: list[tuple[str, list[dict]]] = []
        current_concurrent: list[dict] = []

        for tc in tool_calls:
            tool = self._registry.get(tc["name"])
            is_ro = tool.read_only if tool else False

            if is_ro:
                current_concurrent.append(tc)
            else:
                if current_concurrent:
                    batches.append(("concurrent", current_concurrent))
                    current_concurrent = []
                batches.append(("serial", [tc]))

        if current_concurrent:
            batches.append(("concurrent", current_concurrent))

        return batches

    def _execute_one(self, tc: dict) -> dict | None:
        """执行单个工具调用。"""
        call_id = tc["id"]
        tool_name = tc["name"]
        ai_args = tc["arguments"]

        # 注入 session_id 供 memory 等工具使用（不在 schema 中，LLM 不可见）
        if self._session_id:
            ai_args["_session_id"] = self._session_id

        # 执行
        self.tool_event.emit(call_id, "start", {"name": tool_name, "params": ai_args})
        result = self._registry.execute(tool_name, ai_args)
        self.tool_event.emit(call_id, "done", {"name": tool_name, "result": result})
        return result

    def _execute_concurrent_batch(self, batch: list[dict]) -> list[tuple[dict, dict]]:
        """并发执行一批只读工具。"""
        results: list[tuple[dict, dict] | None] = [None] * len(batch)

        for tc in batch:
            # 注入 session_id 供 memory 等工具使用
            if self._session_id:
                tc["arguments"]["_session_id"] = self._session_id
            self.tool_event.emit(tc["id"], "start", {"name": tc["name"], "params": tc["arguments"]})

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            future_to_idx = {}
            for i, tc in enumerate(batch):
                future = pool.submit(self._registry.execute, tc["name"], tc["arguments"])
                future_to_idx[future] = i

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                tc = batch[idx]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"status": "error", "data": {"message": str(e)}}
                results[idx] = (tc, result)
                self.tool_event.emit(tc["id"], "done", {"name": tc["name"], "result": result})

        return results

    def _get_remaining_calls(
        self, all_calls: list[dict], current_batch: list[dict],
        all_batches: list[tuple[str, list[dict]]]
    ) -> list[dict]:
        """获取当前批次之后尚未执行的工具调用。"""
        done_ids = {tc["id"] for tc in current_batch}
        # 找到当前批次在 all_batches 中的位置之后的所有调用
        found = False
        remaining = []
        for _, batch in all_batches:
            if not found:
                if batch is current_batch:
                    found = True
                continue
            remaining.extend(batch)
        return remaining

    # ── 工具方法 ─────────────────────────────────────────────────────────

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
