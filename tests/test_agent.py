"""Agent 全面单元测试 — 覆盖初始化、状态机、工具执行、hook、生命周期、trace、回调。

与 test_agent_thread.py 互补：
  - test_agent_thread.py 侧重点：批次分区、剩余调用、trace 序列化、转换表、hook 拒绝、wrap_up
  - test_agent.py 侧重点：状态机全流程、工具执行路径、生命周期(start/run_sync/wait/cancel)、
    回调验证、trace 存储集成、边缘情况

不启动线程，只在主线程直接调 Agent 的被测方法。
Agent 零 Qt 依赖，无需 QApplication。
"""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from app.core.agent_hooks import (
    AfterIterationContext,
    AgentHook,
    BeforeToolsContext,
    BeforeTurnContext,
    ToolCallView,
    reject,
)
from app.core.agent_interface import AgentCallbacks
from app.core.llm_gateway import CancellationToken
from app.core.agent import Agent
from app.core.agent_context import AgentContext
from app.core.turn_context import StateTraceEntry, TurnContext, TurnState
from app.tools.registry import ToolErrorType, ToolRegistry


# ══════════════════════════════════════════════════════════════════════════
# Fake / Helper 工厂
# ══════════════════════════════════════════════════════════════════════════

class _FakeTool:
    """预设 read_only 标志的假工具。"""

    def __init__(self, read_only: bool, enabled: bool = True):
        self.read_only = read_only
        self.enabled = enabled
        self.name = "fake_tool"

    def get_openai_functions(self):
        return []


class _FakeRegistry:
    """按名字返回预设 read_only 标志的假注册表，可选模拟 execute 行为。"""

    def __init__(self, read_only_map: dict[str, bool], execute_fn=None):
        self._map = read_only_map
        self._execute_fn = execute_fn

    def get(self, name):
        if name not in self._map:
            return None
        return _FakeTool(self._map[name])

    def get_openai_functions(self):
        return []

    def execute(self, name, params):
        if self._execute_fn:
            return self._execute_fn(name, params)
        return {"status": "success", "data": {}}


class _FakeGateway:
    """按预设 chunk 序列驱动 chat_stream 的假网关，记录收到的 tools 参数。"""

    def __init__(self, chunks=None):
        self._chunks = chunks or []
        self.received_tools = None
        self.call_count = 0

    def chat_stream(self, messages, tools, **kwargs):
        self.received_tools = tools
        self.call_count += 1
        yield from self._chunks


class _FakeTraceStore:
    """收集所有 trace 调用的假存储。"""

    def __init__(self):
        self.starts: list[tuple[str, str]] = []
        self.state_traces: list[tuple[str, list]] = []
        self.finishes: list[dict] = []
        self.tool_calls: list[dict] = []

    def start_trace(self, trace_id, session_id):
        self.starts.append((trace_id, session_id))

    def record_state_trace(self, trace_id, data):
        self.state_traces.append((trace_id, data))

    def finish_trace(self, trace_id, status, turn_count, duration_ms, error=None):
        self.finishes.append({
            "trace_id": trace_id,
            "status": status,
            "turn_count": turn_count,
            "duration_ms": duration_ms,
            "error": error,
        })

    def record_tool_call(self, trace_id, call_id, name, arguments, result, duration_ms):
        self.tool_calls.append({
            "trace_id": trace_id,
            "call_id": call_id,
            "name": name,
            "arguments": arguments,
            "result": result,
            "duration_ms": duration_ms,
        })


def _make_agent(registry=None, gateway=None, hooks=None, callbacks=None,
                messages=None, session_id="s1", max_turns=10, trace_store=None,
                cancel_token=None) -> Agent:
    """便捷构造 Agent 用于测试。"""
    ctx = AgentContext(
        callbacks=callbacks or AgentCallbacks.silent(),
        llm_gateway=gateway or object(),
        registry=registry or _FakeRegistry({}),
        hooks=hooks or [],
        cancel_token=cancel_token or CancellationToken(),
    )
    return Agent(
        ctx=ctx,
        messages=messages or [],
        session_id=session_id,
        max_turns=max_turns,
        trace_store=trace_store,
    )


def _tc(call_id, name="x", arguments=None):
    """快捷构造 tool_call dict。"""
    return {"id": call_id, "name": name, "arguments": arguments or {}}


# ══════════════════════════════════════════════════════════════════════════
# 1. 初始化校验
# ══════════════════════════════════════════════════════════════════════════

class InitValidationTest(unittest.TestCase):
    """验证 Agent.__init__ 的参数校验和默认值。"""

    def test_missing_llm_gateway_raises_valueerror(self):
        ctx = AgentContext(
            callbacks=AgentCallbacks.silent(),
            registry=_FakeRegistry({}),
        )
        with self.assertRaises(ValueError) as cm:
            Agent(ctx=ctx, messages=[])
        self.assertIn("llm_gateway", str(cm.exception))

    def test_missing_registry_raises_valueerror(self):
        ctx = AgentContext(
            callbacks=AgentCallbacks.silent(),
            llm_gateway=object(),
        )
        with self.assertRaises(ValueError) as cm:
            Agent(ctx=ctx, messages=[])
        self.assertIn("registry", str(cm.exception))

    def test_default_session_id_empty_string(self):
        agent = _make_agent(session_id="")
        self.assertEqual(agent._session_id, "")

    def test_session_id_preserved(self):
        agent = _make_agent(session_id="abc-123")
        self.assertEqual(agent._session_id, "abc-123")

    def test_trace_id_is_unique(self):
        a1 = _make_agent()
        a2 = _make_agent()
        self.assertNotEqual(a1._trace_id, a2._trace_id)
        self.assertEqual(len(a1._trace_id), 32)  # uuid4 hex

    def test_max_turns_default(self):
        agent = _make_agent()
        self.assertEqual(agent._max_turns, 10)

    def test_custom_max_turns(self):
        agent = _make_agent(max_turns=3)
        self.assertEqual(agent._max_turns, 3)

    def test_messages_copied_not_aliased(self):
        msgs = [{"role": "user", "content": "hi"}]
        agent = _make_agent(messages=msgs)
        msgs.append({"role": "user", "content": "extra"})
        self.assertEqual(len(agent._messages), 1)

    def test_null_hooks_produces_none_composite(self):
        ctx = AgentContext(
            callbacks=AgentCallbacks.silent(),
            llm_gateway=object(),
            registry=_FakeRegistry({}),
        )
        agent = Agent(ctx=ctx, messages=[])
        self.assertIsNone(agent._hook)

    def test_empty_hooks_produces_none_composite(self):
        agent = _make_agent(hooks=[])
        self.assertIsNone(agent._hook)


# ══════════════════════════════════════════════════════════════════════════
# 2. _state_prepare
# ══════════════════════════════════════════════════════════════════════════

class StatePrepareTest(unittest.TestCase):
    def test_empty_messages_returns_empty(self):
        agent = _make_agent(messages=[])
        ctx = TurnContext(messages=[], tools=None)
        event = agent._state_prepare(ctx)
        self.assertEqual(event, "empty")

    def test_with_messages_returns_ok(self):
        agent = _make_agent(messages=[{"role": "user", "content": "hi"}])
        ctx = TurnContext(
            messages=[{"role": "user", "content": "hi"}],
            tools=None,
        )
        event = agent._state_prepare(ctx)
        self.assertEqual(event, "ok")

    def test_resets_turn_on_ok(self):
        agent = _make_agent(messages=[{"role": "user", "content": "q"}])
        ctx = TurnContext(
            messages=[{"role": "user", "content": "q"}],
            tools=None,
        )
        ctx.full_text = "stale"
        ctx.tool_calls = [{"stale": True}]
        ctx.state = TurnState.STREAM
        agent._state_prepare(ctx)
        self.assertEqual(ctx.full_text, "")
        self.assertEqual(ctx.tool_calls, [])

    def test_before_turn_hook_modifies_messages(self):
        class _ModifyHook(AgentHook):
            def before_turn(self, ctx: BeforeTurnContext):
                return [{"role": "system", "content": "injected"}]

        agent = _make_agent(
            hooks=[_ModifyHook()],
            messages=[{"role": "user", "content": "original"}],
        )
        ctx = TurnContext(
            messages=[{"role": "user", "content": "original"}],
            tools=None,
        )
        agent._state_prepare(ctx)
        self.assertEqual(len(ctx.messages), 1)
        self.assertEqual(ctx.messages[0]["content"], "injected")

    def test_before_turn_hook_returns_none_preserves_messages(self):
        class _NoopHook(AgentHook):
            def before_turn(self, ctx: BeforeTurnContext):
                return None

        agent = _make_agent(
            hooks=[_NoopHook()],
            messages=[{"role": "user", "content": "original"}],
        )
        ctx = TurnContext(
            messages=[{"role": "user", "content": "original"}],
            tools=None,
        )
        agent._state_prepare(ctx)
        self.assertEqual(ctx.messages[0]["content"], "original")

    def test_before_turn_hook_raises_does_not_crash(self):
        class _BadHook(AgentHook):
            def before_turn(self, ctx: BeforeTurnContext):
                raise RuntimeError("oops")

        agent = _make_agent(
            hooks=[_BadHook()],
            messages=[{"role": "user", "content": "original"}],
        )
        ctx = TurnContext(
            messages=[{"role": "user", "content": "original"}],
            tools=None,
        )
        # 不应抛异常
        event = agent._state_prepare(ctx)
        self.assertEqual(event, "ok")


# ══════════════════════════════════════════════════════════════════════════
# 3. _state_stream
# ══════════════════════════════════════════════════════════════════════════

class StateStreamTest(unittest.TestCase):
    def test_text_chunks_accumulated(self):
        chunks = [
            {"type": "text", "delta": "Hello"},
            {"type": "text", "delta": " World"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        event = agent._state_stream(ctx)
        self.assertEqual(event, "no_tools")
        self.assertEqual(ctx.full_text, "Hello World")

    def test_tool_calls_detected_returns_has_tools(self):
        chunks = [
            {"type": "tool_call", "id": "t1", "name": "search", "arguments": {"q": "x"}},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=[{"type": "function"}])
        event = agent._state_stream(ctx)
        self.assertEqual(event, "has_tools")
        self.assertEqual(len(ctx.tool_calls), 1)
        self.assertEqual(ctx.tool_calls[0]["id"], "t1")

    def test_error_chunk_returns_error(self):
        chunks = [{"type": "error", "message": "model overloaded"}]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        event = agent._state_stream(ctx)
        self.assertEqual(event, "error")
        self.assertIn("model overloaded", ctx.error_message)

    def test_reasoning_content_captured_on_done(self):
        chunks = [
            {"type": "text", "delta": "answer"},
            {"type": "done", "reasoning_content": "I think..."},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        agent._state_stream(ctx)
        self.assertEqual(ctx.reasoning_content, "I think...")

    def test_cancelled_during_stream_returns_cancelled(self):
        chunks = [
            {"type": "text", "delta": "start"},
            {"type": "text", "delta": "more"},
            {"type": "done"},
        ]
        cancel_token = CancellationToken()
        gw = _FakeGateway(chunks)

        # 在 gateway 生成过程中取消
        orig = gw.chat_stream

        def cancelling_stream(*args, **kwargs):
            cancel_token.cancel()
            yield from orig(*args, **kwargs)

        gw.chat_stream = cancelling_stream

        agent = _make_agent(gateway=gw, cancel_token=cancel_token)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        event = agent._state_stream(ctx)
        self.assertEqual(event, "cancelled")

    def test_resets_turn_before_stream(self):
        chunks = [{"type": "done"}]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.full_text = "stale"
        ctx.tool_calls = [{"stale": True}]
        agent._state_stream(ctx)
        self.assertEqual(ctx.full_text, "")

    def test_text_then_tool_call_then_done(self):
        chunks = [
            {"type": "text", "delta": "Let me search."},
            {"type": "tool_call", "id": "c1", "name": "web", "arguments": {"q": "test"}},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=[{"type": "function"}])
        event = agent._state_stream(ctx)
        self.assertEqual(event, "has_tools")
        self.assertEqual(ctx.full_text, "Let me search.")
        self.assertEqual(len(ctx.tool_calls), 1)


# ══════════════════════════════════════════════════════════════════════════
# 4. _state_execute
# ══════════════════════════════════════════════════════════════════════════

class StateExecuteTest(unittest.TestCase):
    def _ctx_with_calls(self, calls=None):
        ctx = TurnContext(messages=[{"role": "user", "content": "q"}], tools=None)
        ctx.tool_calls = calls or [_tc("1", "tool_a")]
        return ctx

    def test_single_successful_execution(self):
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {"result": "ok"}})
        agent = _make_agent(registry=reg)
        ctx = self._ctx_with_calls()
        event = agent._state_execute(ctx)
        self.assertEqual(event, "ok")
        # assistant msg appended
        self.assertEqual(ctx.messages[1]["role"], "assistant")
        # tool result appended
        self.assertEqual(ctx.messages[2]["role"], "tool")

    def test_fatal_error_tool_not_found_returns_error(self):
        reg = _FakeRegistry({"bad_tool": False}, execute_fn=lambda n, p: {
            "status": "error",
            "data": {"message": "not found", "error_type": ToolErrorType.TOOL_NOT_FOUND.value, "retryable": False},
        })
        agent = _make_agent(registry=reg)
        ctx = self._ctx_with_calls([_tc("1", "bad_tool")])
        event = agent._state_execute(ctx)
        self.assertEqual(event, "error")
        self.assertIn("bad_tool", ctx.error_message)

    def test_fatal_error_permission_returns_error(self):
        reg = _FakeRegistry({"danger": False}, execute_fn=lambda n, p: {
            "status": "error",
            "data": {"message": "denied", "error_type": ToolErrorType.PERMISSION.value, "retryable": False},
        })
        agent = _make_agent(registry=reg)
        ctx = self._ctx_with_calls([_tc("1", "danger")])
        event = agent._state_execute(ctx)
        self.assertEqual(event, "error")

    def test_max_failures_triggers_error(self):
        call_count = [0]

        def flaky_tool(name, params):
            call_count[0] += 1
            return {"status": "error", "data": {"message": "fail", "error_type": ToolErrorType.RUNTIME.value, "retryable": True}}

        reg = _FakeRegistry({"flaky": False}, execute_fn=flaky_tool)
        agent = _make_agent(registry=reg)
        # 连续失败 6 次（每轮 1 次调用 = 6 轮触发阈值 5）
        agent._tool_failure_counts["flaky"] = 4  # 起始已有 4 次失败
        ctx = self._ctx_with_calls([_tc("1", "flaky")])
        event = agent._state_execute(ctx)
        self.assertEqual(event, "error")
        self.assertIn("flaky", ctx.error_message)

    def test_success_resets_failure_count(self):
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg)
        agent._tool_failure_counts["tool_a"] = 3
        ctx = self._ctx_with_calls([_tc("1", "tool_a")])
        agent._state_execute(ctx)
        self.assertNotIn("tool_a", agent._tool_failure_counts)

    def test_assistant_message_includes_reasoning(self):
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg)
        ctx = self._ctx_with_calls()
        ctx.reasoning_content = "Let me think..."
        agent._state_execute(ctx)
        self.assertEqual(ctx.messages[1].get("reasoning_content"), "Let me think...")

    def test_assistant_message_omits_reasoning_when_none(self):
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg)
        ctx = self._ctx_with_calls()
        ctx.reasoning_content = None
        agent._state_execute(ctx)
        self.assertNotIn("reasoning_content", ctx.messages[1])

    def test_cancelled_mid_batch_returns_cancelled(self):
        cancel_token = CancellationToken()
        cancel_token.cancel()
        reg = _FakeRegistry({"tool_a": False})
        agent = _make_agent(registry=reg, cancel_token=cancel_token)
        ctx = self._ctx_with_calls([_tc("1", "tool_a")])
        event = agent._state_execute(ctx)
        self.assertEqual(event, "cancelled")

    def test_before_tools_hook_rejects_creates_rejection_results(self):
        class _RejectA(AgentHook):
            def before_execute_tools(self, ctx: BeforeToolsContext):
                return [reject("1", "not allowed")]

        reg = _FakeRegistry({"tool_a": False, "tool_b": False},
                            execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg, hooks=[_RejectA()])
        ctx = self._ctx_with_calls([_tc("1", "tool_a"), _tc("2", "tool_b")])
        event = agent._state_execute(ctx)
        self.assertEqual(event, "ok")
        # tool_a 被拒绝，tool_b 正常执行 → 两条 tool 消息
        tool_msgs = [m for m in ctx.messages if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 2)

    def test_partial_hook_rejection_only_rejects_specified(self):
        class _RejectOne(AgentHook):
            def before_execute_tools(self, ctx: BeforeToolsContext):
                return [reject("1", "blocked")]

        executed = []

        def track(name, params):
            executed.append(name)
            return {"status": "success", "data": {}}

        reg = _FakeRegistry({"tool_a": False, "tool_b": False}, execute_fn=track)
        agent = _make_agent(registry=reg, hooks=[_RejectOne()])
        ctx = self._ctx_with_calls([_tc("1", "tool_a"), _tc("2", "tool_b")])
        agent._state_execute(ctx)
        # tool_a 被拒绝不执行；tool_b 执行
        self.assertNotIn("tool_a", executed)
        self.assertIn("tool_b", executed)


# ══════════════════════════════════════════════════════════════════════════
# 5. _state_feedback
# ══════════════════════════════════════════════════════════════════════════

class StateFeedbackTest(unittest.TestCase):
    def test_increments_turn_count(self):
        agent = _make_agent()
        ctx = TurnContext(messages=[{"role": "user"}], tools=None, max_turns=10)
        ctx.turn_count = 0
        agent._state_feedback(ctx)
        self.assertEqual(ctx.turn_count, 1)

    def test_continue_when_under_max_turns(self):
        agent = _make_agent()
        ctx = TurnContext(messages=[{"role": "user"}], tools=None, max_turns=10)
        ctx.turn_count = 0
        event = agent._state_feedback(ctx)
        self.assertEqual(event, "continue")

    def test_max_turns_reached_returns_max_turns(self):
        agent = _make_agent()
        ctx = TurnContext(messages=[{"role": "user"}], tools=None, max_turns=2)
        ctx.turn_count = 1  # 下一轮就是第 2 轮，达到 max
        event = agent._state_feedback(ctx)
        self.assertEqual(event, "max_turns")

    def test_injects_queued_messages(self):
        agent = _make_agent()
        agent._inject_queue.put({"role": "user", "content": "injected"})
        ctx = TurnContext(messages=[{"role": "user", "content": "original"}], tools=None, max_turns=10)
        agent._state_feedback(ctx)
        self.assertEqual(len(ctx.messages), 2)
        self.assertEqual(ctx.messages[1]["content"], "injected")

    def test_injects_multiple_queued_messages(self):
        agent = _make_agent()
        agent._inject_queue.put({"role": "user", "content": "first"})
        agent._inject_queue.put({"role": "user", "content": "second"})
        ctx = TurnContext(messages=[{"role": "user", "content": "original"}], tools=None, max_turns=10)
        agent._state_feedback(ctx)
        self.assertEqual(len(ctx.messages), 3)

    def test_empty_queue_no_injection(self):
        agent = _make_agent()
        ctx = TurnContext(messages=[{"role": "user"}], tools=None, max_turns=10)
        agent._state_feedback(ctx)
        self.assertEqual(len(ctx.messages), 1)


# ══════════════════════════════════════════════════════════════════════════
# 6. _state_finalize
# ══════════════════════════════════════════════════════════════════════════

class StateFinalizeTest(unittest.TestCase):
    def test_returns_ok(self):
        agent = _make_agent()
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        event = agent._state_finalize(ctx)
        self.assertEqual(event, "ok")

    def test_emits_done_with_error(self):
        results = []
        cb = AgentCallbacks(on_done=lambda info: results.append(info))
        agent = _make_agent(callbacks=cb)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.error_message = "something went wrong"
        agent._state_finalize(ctx)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertEqual(results[0]["error"], "something went wrong")

    def test_emits_done_with_success(self):
        results = []
        cb = AgentCallbacks(on_done=lambda info: results.append(info))
        agent = _make_agent(callbacks=cb)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        agent._state_finalize(ctx)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])
        self.assertIsNone(results[0]["error"])

    def test_trace_included_in_done(self):
        results = []
        cb = AgentCallbacks(on_done=lambda info: results.append(info))
        agent = _make_agent(callbacks=cb)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.trace.append(StateTraceEntry(state=TurnState.PREPARE, event="ok", duration_ms=5.0))
        agent._state_finalize(ctx)
        self.assertEqual(len(results[0]["trace"]), 1)
        self.assertEqual(results[0]["trace"][0]["state"], "PREPARE")


# ══════════════════════════════════════════════════════════════════════════
# 7. _execute_one
# ══════════════════════════════════════════════════════════════════════════

class ExecuteOneTest(unittest.TestCase):
    def test_injects_session_id(self):
        captured_params = {}

        def capture(name, params):
            captured_params.update(params)
            return {"status": "success", "data": {}}

        reg = _FakeRegistry({"my_tool": False}, execute_fn=capture)
        agent = _make_agent(registry=reg, session_id="sess-42")
        result = agent._execute_one(_tc("1", "my_tool", {"arg1": "val"}))
        self.assertEqual(result["status"], "success")
        self.assertEqual(captured_params.get("_session_id"), "sess-42")

    def test_emits_tool_start_and_done(self):
        events = []
        cb = AgentCallbacks(
            on_tool_start=lambda cid, name, params: events.append(("start", cid, name)),
            on_tool_done=lambda cid, name, result: events.append(("done", cid, name)),
        )
        reg = _FakeRegistry({"my_tool": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg, callbacks=cb)
        agent._execute_one(_tc("1", "my_tool"))
        self.assertEqual(events[0], ("start", "1", "my_tool"))
        self.assertEqual(events[1], ("done", "1", "my_tool"))

    def test_result_has_status_and_data(self):
        reg = _FakeRegistry({"my_tool": False}, execute_fn=lambda n, p: {"status": "success", "data": {"x": 1}})
        agent = _make_agent(registry=reg)
        result = agent._execute_one(_tc("1", "my_tool"))
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["data"]["x"], 1)

    def test_no_session_id_no_injection(self):
        reg = _FakeRegistry({"my_tool": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg, session_id="")
        agent._execute_one(_tc("1", "my_tool"))
        # 不抛异常即可


# ══════════════════════════════════════════════════════════════════════════
# 8. _execute_concurrent_batch
# ══════════════════════════════════════════════════════════════════════════

class ExecuteConcurrentBatchTest(unittest.TestCase):
    def test_all_successful_concurrent(self):
        reg = _FakeRegistry({"a": True, "b": True, "c": True},
                            execute_fn=lambda n, p: {"status": "success", "data": {"tool": n}})
        agent = _make_agent(registry=reg, session_id="sess-concurrent")
        batch = [_tc("1", "a"), _tc("2", "b"), _tc("3", "c")]
        results = agent._execute_concurrent_batch(batch)
        self.assertEqual(len(results), 3)
        names = {tc["name"] for tc, _ in results}
        self.assertEqual(names, {"a", "b", "c"})

    def test_injects_session_id_concurrent(self):
        captured = {}

        def capture(name, params):
            captured[name] = params.get("_session_id")
            return {"status": "success", "data": {}}

        reg = _FakeRegistry({"a": True, "b": True}, execute_fn=capture)
        agent = _make_agent(registry=reg, session_id="sess-cc")
        batch = [_tc("1", "a"), _tc("2", "b")]
        agent._execute_concurrent_batch(batch)
        self.assertEqual(captured.get("a"), "sess-cc")
        self.assertEqual(captured.get("b"), "sess-cc")

    def test_exception_in_one_does_not_affect_others(self):
        def flaky(name, params):
            if name == "bad":
                raise RuntimeError("boom")
            return {"status": "success", "data": {}}

        reg = _FakeRegistry({"good": True, "bad": True}, execute_fn=flaky)
        agent = _make_agent(registry=reg)
        batch = [_tc("1", "good"), _tc("2", "bad")]
        results = agent._execute_concurrent_batch(batch)
        self.assertEqual(len(results), 2)
        statuses = {tc["id"]: r["status"] for tc, r in results}
        self.assertEqual(statuses["1"], "success")
        self.assertEqual(statuses["2"], "error")

    def test_no_session_id_no_injection(self):
        reg = _FakeRegistry({"a": True}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg, session_id="")
        batch = [_tc("1", "a")]
        agent._execute_concurrent_batch(batch)
        # 不抛异常即可

    def test_emits_tool_start_and_done_for_each(self):
        starts = []
        dones = []
        cb = AgentCallbacks(
            on_tool_start=lambda cid, n, p: starts.append(cid),
            on_tool_done=lambda cid, n, r: dones.append(cid),
        )
        reg = _FakeRegistry({"a": True, "b": True}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg, callbacks=cb)
        batch = [_tc("1", "a"), _tc("2", "b")]
        agent._execute_concurrent_batch(batch)
        self.assertEqual(set(starts), {"1", "2"})
        self.assertEqual(set(dones), {"1", "2"})


# ══════════════════════════════════════════════════════════════════════════
# 9. Hook 辅助方法
# ══════════════════════════════════════════════════════════════════════════

class ApplyBeforeTurnHookTest(unittest.TestCase):
    def test_no_hook_returns_none(self):
        agent = _make_agent(hooks=[])
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        result = agent._apply_before_turn_hook(ctx)
        self.assertIsNone(result)

    def test_hook_modifies_messages(self):
        class _AddSystem(AgentHook):
            def before_turn(self, ctx: BeforeTurnContext):
                return [{"role": "system", "content": "sys"}] + ctx.messages

        agent = _make_agent(hooks=[_AddSystem()])
        ctx = TurnContext(messages=[{"role": "user", "content": "hi"}], tools=None)
        result = agent._apply_before_turn_hook(ctx)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "system")

    def test_hook_raises_returns_none(self):
        class _Bad(AgentHook):
            def before_turn(self, ctx: BeforeTurnContext):
                raise RuntimeError("fail")

        agent = _make_agent(hooks=[_Bad()])
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        result = agent._apply_before_turn_hook(ctx)
        self.assertIsNone(result)


class ApplyBeforeToolsHookTest(unittest.TestCase):
    def test_no_hook_returns_empty_dict(self):
        agent = _make_agent(hooks=[])
        ctx = TurnContext(messages=[], tools=None)
        ctx.tool_calls = [_tc("1", "a")]
        self.assertEqual(agent._apply_before_tools_hook(ctx), {})

    def test_hook_rejects_all(self):
        class _AllReject(AgentHook):
            def before_execute_tools(self, ctx: BeforeToolsContext):
                return [reject(tc.id, "nope") for tc in ctx.tool_calls]

        agent = _make_agent(hooks=[_AllReject()])
        ctx = TurnContext(messages=[], tools=None)
        ctx.tool_calls = [_tc("1", "a"), _tc("2", "b")]
        rejections = agent._apply_before_tools_hook(ctx)
        self.assertEqual(set(rejections.keys()), {"1", "2"})

    def test_hook_raises_rejects_all(self):
        class _Boom(AgentHook):
            reraise = True

            def before_execute_tools(self, ctx: BeforeToolsContext):
                raise RuntimeError("boom")

        agent = _make_agent(hooks=[_Boom()])
        ctx = TurnContext(messages=[], tools=None)
        ctx.tool_calls = [_tc("1", "a"), _tc("2", "b")]
        rejections = agent._apply_before_tools_hook(ctx)
        self.assertEqual(set(rejections.keys()), {"1", "2"})
        self.assertTrue(all(d.is_reject for d in rejections.values()))

    def test_hook_returns_none_no_rejections(self):
        class _AllowAll(AgentHook):
            def before_execute_tools(self, ctx: BeforeToolsContext):
                return None

        agent = _make_agent(hooks=[_AllowAll()])
        ctx = TurnContext(messages=[], tools=None)
        ctx.tool_calls = [_tc("1", "a")]
        self.assertEqual(agent._apply_before_tools_hook(ctx), {})


class FireAfterIterationTest(unittest.TestCase):
    def test_no_hook_does_nothing(self):
        agent = _make_agent(hooks=[])
        ctx = TurnContext(messages=[], tools=None)
        # 不应抛异常
        agent._fire_after_iteration(ctx, [])

    def test_hook_receives_context(self):
        received = []

        class _Recorder(AgentHook):
            def after_iteration(self, ctx: AfterIterationContext):
                received.append(ctx)

        agent = _make_agent(hooks=[_Recorder()])
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.full_text = "result"
        ctx.error_message = "err"
        agent._fire_after_iteration(ctx, [({"id": "1", "name": "t", "arguments": {}}, {"status": "success"})])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].full_text, "result")
        self.assertEqual(received[0].error, "err")
        self.assertEqual(len(received[0].tool_calls), 1)
        self.assertEqual(len(received[0].tool_results), 1)

    def test_hook_raises_does_not_crash(self):
        class _Bad(AgentHook):
            def after_iteration(self, ctx: AfterIterationContext):
                raise RuntimeError("oops")

        agent = _make_agent(hooks=[_Bad()])
        ctx = TurnContext(messages=[], tools=None)
        agent._fire_after_iteration(ctx, [])
        # 不抛异常


# ══════════════════════════════════════════════════════════════════════════
# 10. Trace 方法
# ══════════════════════════════════════════════════════════════════════════

class TraceMethodsTest(unittest.TestCase):
    def test_trace_start_when_store_is_none(self):
        agent = _make_agent(trace_store=None)
        agent._trace_start()
        # 不抛异常

    def test_trace_start_calls_store(self):
        store = _FakeTraceStore()
        agent = _make_agent(trace_store=store, session_id="s1")
        agent._trace_start()
        self.assertEqual(len(store.starts), 1)
        self.assertEqual(store.starts[0][0], agent._trace_id)
        self.assertEqual(store.starts[0][1], "s1")

    def test_trace_finish_calls_store(self):
        store = _FakeTraceStore()
        agent = _make_agent(trace_store=store)
        ctx = TurnContext(messages=[], tools=None)
        ctx.turn_count = 3
        ctx.trace.append(StateTraceEntry(state=TurnState.STREAM, event="no_tools", duration_ms=10.0))
        agent._trace_finish(ctx, "ok", time.perf_counter() - 1.0, error=None)
        self.assertEqual(len(store.state_traces), 1)
        self.assertEqual(len(store.finishes), 1)
        self.assertEqual(store.finishes[0]["status"], "ok")
        self.assertEqual(store.finishes[0]["turn_count"], 3)

    def test_trace_finish_with_error(self):
        store = _FakeTraceStore()
        agent = _make_agent(trace_store=store)
        ctx = TurnContext(messages=[], tools=None)
        agent._trace_finish(ctx, "error", time.perf_counter() - 1.0, error="fail")
        self.assertEqual(store.finishes[0]["status"], "error")
        self.assertEqual(store.finishes[0]["error"], "fail")

    def test_trace_tool_call(self):
        store = _FakeTraceStore()
        agent = _make_agent(trace_store=store)
        agent._trace_tool_call("c1", "search", {"q": "x"}, {"status": "success"}, 42.0)
        self.assertEqual(len(store.tool_calls), 1)
        self.assertEqual(store.tool_calls[0]["call_id"], "c1")
        self.assertEqual(store.tool_calls[0]["duration_ms"], 42.0)

    def test_trace_tool_call_when_store_none(self):
        agent = _make_agent(trace_store=None)
        agent._trace_tool_call("c1", "x", {}, {}, 0.0)
        # 不抛异常

    def test_trace_start_store_raises_no_crash(self):
        store = MagicMock()
        store.start_trace.side_effect = RuntimeError("oops")
        agent = _make_agent(trace_store=store)
        agent._trace_start()
        # 不抛异常

    def test_trace_finish_store_raises_no_crash(self):
        store = MagicMock()
        store.record_state_trace.side_effect = RuntimeError("oops")
        agent = _make_agent(trace_store=store)
        ctx = TurnContext(messages=[], tools=None)
        agent._trace_finish(ctx, "ok", time.perf_counter(), error=None)
        # 不抛异常

    def test_trace_tool_call_store_raises_no_crash(self):
        store = MagicMock()
        store.record_tool_call.side_effect = RuntimeError("oops")
        agent = _make_agent(trace_store=store)
        agent._trace_tool_call("c1", "x", {}, {}, 0.0)
        # 不抛异常


# ══════════════════════════════════════════════════════════════════════════
# 11. Callback 发射辅助
# ══════════════════════════════════════════════════════════════════════════

class CallbackEmissionTest(unittest.TestCase):
    def test_text_chunk_callback(self):
        chunks = []
        cb = AgentCallbacks(on_text_chunk=lambda d: chunks.append(d))
        agent = _make_agent(callbacks=cb)
        agent._emit_text_chunk("hello")
        agent._emit_text_chunk(" world")
        self.assertEqual(chunks, ["hello", " world"])

    def test_text_chunk_no_callback_no_crash(self):
        agent = _make_agent(callbacks=AgentCallbacks.silent())
        agent._emit_text_chunk("x")

    def test_tool_start_callback(self):
        starts = []
        cb = AgentCallbacks(on_tool_start=lambda cid, n, p: starts.append((cid, n)))
        agent = _make_agent(callbacks=cb)
        agent._emit_tool_start("c1", "search", {"q": "x"})
        self.assertEqual(starts, [("c1", "search")])

    def test_tool_done_callback(self):
        dones = []
        cb = AgentCallbacks(on_tool_done=lambda cid, n, r: dones.append((cid, n)))
        agent = _make_agent(callbacks=cb)
        agent._emit_tool_done("c1", "search", {"status": "success"})
        self.assertEqual(dones, [("c1", "search")])

    def test_state_change_callback(self):
        states = []
        cb = AgentCallbacks(on_state_change=lambda s: states.append(s))
        agent = _make_agent(callbacks=cb)
        agent._emit_state_change("STREAM")
        self.assertEqual(states, ["STREAM"])

    def test_new_turn_callback(self):
        turns = []
        cb = AgentCallbacks(on_new_turn=lambda tc: turns.append(tc))
        agent = _make_agent(callbacks=cb)
        agent._emit_new_turn(3)
        self.assertEqual(turns, [3])

    def test_done_callback(self):
        results = []
        cb = AgentCallbacks(on_done=lambda info: results.append(info))
        agent = _make_agent(callbacks=cb)
        agent._emit_done({"ok": True})
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["ok"])

    def test_callback_raises_no_crash(self):
        cb = AgentCallbacks(on_text_chunk=lambda d: (_ for _ in ()).throw(RuntimeError("boom")))
        agent = _make_agent(callbacks=cb)
        agent._emit_text_chunk("x")
        # 不抛异常

    def test_all_callbacks_fire_with_collect(self):
        collector: dict = {}
        cb = AgentCallbacks.collect(collector)
        agent = _make_agent(callbacks=cb)
        agent._emit_text_chunk("t1")
        agent._emit_tool_start("c1", "t", {})
        agent._emit_tool_done("c1", "t", {})
        agent._emit_state_change("EXECUTE")
        agent._emit_new_turn(2)
        agent._emit_done({"ok": True})

        self.assertEqual(collector["text"], ["t1"])
        self.assertEqual(len(collector["tools"]), 2)
        self.assertEqual(collector["states"], ["EXECUTE"])
        self.assertEqual(collector["turns"], [2])
        self.assertEqual(len(collector["result"]), 1)


# ══════════════════════════════════════════════════════════════════════════
# 12. 外部控制接口
# ══════════════════════════════════════════════════════════════════════════

class ExternalControlTest(unittest.TestCase):
    def test_cancel_sets_cancel_token_and_puts_queue(self):
        cancel_token = CancellationToken()
        agent = _make_agent(cancel_token=cancel_token)
        self.assertFalse(cancel_token.is_cancelled())
        agent.cancel()
        self.assertTrue(cancel_token.is_cancelled())
        # input_queue 应有一个项
        self.assertFalse(agent._input_queue.empty())

    def test_supply_input_puts_to_queue(self):
        agent = _make_agent()
        self.assertTrue(agent._input_queue.empty())
        agent.supply_input({"param": "value"})
        self.assertFalse(agent._input_queue.empty())
        self.assertEqual(agent._input_queue.get(), {"param": "value"})

    def test_inject_message_puts_to_queue(self):
        agent = _make_agent()
        self.assertTrue(agent._inject_queue.empty())
        agent.inject_message({"role": "user", "content": "hi"})
        self.assertFalse(agent._inject_queue.empty())
        self.assertEqual(agent._inject_queue.get(), {"role": "user", "content": "hi"})


# ══════════════════════════════════════════════════════════════════════════
# 13. run_sync — 同步运行完整流程
# ══════════════════════════════════════════════════════════════════════════

class RunSyncTest(unittest.TestCase):
    def test_simple_no_tool_response(self):
        chunks = [
            {"type": "text", "delta": "Hello!"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(
            gateway=gw,
            messages=[{"role": "user", "content": "hi"}],
        )
        result = agent.run_sync()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])

    def test_one_tool_call_iteration(self):
        # LLM 先返回 tool_call，然后反馈后返回纯文本
        stream1 = [
            {"type": "tool_call", "id": "t1", "name": "tool_a", "arguments": {"arg": "val"}},
            {"type": "done"},
        ]
        stream2 = [
            {"type": "text", "delta": "Done!"},
            {"type": "done"},
        ]
        gw = _FakeGateway(stream1)  # 初始 chunks
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})

        # 需要让 gateway 在第二次调用时返回不同的 chunks
        call_seq = [0]

        def multi_stream(messages, tools, **kwargs):
            idx = call_seq[0]
            call_seq[0] += 1
            gw.received_tools = tools
            if idx == 0:
                yield from stream1
            else:
                yield from stream2

        gw.chat_stream = multi_stream

        agent = _make_agent(
            gateway=gw,
            registry=reg,
            messages=[{"role": "user", "content": "do it"}],
        )
        result = agent.run_sync()
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])

    def test_run_sync_with_cancellation(self):
        cancel_token = CancellationToken()
        chunks = [
            {"type": "text", "delta": "starting"},
            {"type": "text", "delta": " more"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)

        # 在第一次 stream 时触发取消
        orig = gw.chat_stream

        def cancelling_stream(*args, **kwargs):
            cancel_token.cancel()
            yield from orig(*args, **kwargs)

        gw.chat_stream = cancelling_stream

        agent = _make_agent(
            gateway=gw,
            cancel_token=cancel_token,
            messages=[{"role": "user", "content": "hi"}],
        )
        result = agent.run_sync()
        self.assertFalse(result["ok"])

    def test_run_sync_error_in_stream(self):
        chunks = [{"type": "error", "message": "API error"}]
        gw = _FakeGateway(chunks)
        agent = _make_agent(
            gateway=gw,
            messages=[{"role": "user", "content": "hi"}],
        )
        result = agent.run_sync()
        self.assertFalse(result["ok"])
        self.assertIn("API error", result["error"])

    def test_run_sync_empty_messages(self):
        agent = _make_agent(messages=[])
        result = agent.run_sync()
        # PREPARE 返回 "empty" → DONE，快速路径无错误
        self.assertTrue(result["ok"])
        self.assertIsNone(result["error"])

    def test_run_sync_max_turns_with_tools(self):
        # 每次 LLM 都返回 tool_call，触发 max_turns → wrap_up
        tool_stream = [
            {"type": "tool_call", "id": "t1", "name": "tool_a", "arguments": {}},
            {"type": "done"},
        ]
        wrap_stream = [
            {"type": "text", "delta": "Final!"},
            {"type": "done"},
        ]
        gw = _FakeGateway(tool_stream)
        reg = _FakeRegistry({"tool_a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})

        call_seq = [0]

        def multi_stream(messages, tools, **kwargs):
            idx = call_seq[0]
            call_seq[0] += 1
            # 第一轮和第二轮返回 tool_call，第三轮（wrap_up）返回文本
            if idx == 0 or idx == 1:
                yield from tool_stream
            else:
                yield from wrap_stream

        gw.chat_stream = multi_stream

        agent = _make_agent(
            gateway=gw,
            registry=reg,
            messages=[{"role": "user", "content": "loop"}],
            max_turns=2,
        )
        result = agent.run_sync()
        self.assertTrue(result["ok"])

    def test_run_sync_trace_included(self):
        chunks = [
            {"type": "text", "delta": "ok"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(
            gateway=gw,
            messages=[{"role": "user", "content": "hi"}],
        )
        result = agent.run_sync()
        self.assertIn("trace", result)
        self.assertIsInstance(result["trace"], list)
        # 至少包含 PREPARE → STREAM → FINALIZE
        states = [e["state"] for e in result["trace"]]
        self.assertIn("PREPARE", states)
        self.assertIn("STREAM", states)
        self.assertIn("FINALIZE", states)

    def test_run_sync_fatal_tool_error(self):
        chunks = [
            {"type": "tool_call", "id": "t1", "name": "bad_tool", "arguments": {}},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        reg = _FakeRegistry({"bad_tool": False}, execute_fn=lambda n, p: {
            "status": "error",
            "data": {"message": "not found", "error_type": ToolErrorType.TOOL_NOT_FOUND.value, "retryable": False},
        })
        agent = _make_agent(
            gateway=gw,
            registry=reg,
            messages=[{"role": "user", "content": "do"}],
        )
        result = agent.run_sync()
        self.assertFalse(result["ok"])
        self.assertIsNotNone(result["error"])


# ══════════════════════════════════════════════════════════════════════════
# 14. start() / wait() / is_running / result — 异步生命周期
# ══════════════════════════════════════════════════════════════════════════

class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self._agents: list[Agent] = []

    def tearDown(self):
        for a in self._agents:
            try:
                a.cancel()
            except Exception:
                pass
        # 等待所有线程结束
        for a in self._agents:
            if a._thread is not None:
                a._thread.join(timeout=2.0)

    def _make(self, **kw) -> Agent:
        chunks = [
            {"type": "text", "delta": "quick"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(
            gateway=gw,
            messages=[{"role": "user", "content": "hi"}],
            **kw,
        )
        self._agents.append(agent)
        return agent

    def test_start_and_wait(self):
        # 使用慢速 gateway 确保线程不会在 start() 返回前结束
        started = threading.Event()
        proceed = threading.Event()

        class _BlockingGateway:
            def chat_stream(self, messages, tools, **kwargs):
                started.set()
                proceed.wait(timeout=5.0)
                yield {"type": "text", "delta": "ok"}
                yield {"type": "done"}

        gw = _BlockingGateway()
        agent = _make_agent(gateway=gw, messages=[{"role": "user", "content": "hi"}])
        self._agents.append(agent)

        self.assertFalse(agent.is_running)
        agent.start()
        started.wait(timeout=2.0)
        self.assertTrue(agent.is_running)
        proceed.set()
        result = agent.wait(timeout=5.0)
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertFalse(agent.is_running)

    def test_run_sync_sets_result(self):
        agent = self._make()
        result = agent.run_sync()
        self.assertEqual(agent.result, result)
        self.assertTrue(result["ok"])

    def test_start_already_running_raises(self):
        def test_start_already_running_raises(self):
            started = threading.Event()
            proceed = threading.Event()
    
            class _BlockingGateway:
                def chat_stream(self, messages, tools, **kwargs):
                    started.set()
                    proceed.wait(timeout=5.0)
                    yield {"type": "text", "delta": "ok"}
                    yield {"type": "done"}
    
            gw = _BlockingGateway()
            agent = _make_agent(gateway=gw, messages=[{"role": "user", "content": "hi"}])
            self._agents.append(agent)
            agent.start()
            started.wait(timeout=2.0)
            with self.assertRaises(RuntimeError) as cm:
                agent.start()
            self.assertIn("already running", str(cm.exception))
            proceed.set()
            agent.wait(timeout=5.0)
    def test_wait_timeout_returns_none(self):
        # 构造一个长时间运行的 agent
        chunks = [
            {"type": "text", "delta": "zzz"},
            {"type": "done"},
        ]

        class _SlowGateway:
            def chat_stream(self, messages, tools, **kwargs):
                time.sleep(5.0)  # 超长 sleep
                yield {"type": "done"}
                return

        gw = _SlowGateway()
        agent = _make_agent(gateway=gw, messages=[{"role": "user", "content": "hi"}])
        self._agents.append(agent)
        agent.start()
        result = agent.wait(timeout=0.1)
        self.assertIsNone(result)
        agent.cancel()
        agent.wait(timeout=3.0)

    def test_result_none_before_run(self):
        agent = self._make()
        self.assertIsNone(agent.result)

    def test_is_running_false_before_start(self):
        agent = self._make()
        self.assertFalse(agent.is_running)

    def test_done_event_set_after_run_sync(self):
        agent = self._make()
        self.assertFalse(agent._done_event.is_set())
        agent.run_sync()
        self.assertTrue(agent._done_event.is_set())


# ══════════════════════════════════════════════════════════════════════════
# 15. _get_remaining_calls
# ══════════════════════════════════════════════════════════════════════════

class RemainingCallsComprehensiveTest(unittest.TestCase):
    def test_middle_batch(self):
        agent = _make_agent()
        b1 = [_tc("1"), _tc("2")]
        b2 = [_tc("3")]
        b3 = [_tc("4"), _tc("5")]
        all_batches = [("concurrent", b1), ("serial", b2), ("concurrent", b3)]
        remaining = agent._get_remaining_calls([], b2, all_batches)
        self.assertEqual([tc["id"] for tc in remaining], ["4", "5"])

    def test_first_batch(self):
        agent = _make_agent()
        b1 = [_tc("1")]
        b2 = [_tc("2")]
        all_batches = [("serial", b1), ("serial", b2)]
        remaining = agent._get_remaining_calls([], b1, all_batches)
        self.assertEqual([tc["id"] for tc in remaining], ["2"])

    def test_last_batch_returns_empty(self):
        agent = _make_agent()
        b1 = [_tc("1")]
        b2 = [_tc("2")]
        all_batches = [("serial", b1), ("serial", b2)]
        remaining = agent._get_remaining_calls([], b2, all_batches)
        self.assertEqual(remaining, [])

    def test_empty_batches(self):
        agent = _make_agent()
        remaining = agent._get_remaining_calls([], [], [])
        self.assertEqual(remaining, [])

    def test_batch_not_found_returns_empty(self):
        agent = _make_agent()
        b1 = [_tc("1")]
        unknown = [_tc("99")]
        all_batches = [("serial", b1)]
        remaining = agent._get_remaining_calls([], unknown, all_batches)
        self.assertEqual(remaining, [])


# ══════════════════════════════════════════════════════════════════════════
# 16. 综合场景 / 回归测试
# ══════════════════════════════════════════════════════════════════════════

class IntegrationScenariosTest(unittest.TestCase):
    def test_full_pipeline_with_collect_callbacks(self):
        """验证 AgentCallbacks.collect() 能捕获完整的运行过程。"""
        collector: dict = {}
        cb = AgentCallbacks.collect(collector)

        chunks = [
            {"type": "text", "delta": "Answer"},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(
            gateway=gw,
            callbacks=cb,
            messages=[{"role": "user", "content": "q"}],
        )
        result = agent.run_sync()
        self.assertTrue(result["ok"])
        self.assertIn("text", collector)
        self.assertIn("states", collector)
        self.assertIn("result", collector)
        self.assertEqual(collector["text"], ["Answer"])

    def test_tool_stream_text_then_tool(self):
        """流中既有文本又有工具调用。"""
        chunks = [
            {"type": "text", "delta": "Let me check."},
            {"type": "tool_call", "id": "c1", "name": "search", "arguments": {"q": "x"}},
            {"type": "done"},
        ]
        gw = _FakeGateway(chunks)
        agent = _make_agent(gateway=gw)
        ctx = TurnContext(messages=[{"role": "user"}], tools=[{"type": "function"}])
        event = agent._state_stream(ctx)
        self.assertEqual(event, "has_tools")
        self.assertEqual(ctx.full_text, "Let me check.")
        self.assertEqual(len(ctx.tool_calls), 1)

    def test_concurrent_and_serial_mixed_execution(self):
        """混合并发和串行工具的执行顺序。"""
        executed_order = []

        def track(name, params):
            executed_order.append(name)
            return {"status": "success", "data": {}}

        # read_only=True → concurrent, read_only=False → serial
        reg = _FakeRegistry({"ro1": True, "ro2": True, "rw": False, "ro3": True}, execute_fn=track)
        agent = _make_agent(registry=reg)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.tool_calls = [
            _tc("1", "ro1"),
            _tc("2", "ro2"),
            _tc("3", "rw"),
            _tc("4", "ro3"),
        ]
        event = agent._state_execute(ctx)
        self.assertEqual(event, "ok")
        # ro1/ro2 并发先执行（顺序不确定），rw 串行，ro3 并发执行
        # 但 rw 必须在 ro3 之前
        rw_idx = executed_order.index("rw")
        self.assertLess(rw_idx, len(executed_order) - 1)  # rw 不是最后一个（因为 ro3 在后面）
        # ro3 在 rw 之后
        self.assertIn("ro3", executed_order[rw_idx + 1:])

    def test_multiple_tool_calls_in_assistant_message_format(self):
        """验证 assistant 消息的 tool_calls 格式化正确。"""
        reg = _FakeRegistry({"a": False}, execute_fn=lambda n, p: {"status": "success", "data": {}})
        agent = _make_agent(registry=reg)
        ctx = TurnContext(messages=[{"role": "user"}], tools=None)
        ctx.tool_calls = [
            {"id": "c1", "name": "a", "arguments": {"x": 1}},
            {"id": "c2", "name": "a", "arguments": {"y": 2}},
        ]
        agent._state_execute(ctx)
        assistant_msg = ctx.messages[1]
        self.assertEqual(assistant_msg["role"], "assistant")
        self.assertEqual(len(assistant_msg["tool_calls"]), 2)
        self.assertEqual(assistant_msg["tool_calls"][0]["id"], "c1")
        self.assertEqual(assistant_msg["tool_calls"][0]["function"]["name"], "a")
        # arguments 应为 JSON 字符串
        self.assertIsInstance(assistant_msg["tool_calls"][0]["function"]["arguments"], str)


if __name__ == "__main__":
    unittest.main()