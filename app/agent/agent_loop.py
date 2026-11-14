"""Synchronous Agent state machine; owns no top-level execution thread."""
from __future__ import annotations

import copy
import json
import logging
import queue
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agent.agent_context import AgentContext
from app.agent.agent_hooks import (
    AfterIterationContext, BeforeToolsContext, BeforeTurnContext, ToolCallView, reject as _reject,
)
from app.agent.contracts import CheckpointSnapshot, ToolExecutionContext, ToolFailureKind, ToolRuntime, TraceSink
from app.agent.execution_policy import ExecutionPolicy, resolve_policy
from app.agent.request_context import RequestContext, RequestCancelled, check_cancelled, encode_for_model, validate_tool_calls
from app.agent.turn_context import TRANSITIONS, StateTraceEntry, TurnContext, TurnState
from app.runtime.cancellation import _close_resource

logger = logging.getLogger(__name__)


class AgentLoop:
    def __init__(
        self, ctx: AgentContext, messages: list[dict], session_id: str = "",
        max_turns: int | None = None, trace_store: TraceSink | None = None, *,
        trace_id: str | None = None, policy: ExecutionPolicy | None = None,
        injected_queue: queue.Queue | None = None,
    ):
        if ctx.llm_gateway is None:
            raise ValueError("AgentContext.llm_gateway is required for AgentLoop")
        if ctx.registry is None:
            raise ValueError("AgentContext.registry is required for AgentLoop")
        self._ctx = ctx
        self._llm = ctx.llm_gateway
        self._registry: ToolRuntime = ctx.registry
        self._messages = copy.deepcopy(messages)
        self._input_count = len(messages)
        self._initial_view = None
        self._session_id = session_id
        self._policy = resolve_policy(max_turns, policy)
        self._max_turns = self._policy.max_turns
        self._trace_store = trace_store if trace_store is not None else ctx.trace_store
        self._trace_id = trace_id if trace_id is not None else uuid.uuid4().hex
        self._llm_seq = 0
        self._hook = ctx.composite_hook
        self._inject_queue = injected_queue if injected_queue is not None else queue.Queue()
        self._tool_failure_counts: dict[str, int] = {}
        self._started = False
        self._iteration_notified = True
        self._turn: TurnContext | None = None

    @property
    def turn_count(self) -> int:
        return self._turn.turn_count if self._turn is not None else 0

    def run(self) -> dict:
        if self._started:
            raise RuntimeError("AgentLoop is single-use")
        self._started = True
        ctx = self._turn = TurnContext(
            messages=copy.deepcopy(self._messages), tools=None, max_turns=self._max_turns,
        )
        try:
            if not self._ctx.is_cancelled:
                ctx.tools = copy.deepcopy(self._registry.definitions())
            while ctx.state is not TurnState.DONE:
                if self._ctx.is_cancelled:
                    ctx.error_message = None
                    if not self._iteration_notified:
                        self._fire_after_iteration(ctx, ctx.iteration_results)
                    ctx.state = TurnState.FINALIZE
                state = ctx.state
                self._emit_state_change(state.name)
                t0 = time.perf_counter()
                event = getattr(self, f"_state_{state.name.lower()}")(ctx)
                ctx.trace.append(StateTraceEntry(
                    state=state, event=event, duration_ms=(time.perf_counter()-t0)*1000,
                ))
                next_state = TRANSITIONS.get((state, event))
                if next_state is None:
                    raise RuntimeError(f"Invalid transition: ({state.name}, {event})")
                ctx.state = next_state
        except RequestCancelled:
            pass
        except Exception as exc:
            logger.exception("[AgentLoop] Execution failed")
            ctx.error_message = str(exc)
            if not self._iteration_notified:
                self._fire_after_iteration(ctx, ctx.iteration_results)
        status = "cancelled" if self._ctx.is_cancelled else ("error" if ctx.error_message else "ok")
        return {
            "ok": status == "ok", "status": status, "trace_id": self._trace_id,
            "answer": ctx.full_text, "messages": copy.deepcopy(ctx.messages),
            "error": None if status == "cancelled" else ctx.error_message,
            "trace": self._serialize_trace(ctx),
        }

    def _state_prepare(self, ctx: TurnContext) -> str:
        if not ctx.messages:
            return "empty"
        view = self._apply_before_turn_hook(ctx)
        self._initial_view = copy.deepcopy(view) if view is not None else None
        ctx.reset_turn()
        return "ok"

    def _state_stream(self, ctx: TurnContext) -> str:
        return self._stream_response(ctx, wrap_up=False)

    def _prepare_request(self, ctx: TurnContext, seq: int, wrap_up: bool):
        check_cancelled(self._ctx.cancel_token)
        messages = ctx.messages
        if self._initial_view is not None:
            messages = self._initial_view + ctx.messages[self._input_count:]
        request = RequestContext(
            messages=copy.deepcopy(messages), tools=None if wrap_up else copy.deepcopy(ctx.tools),
            session_id=self._session_id, trace_id=self._trace_id, seq=seq,
            mode="wrap_up" if wrap_up else "normal", cancel_token=self._ctx.cancel_token,
        )
        prepared = self._ctx.request_preparer.prepare(request)
        check_cancelled(self._ctx.cancel_token)
        return encode_for_model(prepared.messages), None if wrap_up else copy.deepcopy(prepared.tools)

    def _stream_response(self, ctx: TurnContext, *, wrap_up: bool) -> str:
        ctx.reset_turn()
        self._iteration_notified = False
        self._request_active = True
        seq = self._llm_seq
        self._llm_seq += 1
        stream = None
        try:
            messages, tools = self._prepare_request(ctx, seq, wrap_up)
            check_cancelled(self._ctx.cancel_token)
            stream = self._llm.chat_stream(
                messages, tools, cancel_token=self._ctx.cancel_token,
                trace_id=self._trace_id, seq=seq,
            )
            for chunk in stream:
                check_cancelled(self._ctx.cancel_token)
                if chunk["type"] == "text":
                    ctx.full_text += chunk["delta"]
                    self._emit_text_chunk(chunk["delta"])
                elif chunk["type"] == "tool_call" and not wrap_up:
                    ctx.tool_calls.append(copy.deepcopy(chunk))
                elif chunk["type"] == "error":
                    raise RuntimeError(chunk["message"])
                elif chunk["type"] == "done":
                    ctx.reasoning_content = chunk.get("reasoning_content")
                    self._message_complete(ctx, chunk)
                    break
            check_cancelled(self._ctx.cancel_token)
            if ctx.tool_calls:
                return "has_tools"
            if not ctx.full_text.strip():
                if wrap_up:
                    raise RuntimeError(f"已达到最大工具调用轮数（{ctx.max_turns} 轮），任务尚未完成。可继续追问以推进。")
                raise RuntimeError("模型返回了空响应（无正文、无工具调用），请重试。")
            ctx.messages.append(self._assistant_message(ctx))
            self._fire_after_iteration(ctx, [])
            return "ok" if wrap_up else "no_tools"
        except RequestCancelled:
            ctx.error_message = None
            self._fire_after_iteration(ctx, [])
            return "cancelled"
        except Exception as exc:
            ctx.error_message = str(exc)
            self._fire_after_iteration(ctx, [])
            return "error"
        finally:
            _close_resource(stream)

    @staticmethod
    def _assistant_message(ctx: TurnContext) -> dict:
        message = {"role": "assistant", "content": ctx.full_text or None}
        if ctx.tool_calls:
            message["tool_calls"] = [
                {
                    "id": call["id"], "type": "function",
                    "function": {"name": call["name"], "arguments": json.dumps(call["arguments"], ensure_ascii=False)},
                    **({"extra_content": copy.deepcopy(call["extra_content"])} if call.get("extra_content") else {}),
                }
                for call in ctx.tool_calls
            ]
        if ctx.reasoning_content:
            message["reasoning_content"] = ctx.reasoning_content
        if ctx.provider_state:
            message["provider_state"] = copy.deepcopy(ctx.provider_state)
        return message

    def _state_execute(self, ctx: TurnContext) -> str:
        assistant = self._assistant_message(ctx)
        validate_tool_calls(assistant.get("tool_calls", []))
        ctx.messages.append(assistant)
        result_start = len(ctx.messages)
        completed = {}

        def record_results():
            ordered = [(call, completed[call["id"]]) for call in ctx.tool_calls if call["id"] in completed]
            ctx.iteration_results = ordered
            ctx.messages[result_start:] = [
                {"role": "tool", "tool_call_id": call["id"], "content": self._registry.format_result(result)}
                for call, result in ordered
            ]

        rejections = self._apply_before_tools_hook(ctx)
        pending = []
        for call in ctx.tool_calls:
            decision = rejections.get(call["id"])
            if decision is None:
                pending.append(call)
                continue
            result = {
                "status": "error",
                "data": {
                    "message": decision.message or "该工具调用被安全策略拒绝。",
                    "error_type": ToolFailureKind.PERMISSION.value,
                    "retryable": False, "rejected_by_hook": True,
                },
            }
            completed[call["id"]] = result
            self._trace_tool_call(call["id"], call["name"], call["arguments"], result, 0.0)
        record_results()
        batches = self._partition_batches(pending)
        for mode, batch in batches:
            if self._ctx.is_cancelled:
                self._fire_after_iteration(ctx, ctx.iteration_results)
                return "cancelled"
            if mode == "concurrent" and len(batch) > 1:
                outcomes = self._execute_concurrent_batch(batch)
            else:
                outcomes = []
                for call in batch:
                    result = self._execute_one(call)
                    if result is None:
                        self._fire_after_iteration(ctx, ctx.iteration_results)
                        return "cancelled"
                    outcomes.append((call, result))
            error = None
            for call, result in outcomes:
                completed[call["id"]] = result
                name = call["name"]
                if result.get("status") != "error":
                    self._tool_failure_counts.pop(name, None)
                    continue
                count = self._tool_failure_counts.get(name, 0) + 1
                self._tool_failure_counts[name] = count
                data = result.get("data", {})
                try:
                    kind = ToolFailureKind(data.get("error_type"))
                except (ValueError, TypeError):
                    kind = ToolFailureKind.RUNTIME
                if error is None and self._policy.is_fatal(kind):
                    error = f"工具 {name} 发生致命错误 ({kind.value}): {data.get('message', '')}"
                if error is None and count >= self._policy.max_tool_failures:
                    error = f"工具 {name} 连续失败 {self._policy.max_tool_failures} 次，终止执行"
            record_results()
            if self._ctx.is_cancelled:
                self._fire_after_iteration(ctx, ctx.iteration_results)
                return "cancelled"
            if error is not None:
                ctx.error_message = error
                self._fire_after_iteration(ctx, ctx.iteration_results)
                return "error"
            remaining = [call for call in pending if call["id"] not in completed]
            if self._session_id and remaining:
                self._ctx.checkpoint_store.save(self._session_id, CheckpointSnapshot(
                    messages=copy.deepcopy(ctx.messages), assistant_msg=copy.deepcopy(assistant),
                    completed_results=copy.deepcopy(ctx.messages[result_start:]),
                    pending_tool_calls=[{"id": call["id"], "name": call["name"]} for call in remaining],
                ))
        if self._session_id:
            self._ctx.checkpoint_store.clear(self._session_id)
        self._fire_after_iteration(ctx, ctx.iteration_results)
        return "ok"

    def _state_feedback(self, ctx: TurnContext) -> str:
        ctx.turn_count += 1

        while not self._inject_queue.empty():
            try:
                msg = self._inject_queue.get_nowait()
                ctx.messages.append(msg)
            except queue.Empty:
                break

        if self._policy.needs_wrap_up(ctx.turn_count):
            return "max_turns"

        self._emit_new_turn(ctx.turn_count)
        return "continue"

    def _state_wrap_up(self, ctx: TurnContext) -> str:
        self._emit_new_turn(ctx.turn_count)
        return self._stream_response(ctx, wrap_up=True)

    def _message_complete(self, ctx: TurnContext, chunk: dict) -> None:
        ctx.provider_state = copy.deepcopy(chunk.get("provider_state") or {})
        cb = self._ctx.callbacks.on_message_complete
        if cb:
            try:
                cb({"provider_state": copy.deepcopy(ctx.provider_state), "reasoning_content": ctx.reasoning_content,
                    "tool_calls": copy.deepcopy(ctx.tool_calls)})
            except Exception:
                logger.debug("[Agent] message metadata callback raised", exc_info=True)

    def _state_finalize(self, ctx: TurnContext) -> str:
        return "ok"

    def _partition_batches(self, tool_calls: list[dict]) -> list[tuple[str, list[dict]]]:
        return self._policy.partition(tool_calls, self._registry)

    def _execute_one(self, tc: dict) -> dict | None:
        """执行单个工具调用。"""
        if self._ctx.is_cancelled:
            return None
        call_id = tc["id"]
        tool_name = tc["name"]
        ai_args = tc["arguments"]

        self._emit_tool_start(call_id, tool_name, ai_args)
        if self._ctx.is_cancelled:
            return None
        t0 = time.perf_counter()
        result = self._registry.execute(
            tool_name, copy.deepcopy(ai_args), self._tool_context(call_id),
        )
        duration_ms = (time.perf_counter() - t0) * 1000
        self._emit_tool_done(call_id, tool_name, result)
        self._trace_tool_call(call_id, tool_name, ai_args, result, duration_ms)
        return result

    def _execute_concurrent_batch(self, batch: list[dict]) -> list[tuple[dict, dict]]:
        """并发执行一批只读工具。"""
        results: list[tuple[dict, dict] | None] = [None] * len(batch)

        for tc in batch:
            self._emit_tool_start(tc["id"], tc["name"], tc["arguments"])

        with ThreadPoolExecutor(max_workers=self._policy.max_workers) as pool:
            future_to_idx = {}
            start_times: dict[int, float] = {}
            for i, tc in enumerate(batch):
                start_times[i] = time.perf_counter()
                future = pool.submit(self._execute_if_active, tc)
                future_to_idx[future] = i

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                tc = batch[idx]
                try:
                    result = future.result()
                    if result is None:
                        continue
                except Exception as e:
                    result = {"status": "error", "data": {"message": str(e)}}
                duration_ms = (time.perf_counter() - start_times[idx]) * 1000
                results[idx] = (tc, result)
                self._emit_tool_done(tc["id"], tc["name"], result)
                self._trace_tool_call(
                    tc["id"], tc["name"], tc["arguments"], result, duration_ms
                )

        return [r for r in results if r is not None]

    def _tool_context(self, call_id: str) -> ToolExecutionContext:
        return ToolExecutionContext(
            session_id=self._session_id, trace_id=self._trace_id,
            call_id=call_id, cancel_token=self._ctx.cancel_token,
        )

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

    def _apply_before_turn_hook(self, ctx: TurnContext) -> list[dict] | None:
        """调用 before_turn hook，返回修改后的消息列表或 None。"""
        if self._hook is None:
            return None
        hook_ctx = BeforeTurnContext(
            trace_id=self._trace_id,
            session_id=self._session_id,
            turn_count=ctx.turn_count,
            messages=copy.deepcopy(ctx.messages),
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
        if getattr(self, "_request_active", False) and self._iteration_notified:
            return
        self._iteration_notified = True
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
                arguments=copy.deepcopy(arguments),
                result=copy.deepcopy(result),
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
                cb(call_id, name, copy.deepcopy(params))
            except Exception:
                logger.debug("[Agent] on_tool_start callback raised", exc_info=True)

    def _emit_tool_done(self, call_id: str, name: str, result: dict) -> None:
        cb = self._ctx.callbacks.on_tool_done
        if cb is not None:
            try:
                cb(call_id, name, copy.deepcopy(result))
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

    def _execute_if_active(self, call: dict) -> dict | None:
        if self._ctx.is_cancelled:
            return None
        return self._registry.execute(
            call["name"], copy.deepcopy(call["arguments"]), self._tool_context(call["id"]),
        )
