"""AgentLoop 纯逻辑单测 — 批次分区、剩余调用计算、trace 序列化、hook 拒绝映射。

不启动 QThread.run()，只在主线程直接调被测方法。需要 QApplication 才能
实例化 QObject 子类，故 setUpClass 建一个。
"""
import unittest

from PyQt6.QtWidgets import QApplication

from app.core.agent_hooks import AgentHook, BeforeToolsContext, ToolDecision, reject
from app.core.agent_loop import AgentLoop
from app.core.turn_context import StateTraceEntry, TurnContext, TurnState


class _FakeTool:
    def __init__(self, read_only: bool):
        self.read_only = read_only


class _FakeRegistry:
    """按名字返回预设 read_only 标志的假注册表。"""

    def __init__(self, read_only_map: dict[str, bool]):
        self._map = read_only_map

    def get(self, name):
        if name not in self._map:
            return None
        return _FakeTool(self._map[name])

    def get_openai_functions(self):
        return []


def _make_loop(registry) -> AgentLoop:
    return AgentLoop(
        llm_gateway=object(),
        registry=registry,
        api_messages=[],
        session_id="s1",
    )


class PartitionBatchesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tc(self, call_id, name):
        return {"id": call_id, "name": name, "arguments": {}}

    def test_all_readonly_grouped_concurrent(self):
        reg = _FakeRegistry({"read": True})
        loop = _make_loop(reg)
        calls = [self._tc("1", "read"), self._tc("2", "read"), self._tc("3", "read")]
        batches = loop._partition_batches(calls)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0][0], "concurrent")
        self.assertEqual(len(batches[0][1]), 3)

    def test_writes_are_serial(self):
        reg = _FakeRegistry({"write": False})
        loop = _make_loop(reg)
        calls = [self._tc("1", "write"), self._tc("2", "write")]
        batches = loop._partition_batches(calls)
        self.assertEqual([m for m, _ in batches], ["serial", "serial"])

    def test_mixed_preserves_order_and_splits(self):
        reg = _FakeRegistry({"read": True, "write": False})
        loop = _make_loop(reg)
        calls = [
            self._tc("1", "read"),
            self._tc("2", "read"),
            self._tc("3", "write"),
            self._tc("4", "read"),
        ]
        batches = loop._partition_batches(calls)
        # [concurrent(1,2), serial(3), concurrent(4)]
        self.assertEqual([m for m, _ in batches], ["concurrent", "serial", "concurrent"])
        self.assertEqual([tc["id"] for tc in batches[0][1]], ["1", "2"])
        self.assertEqual([tc["id"] for tc in batches[1][1]], ["3"])
        self.assertEqual([tc["id"] for tc in batches[2][1]], ["4"])

    def test_unknown_tool_treated_as_write(self):
        reg = _FakeRegistry({})  # get() 返回 None → is_ro=False → serial
        loop = _make_loop(reg)
        calls = [self._tc("1", "mystery")]
        batches = loop._partition_batches(calls)
        self.assertEqual(batches[0][0], "serial")


class RemainingCallsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _tc(self, call_id):
        return {"id": call_id, "name": "x", "arguments": {}}

    def test_remaining_after_first_batch(self):
        loop = _make_loop(_FakeRegistry({}))
        b1 = [self._tc("1")]
        b2 = [self._tc("2")]
        b3 = [self._tc("3")]
        all_batches = [("serial", b1), ("serial", b2), ("serial", b3)]
        remaining = loop._get_remaining_calls([], b1, all_batches)
        self.assertEqual([tc["id"] for tc in remaining], ["2", "3"])

    def test_no_remaining_after_last_batch(self):
        loop = _make_loop(_FakeRegistry({}))
        b1 = [self._tc("1")]
        b2 = [self._tc("2")]
        all_batches = [("serial", b1), ("serial", b2)]
        remaining = loop._get_remaining_calls([], b2, all_batches)
        self.assertEqual(remaining, [])


class SerializeTraceTest(unittest.TestCase):
    def test_serialize_rounds_and_maps_fields(self):
        ctx = TurnContext(messages=[], tools=None)
        ctx.trace.append(StateTraceEntry(state=TurnState.STREAM, event="has_tools", duration_ms=12.345))
        ctx.trace.append(StateTraceEntry(state=TurnState.EXECUTE, event="ok", duration_ms=7.0))
        out = AgentLoop._serialize_trace(ctx)
        self.assertEqual(out, [
            {"state": "STREAM", "event": "has_tools", "duration_ms": 12.3},
            {"state": "EXECUTE", "event": "ok", "duration_ms": 7.0},
        ])


class TransitionTableTest(unittest.TestCase):
    """状态机转换表：EXECUTE 阶段的致命工具错误必须有明确转换。"""

    def test_execute_error_transitions_to_finalize(self):
        from app.core.turn_context import TRANSITIONS

        # 缺失此转换时，_state_execute 返回 "error" 会落到 run() 的兜底分支，
        # 用 "Invalid transition" 覆盖掉真实错误文案（见 agent_loop 兜底逻辑）。
        self.assertEqual(
            TRANSITIONS.get((TurnState.EXECUTE, "error")),
            TurnState.FINALIZE,
        )


class _RejectAllHook(AgentHook):
    def before_execute_tools(self, ctx: BeforeToolsContext):
        return [reject(tc.id, "nope") for tc in ctx.tool_calls]


class _BoomHook(AgentHook):
    reraise = True

    def before_execute_tools(self, ctx: BeforeToolsContext):
        raise RuntimeError("hook boom")


class BeforeToolsHookTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _ctx_with_calls(self):
        ctx = TurnContext(messages=[], tools=None)
        ctx.tool_calls = [
            {"id": "1", "name": "a", "arguments": {}},
            {"id": "2", "name": "b", "arguments": {}},
        ]
        return ctx

    def test_no_hook_allows_all(self):
        loop = _make_loop(_FakeRegistry({}))
        rejections = loop._apply_before_tools_hook(self._ctx_with_calls())
        self.assertEqual(rejections, {})

    def test_reject_hook_maps_all_calls(self):
        loop = AgentLoop(
            llm_gateway=object(), registry=_FakeRegistry({}),
            api_messages=[], session_id="s1", hooks=[_RejectAllHook()],
        )
        rejections = loop._apply_before_tools_hook(self._ctx_with_calls())
        self.assertEqual(set(rejections.keys()), {"1", "2"})
        self.assertTrue(all(d.is_reject for d in rejections.values()))

    def test_reraise_hook_exception_rejects_all(self):
        # 安全 hook 抛异常时，必须拒绝本轮全部调用，不能照常执行
        loop = AgentLoop(
            llm_gateway=object(), registry=_FakeRegistry({}),
            api_messages=[], session_id="s1", hooks=[_BoomHook()],
        )
        rejections = loop._apply_before_tools_hook(self._ctx_with_calls())
        self.assertEqual(set(rejections.keys()), {"1", "2"})
        self.assertTrue(all(d.is_reject for d in rejections.values()))


class _FakeGateway:
    """按预设 chunk 序列驱动 chat_stream 的假网关，记录收到的 tools 参数。"""

    def __init__(self, chunks):
        self._chunks = chunks
        self.received_tools = "unset"

    def chat_stream(self, messages, tools, **kwargs):
        self.received_tools = tools
        yield from self._chunks


class WrapUpStateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_loop(self, chunks):
        gw = _FakeGateway(chunks)
        loop = AgentLoop(
            llm_gateway=gw, registry=_FakeRegistry({}),
            api_messages=[], session_id="s1",
        )
        return loop, gw

    def test_wrap_up_emits_text_and_returns_ok(self):
        chunks = [
            {"type": "text", "delta": "最终答复"},
            {"type": "done"},
        ]
        loop, gw = self._make_loop(chunks)
        ctx = TurnContext(messages=[], tools=[{"x": 1}], max_turns=10)
        event = loop._state_wrap_up(ctx)
        self.assertEqual(event, "ok")
        self.assertEqual(ctx.full_text, "最终答复")
        self.assertIsNone(ctx.error_message)
        # 收尾轮必须不下发 tools，模型才能纯文本收尾
        self.assertIsNone(gw.received_tools)

    def test_wrap_up_empty_text_sets_error(self):
        chunks = [{"type": "done"}]  # 模型无任何文字
        loop, _ = self._make_loop(chunks)
        ctx = TurnContext(messages=[], tools=None, max_turns=10)
        event = loop._state_wrap_up(ctx)
        self.assertEqual(event, "error")
        self.assertIn("最大工具调用轮数", ctx.error_message)

    def test_wrap_up_discards_tool_calls(self):
        chunks = [
            {"type": "tool_call", "id": "t1", "name": "x", "arguments": {}},
            {"type": "text", "delta": "收尾"},
            {"type": "done"},
        ]
        loop, _ = self._make_loop(chunks)
        ctx = TurnContext(messages=[], tools=[{"x": 1}], max_turns=10)
        event = loop._state_wrap_up(ctx)
        self.assertEqual(event, "ok")
        self.assertEqual(ctx.tool_calls, [])


if __name__ == "__main__":
    unittest.main()
