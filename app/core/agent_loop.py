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
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.llm_gateway import CancellationToken, LLMGateway
from app.core.checkpoint import clear_checkpoint, save_checkpoint
from app.core.agent_hooks import (
    AfterIterationContext,
    AgentHook,
    BeforeToolsContext,
    CompositeHook,
    ToolCallView,
    reject as _reject,
)
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
        trace_store=None,
        hooks: list[AgentHook] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self._llm = llm_gateway
        self._registry = registry
        self._messages = api_messages
        self._session_id = session_id
        self._max_turns = max_turns
        # 统一 trace：本次 run 一个 trace_id，贯穿 LLM 调用与工具调用。
        self._trace_store = trace_store
        self._trace_id = uuid.uuid4().hex
        # 同一 turn 内 LLM 往返序号，供回放排序。
        self._llm_seq = 0
        # 生命周期 hook（评测埋点 / 安全审批等横切关注点）。
        self._hook = CompositeHook(hooks) if hooks else None

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
        self._trace_start_turn()
        run_t0 = time.perf_counter()
        try:
            while ctx.state is not TurnState.DONE:
                if self._cancelled:
                    ctx.error_message = None
                    ctx.state = TurnState.FINALIZE
                    if ctx.state is TurnState.DONE:
                        break
                # 取当前状态对应的handler
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
            self._trace_finish_turn(ctx, "error", run_t0, error=str(e))
            self.done.emit({"ok": False, "error": str(e), "trace": self._serialize_trace(ctx)})
            return

        status = "cancelled" if self._cancelled else ("error" if ctx.error_message else "ok")
        self._trace_finish_turn(ctx, status, run_t0, error=ctx.error_message)

    # ── State Handlers ───────────────────────────────────────────────────

    def _state_prepare(self, ctx: TurnContext) -> str:
        if not ctx.messages:
            return "empty"
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        ctx.reset_turn()

        seq = self._llm_seq
        self._llm_seq += 1
        for chunk in self._llm.chat_stream(
            ctx.messages,
            ctx.tools,
            cancel_token=self._cancel_token,
            trace_id=self._trace_id,
            seq=seq,
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
                self._fire_after_iteration(ctx, [])
                return "error"
            elif chunk["type"] == "done":
                ctx.reasoning_content = chunk.get("reasoning_content")
                break

        if not ctx.tool_calls:
            # 纯文本收尾轮（无工具）：也触发 after_iteration，让评测能捕获最终答复。
            self._fire_after_iteration(ctx, [])
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

        # 安全审批挂载点：hook 可对即将执行的工具调用裁决（放行/软拒绝）。
        rejections = self._apply_before_tools_hook(ctx)
        # 收集本轮所有 (tool_call, result) 供 after_iteration 评测埋点使用。
        iteration_results: list[tuple[dict, dict]] = []

        # 被软拒绝的调用：不执行，直接回灌拒绝说明作为工具结果。
        pending_calls = []
        for tc in ctx.tool_calls:
            decision = rejections.get(tc["id"])
            if decision is not None:
                reject_result = {
                    "status": "error",
                    "data": {
                        "message": decision.message or "该工具调用被安全策略拒绝。",
                        "error_type": ToolErrorType.PERMISSION.value,
                        "retryable": False,
                        "rejected_by_hook": True,
                    },
                }
                ctx.messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": ToolRegistry.format_result(reject_result),
                })
                iteration_results.append((tc, reject_result))
                self._trace_tool_call(
                    tc["id"], tc["name"], tc["arguments"], reject_result, 0.0
                )
            else:
                pending_calls.append(tc)

        batches = self._partition_batches(pending_calls)
        completed_results: list[dict] = []

        for mode, batch in batches:
            if self._cancelled:
                self._fire_after_iteration(ctx, iteration_results)
                return "cancelled"

            if mode == "concurrent" and len(batch) > 1:
                batch_results = self._execute_concurrent_batch(batch)
            else:
                batch_results = []
                for tc in batch:
                    if self._cancelled:
                        self._fire_after_iteration(ctx, iteration_results)
                        return "cancelled"
                    result = self._execute_one(tc)
                    if result is None:
                        self._fire_after_iteration(ctx, iteration_results)
                        return "cancelled"
                    batch_results.append((tc, result))

            for tc, result in batch_results:
                iteration_results.append((tc, result))
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
                        self._fire_after_iteration(ctx, iteration_results)
                        return "error"

                    if self._tool_failure_counts[tool_name] >= _MAX_TOOL_FAILURES:
                        logger.error(
                            "[AgentLoop] Tool %s failed %d times, terminating loop",
                            tool_name, _MAX_TOOL_FAILURES,
                        )
                        ctx.error_message = (
                            f"工具 {tool_name} 连续失败 {_MAX_TOOL_FAILURES} 次，终止执行"
                        )
                        self._fire_after_iteration(ctx, iteration_results)
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
                remaining = self._get_remaining_calls(pending_calls, batch, batches)
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

        self._fire_after_iteration(ctx, iteration_results)
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
        t0 = time.perf_counter()
        result = self._registry.execute(tool_name, ai_args)
        duration_ms = (time.perf_counter() - t0) * 1000
        self.tool_event.emit(call_id, "done", {"name": tool_name, "result": result})
        self._trace_tool_call(call_id, tool_name, ai_args, result, duration_ms)
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
            start_times: dict[int, float] = {}
            for i, tc in enumerate(batch):
                start_times[i] = time.perf_counter()
                future = pool.submit(self._registry.execute, tc["name"], tc["arguments"])
                future_to_idx[future] = i

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                tc = batch[idx]
                try:
                    result = future.result()
                except Exception as e:
                    result = {"status": "error", "data": {"message": str(e)}}
                duration_ms = (time.perf_counter() - start_times[idx]) * 1000
                results[idx] = (tc, result)
                self.tool_event.emit(tc["id"], "done", {"name": tc["name"], "result": result})
                self._trace_tool_call(
                    tc["id"], tc["name"], tc["arguments"], result, duration_ms
                )

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

    def _apply_before_tools_hook(self, ctx: TurnContext) -> dict:
        """调用 before_execute_tools，返回 {call_id: ToolDecision} 的拒绝映射。

        hook 为 None 或全部放行时返回空 dict。安全 hook（reraise=True）抛出
        异常时，记录致命错误并拒绝本轮全部工具调用，避免「审批失败却照常执行」。
        """
        if self._hook is None:
            return {}
        views = [
            ToolCallView(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in ctx.tool_calls
        ]
        hook_ctx = BeforeToolsContext(
            trace_id=self._trace_id,
            session_id=self._session_id,
            turn_count=ctx.turn_count,
            tool_calls=views,
        )
        try:
            decisions = self._hook.before_execute_tools(hook_ctx)
        except Exception as exc:
            logger.exception("[AgentLoop] before_execute_tools hook raised; rejecting all")
            msg = f"安全审批异常，工具调用被拒绝: {exc}"
            return {tc["id"]: _reject(tc["id"], msg) for tc in ctx.tool_calls}
        if not decisions:
            return {}
        return {d.call_id: d for d in decisions if d.is_reject}

    def _fire_after_iteration(
        self, ctx: TurnContext, results: list[tuple[dict, dict]]
    ) -> None:
        """触发 after_iteration 评测埋点。非 reraise hook 的异常已在内部隔离。"""
        if self._hook is None:
            return
        hook_ctx = AfterIterationContext(
            trace_id=self._trace_id,
            session_id=self._session_id,
            turn_count=ctx.turn_count,
            full_text=ctx.full_text,
            tool_calls=[
                ToolCallView(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc, _ in results
            ],
            tool_results=[result for _, result in results],
            error=ctx.error_message,
        )
        try:
            self._hook.after_iteration(hook_ctx)
        except Exception:
            logger.exception("[AgentLoop] after_iteration hook raised")

    def _trace_start_turn(self) -> None:
        if self._trace_store is None:
            return
        try:
            self._trace_store.start_turn(self._trace_id, self._session_id)
        except Exception:
            logger.debug("[AgentLoop] trace start_turn failed", exc_info=True)

    def _trace_finish_turn(
        self, ctx: TurnContext, status: str, run_t0: float, error: str | None = None
    ) -> None:
        if self._trace_store is None:
            return
        duration_ms = (time.perf_counter() - run_t0) * 1000
        try:
            self._trace_store.record_state_trace(self._trace_id, self._serialize_trace(ctx))
            self._trace_store.finish_turn(
                self._trace_id,
                status=status,
                turn_count=ctx.turn_count,
                duration_ms=duration_ms,
                error=error,
            )
        except Exception:
            logger.debug("[AgentLoop] trace finish_turn failed", exc_info=True)

    def _trace_tool_call(
        self, call_id: str, name: str, arguments: dict, result: dict | None, duration_ms: float
    ) -> None:
        if self._trace_store is None:
            return
        try:
            self._trace_store.record_tool_call(
                self._trace_id,
                call_id=call_id,
                name=name,
                arguments=arguments,
                result=result,
                duration_ms=duration_ms,
            )
        except Exception:
            logger.debug("[AgentLoop] trace record_tool_call failed", exc_info=True)

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
