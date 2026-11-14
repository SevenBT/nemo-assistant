"""
Agent — 纯 Python 状态机驱动的 Agent 执行循环（零 Qt 依赖）。

与 AgentThread 共享相同的 TurnState、TRANSITIONS、TurnContext 定义，
但使用 threading.Thread + AgentCallbacks 替代 QThread + pyqtSignal。
适用于 headless 场景、Web 服务、CLI 和测试。

Usage:
    from app.agent.agent_context import AgentContext
    from app.agent.agent_interface import AgentCallbacks
    from app.agent.agent import Agent

    ctx = AgentContext(
        callbacks=AgentCallbacks.print(),
        llm_gateway=gateway,
        registry=registry,
    )
    agent = Agent(ctx, messages)
    agent.start()  # 异步后台运行
    # 或
    result = agent.run_sync()  # 同步阻塞运行

状态流转（与 AgentThread 一致）：
    PREPARE → STREAM → EXECUTE → FEEDBACK → STREAM → ... → FINALIZE → DONE
                 ↓ (no_tools)                  ↓ (max_turns)
              FINALIZE                   WRAP_UP → FINALIZE
"""
from __future__ import annotations

import json
import copy
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agent.agent_hooks import (
    AfterIterationContext,
    BeforeToolsContext,
    BeforeTurnContext,
    CompositeHook,
    ToolCallView,
    reject as _reject,
)
from app.agent.checkpoint import clear_checkpoint, save_checkpoint
from app.agent.agent_context import AgentContext
from app.agent.turn_context import (
    TRANSITIONS,
    StateTraceEntry,
    TurnContext,
    TurnState,
)
from app.tools.registry import ToolErrorType, ToolRegistry

logger = logging.getLogger(__name__)

_MAX_WORKERS = 4

# 单工具连续失败超过此次数后强制终止 loop
_MAX_TOOL_FAILURES = 5

# 致命错误类型：检测到后终止 loop，不再进入下一轮 LLM 调用
_FATAL_ERROR_TYPES = {ToolErrorType.TOOL_NOT_FOUND, ToolErrorType.PERMISSION}


class Agent:
    """纯 Python Agent 执行循环。

    提供与 AgentThread 完全相同的状态机逻辑，但：
    - 使用 threading.Thread 替代 QThread
    - 使用 AgentCallbacks 替代 pyqtSignal
    - 零 PyQt 依赖

    支持两种运行模式：
    - start() → 异步后台线程运行
    - run_sync() → 同步阻塞运行，返回结果 dict
    """

    def __init__(
        self,
        ctx: AgentContext,
        messages: list[dict],
        session_id: str = "",
        max_turns: int = 10,
        trace_store=None,
    ):
        """初始化 Agent。

        Args:
            ctx: 中央上下文，包含 callbacks、hooks、cancel_token、llm_gateway、registry。
            messages: OpenAI API 格式的消息列表。
            session_id: 可选的会话 ID（用于 checkpoint 和 trace）。
            max_turns: 最大工具调用轮数。
            trace_store: 可选的 trace 存储后端。

        Raises:
            ValueError: ctx.llm_gateway 或 ctx.registry 为 None。
        """
        if ctx.llm_gateway is None:
            raise ValueError("AgentContext.llm_gateway is required for Agent")
        if ctx.registry is None:
            raise ValueError("AgentContext.registry is required for Agent")

        self._ctx = ctx
        self._llm = ctx.llm_gateway
        self._registry: ToolRegistry = ctx.registry
        self._messages = list(messages)
        self._session_id = session_id
        self._max_turns = max_turns
        self._trace_store = trace_store
        self._trace_id = uuid.uuid4().hex
        self._llm_seq = 0
        self._hook = ctx.composite_hook

        self._input_queue: queue.Queue = queue.Queue()
        self._inject_queue: queue.Queue = queue.Queue()
        self._tool_failure_counts: dict[str, int] = {}

        # 异步运行支持
        self._thread: threading.Thread | None = None
        self._result: dict | None = None
        self._done_event = threading.Event()

    # ── 外部控制接口 ──────────────────────────────────────────────────────

    def cancel(self):
        """请求取消当前 Agent 运行。

        线程安全：可从任意线程调用。
        """
        self._ctx.cancel()
        self._input_queue.put({})

    def supply_input(self, params: dict):
        """提供手动参数（响应 on_need_input 回调）。"""
        self._input_queue.put(params)

    def inject_message(self, message: dict):
        """Mid-turn 注入用户消息。"""
        self._inject_queue.put(message)

    # ── 运行模式 ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """在后台线程中启动状态机。

        Raises:
            RuntimeError: 如果 Agent 已在运行中。
        """
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("Agent is already running")
        self._done_event.clear()
        self._result = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="agent")
        self._thread.start()

    def run_sync(self) -> dict:
        """同步运行状态机（阻塞当前线程），返回结果 dict。

        Returns:
            {"ok": bool, "error": str|None, "trace": list[dict]}
        """
        self._done_event.clear()
        self._result = None
        self._run()
        return self._result or {"ok": False, "error": "Agent did not produce a result"}

    def wait(self, timeout: float | None = None) -> dict | None:
        """等待 Agent 运行完成（阻塞），返回结果或超时时返回 None。

        Args:
            timeout: 最大等待秒数，None 表示无限等待。
        """
        if not self._done_event.wait(timeout=timeout):
            return None
        return self._result

    @property
    def is_running(self) -> bool:
        """Agent 是否正在运行。"""
        return self._thread is not None and self._thread.is_alive()

    @property
    def trace_id(self) -> str:
        """Public execution identifier."""
        return self._trace_id

    @property
    def result(self) -> dict | None:
        """获取运行结果（仅在运行完成后可用）。"""
        return self._result

    # ── 状态机主驱动 ─────────────────────────────────────────────────────

    def _run(self):
        """状态机主循环（在后台线程中执行）。"""
        ctx = TurnContext(
            messages=list(self._messages),
            tools=self._registry.get_openai_functions(),
            max_turns=self._max_turns,
        )
        self._trace_start()
        run_t0 = time.perf_counter()
        try:
            while ctx.state is not TurnState.DONE:
                if self._ctx.is_cancelled:
                    ctx.error_message = None
                    ctx.state = TurnState.FINALIZE

                handler = getattr(self, f"_state_{ctx.state.name.lower()}")
                self._emit_state_change(ctx.state.name)

                t0 = time.perf_counter()
                event = handler(ctx)
                elapsed_ms = (time.perf_counter() - t0) * 1000

                ctx.trace.append(StateTraceEntry(
                    state=ctx.state, event=event, duration_ms=elapsed_ms
                ))
                logger.debug("[Agent] %s -> %s (%.1fms)", ctx.state.name, event, elapsed_ms)

                next_state = TRANSITIONS.get((ctx.state, event))
                if next_state is None:
                    logger.error("[Agent] No transition for (%s, %s)", ctx.state.name, event)
                    ctx.state = TurnState.FINALIZE
                    ctx.error_message = f"Invalid transition: ({ctx.state.name}, {event})"
                    event = self._state_finalize(ctx)
                    ctx.state = TRANSITIONS[(TurnState.FINALIZE, event)]
                else:
                    ctx.state = next_state
        except Exception as e:
            logger.exception("[Agent] Unhandled exception")
            self._trace_finish(ctx, "error", run_t0, error=str(e))
            self._result = {"ok": False, "status": "error", "trace_id": self.trace_id,
                            "answer": ctx.full_text, "messages": copy.deepcopy(ctx.messages),
                            "error": str(e), "trace": self._serialize_trace(ctx)}
            self._emit_done(self._result)
            self._done_event.set()
            return

        status = "cancelled" if self._ctx.is_cancelled else ("error" if ctx.error_message else "ok")
        self._trace_finish(ctx, status, run_t0, error=ctx.error_message)
        self._result = {
            "ok": status == "ok",
            "status": status,
            "trace_id": self.trace_id,
            "answer": ctx.full_text,
            "messages": copy.deepcopy(ctx.messages),
            "error": ctx.error_message,
            "trace": self._serialize_trace(ctx),
        }
        self._emit_done(self._result)
        self._done_event.set()

    # ── State Handlers ───────────────────────────────────────────────────

    def _state_prepare(self, ctx: TurnContext) -> str:
        if not ctx.messages:
            return "empty"
        new_messages = self._apply_before_turn_hook(ctx)
        if new_messages is not None:
            ctx.messages = new_messages
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        ctx.reset_turn()

        seq = self._llm_seq
        self._llm_seq += 1
        for chunk in self._llm.chat_stream(
            ctx.messages,
            ctx.tools,
            cancel_token=self._ctx.cancel_token,
            trace_id=self._trace_id,
            seq=seq,
        ):
            if self._ctx.is_cancelled:
                return "cancelled"

            if chunk["type"] == "text":
                ctx.full_text += chunk["delta"]
                self._emit_text_chunk(chunk["delta"])
            elif chunk["type"] == "tool_call":
                ctx.tool_calls.append(chunk)
            elif chunk["type"] == "error":
                ctx.error_message = chunk["message"]
                self._fire_after_iteration(ctx, [])
                return "error"
            elif chunk["type"] == "done":
                ctx.reasoning_content = chunk.get("reasoning_content")
                self._message_complete(ctx, chunk)
                break

        if not ctx.tool_calls:
            if not ctx.full_text.strip():
                ctx.error_message = "模型返回了空响应（无正文、无工具调用），请重试。"
                self._fire_after_iteration(ctx, [])
                return "error"
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
                    **({"extra_content": copy.deepcopy(tc["extra_content"])} if tc.get("extra_content") else {}),
                }
                for tc in ctx.tool_calls
            ],
        }
        if ctx.reasoning_content:
            assistant_msg["reasoning_content"] = ctx.reasoning_content
        if ctx.provider_state:
            assistant_msg["provider_state"] = copy.deepcopy(ctx.provider_state)
        ctx.messages.append(assistant_msg)

        rejections = self._apply_before_tools_hook(ctx)
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
            if self._ctx.is_cancelled:
                self._fire_after_iteration(ctx, iteration_results)
                return "cancelled"

            if mode == "concurrent" and len(batch) > 1:
                batch_results = self._execute_concurrent_batch(batch)
            else:
                batch_results = []
                for tc in batch:
                    if self._ctx.is_cancelled:
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
                            "[Agent] Fatal tool error (%s): %s — %s",
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
                            "[Agent] Tool %s failed %d times, terminating loop",
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
                    checkpoint_save = (self._ctx.checkpoint_store.save
                                       if self._ctx.checkpoint_store is not None else save_checkpoint)
                    checkpoint_save(
                        self._session_id,
                        ctx.messages,
                        assistant_msg,
                        completed_results,
                        [{"id": t["id"], "name": t["name"]} for t in remaining],
                    )

        if self._session_id:
            checkpoint_clear = (self._ctx.checkpoint_store.clear
                                if self._ctx.checkpoint_store is not None else clear_checkpoint)
            checkpoint_clear(self._session_id)

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

        self._emit_new_turn(ctx.turn_count)
        return "continue"

    def _state_wrap_up(self, ctx: TurnContext) -> str:
        """强制收尾轮：达到 max_turns 后，去掉 tools 再调一次 LLM，
        让模型基于已有工具结果产出纯文本最终答复。
        """
        ctx.reset_turn()
        self._emit_new_turn(ctx.turn_count)

        seq = self._llm_seq
        self._llm_seq += 1
        for chunk in self._llm.chat_stream(
            ctx.messages,
            None,
            cancel_token=self._ctx.cancel_token,
            trace_id=self._trace_id,
            seq=seq,
        ):
            if self._ctx.is_cancelled:
                return "cancelled"

            if chunk["type"] == "text":
                ctx.full_text += chunk["delta"]
                self._emit_text_chunk(chunk["delta"])
            elif chunk["type"] == "tool_call":
                continue
            elif chunk["type"] == "error":
                ctx.error_message = chunk["message"]
                self._fire_after_iteration(ctx, [])
                return "error"
            elif chunk["type"] == "done":
                ctx.reasoning_content = chunk.get("reasoning_content")
                self._message_complete(ctx, chunk)
                break

        self._fire_after_iteration(ctx, [])
        if not ctx.full_text.strip():
            ctx.error_message = (
                f"已达到最大工具调用轮数（{ctx.max_turns} 轮），任务尚未完成。"
                f"可继续追问以推进。"
            )
            return "error"
        return "ok"

    def _message_complete(self, ctx: TurnContext, chunk: dict) -> None:
        ctx.provider_state = copy.deepcopy(chunk.get("provider_state") or {})
        cb = self._ctx.callbacks.on_message_complete
        if cb:
            try:
                cb({"provider_state": ctx.provider_state, "reasoning_content": ctx.reasoning_content,
                    "tool_calls": copy.deepcopy(ctx.tool_calls)})
            except Exception:
                logger.debug("[Agent] message metadata callback raised", exc_info=True)

    def _state_finalize(self, ctx: TurnContext) -> str:
        trace_data = self._serialize_trace(ctx)
        if ctx.error_message:
            self._emit_done({"ok": False, "error": ctx.error_message, "trace": trace_data})
        else:
            self._emit_done({"ok": True, "error": None, "trace": trace_data})
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

        if self._session_id:
            ai_args["_session_id"] = self._session_id

        self._emit_tool_start(call_id, tool_name, ai_args)
        t0 = time.perf_counter()
        result = self._registry.execute(tool_name, ai_args)
        duration_ms = (time.perf_counter() - t0) * 1000
        self._emit_tool_done(call_id, tool_name, result)
        self._trace_tool_call(call_id, tool_name, ai_args, result, duration_ms)
        return result

    def _execute_concurrent_batch(self, batch: list[dict]) -> list[tuple[dict, dict]]:
        """并发执行一批只读工具。"""
        results: list[tuple[dict, dict] | None] = [None] * len(batch)

        for tc in batch:
            if self._session_id:
                tc["arguments"]["_session_id"] = self._session_id
            self._emit_tool_start(tc["id"], tc["name"], tc["arguments"])

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
                self._emit_tool_done(tc["id"], tc["name"], result)
                self._trace_tool_call(
                    tc["id"], tc["name"], tc["arguments"], result, duration_ms
                )

        return [r for r in results if r is not None]

    def _get_remaining_calls(
        self, all_calls: list[dict], current_batch: list[dict],
        all_batches: list[tuple[str, list[dict]]]
    ) -> list[dict]:
        """获取当前批次之后尚未执行的工具调用。"""
        found = False
        remaining = []
        for _, batch in all_batches:
            if not found:
                if batch is current_batch:
                    found = True
                continue
            remaining.extend(batch)
        return remaining

    # ── Hook 辅助方法 ────────────────────────────────────────────────────

    def _apply_before_turn_hook(self, ctx: TurnContext) -> list[dict] | None:
        """调用 before_turn hook，返回修改后的消息列表或 None。"""
        if self._hook is None:
            return None
        hook_ctx = BeforeTurnContext(
            trace_id=self._trace_id,
            session_id=self._session_id,
            turn_count=ctx.turn_count,
            messages=ctx.messages,
        )
        try:
            return self._hook.before_turn(hook_ctx)
        except Exception:
            logger.exception("[Agent] before_turn hook raised")
            return None

    def _apply_before_tools_hook(self, ctx: TurnContext) -> dict:
        """调用 before_execute_tools，返回 {call_id: ToolDecision} 的拒绝映射。"""
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
            logger.exception("[Agent] before_execute_tools hook raised; rejecting all")
            msg = f"安全审批异常，工具调用被拒绝: {exc}"
            return {tc["id"]: _reject(tc["id"], msg) for tc in ctx.tool_calls}
        if not decisions:
            return {}
        return {d.call_id: d for d in decisions if d.is_reject}

    def _fire_after_iteration(
        self, ctx: TurnContext, results: list[tuple[dict, dict]]
    ) -> None:
        """触发 after_iteration 评测埋点。"""
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
            logger.exception("[Agent] after_iteration hook raised")

    # ── Trace 辅助 ───────────────────────────────────────────────────────

    def _trace_start(self) -> None:
        if self._trace_store is None:
            return
        try:
            self._trace_store.start_trace(self._trace_id, self._session_id)
        except Exception:
            logger.debug("[Agent] trace start failed", exc_info=True)

    def _trace_finish(
        self, ctx: TurnContext, status: str, run_t0: float, error: str | None = None
    ) -> None:
        """完成 Trace 记录并写入状态机流转。"""
        if self._trace_store is None:
            return
        duration_ms = (time.perf_counter() - run_t0) * 1000
        try:
            self._trace_store.record_state_trace(self._trace_id, self._serialize_trace(ctx))
            self._trace_store.finish_trace(
                self._trace_id,
                status=status,
                turn_count=ctx.turn_count,
                duration_ms=duration_ms,
                error=error,
            )
        except Exception:
            logger.debug("[Agent] trace finish failed", exc_info=True)

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
            logger.debug("[Agent] trace record_tool_call failed", exc_info=True)

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

    # ── Callback 发射辅助 ────────────────────────────────────────────────

    def _emit_text_chunk(self, delta: str) -> None:
        cb = self._ctx.callbacks.on_text_chunk
        if cb is not None:
            try:
                cb(delta)
            except Exception:
                logger.debug("[Agent] on_text_chunk callback raised", exc_info=True)

    def _emit_tool_start(self, call_id: str, name: str, params: dict) -> None:
        cb = self._ctx.callbacks.on_tool_start
        if cb is not None:
            try:
                cb(call_id, name, params)
            except Exception:
                logger.debug("[Agent] on_tool_start callback raised", exc_info=True)

    def _emit_tool_done(self, call_id: str, name: str, result: dict) -> None:
        cb = self._ctx.callbacks.on_tool_done
        if cb is not None:
            try:
                cb(call_id, name, result)
            except Exception:
                logger.debug("[Agent] on_tool_done callback raised", exc_info=True)

    def _emit_state_change(self, state_name: str) -> None:
        cb = self._ctx.callbacks.on_state_change
        if cb is not None:
            try:
                cb(state_name)
            except Exception:
                logger.debug("[Agent] on_state_change callback raised", exc_info=True)

    def _emit_new_turn(self, turn_count: int) -> None:
        cb = self._ctx.callbacks.on_new_turn
        if cb is not None:
            try:
                cb(turn_count)
            except Exception:
                logger.debug("[Agent] on_new_turn callback raised", exc_info=True)

    def _emit_done(self, info: dict) -> None:
        cb = self._ctx.callbacks.on_done
        if cb is not None:
            try:
                cb(info)
            except Exception:
                logger.debug("[Agent] on_done callback raised", exc_info=True)
