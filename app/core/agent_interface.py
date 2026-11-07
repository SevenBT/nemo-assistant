"""
Agent 回调接口 — 纯 Python，零 Qt 依赖。

替换 pyqtSignal，使得 Agent 可用于任何 UI 框架或 headless 场景。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentCallbacks:
    """Agent 与外部世界的通信接口。

    所有回调均为可选。未被设置的回调对应的事件将被静默丢弃。
    回调在 Agent 的工作线程中同步调用，应快速返回避免阻塞状态机。
    """

    on_text_chunk: Callable[[str], None] | None = None
    """流式文本增量。每个 delta 是一个片段（可能多 token）。"""

    on_tool_start: Callable[[str, str, dict], None] | None = None
    """工具开始执行。(call_id, tool_name, params_dict)"""

    on_tool_done: Callable[[str, str, dict], None] | None = None
    """工具执行完成。(call_id, tool_name, result_dict)"""

    on_state_change: Callable[[str], None] | None = None
    """状态机状态变更。(state_name)"""

    on_new_turn: Callable[[int], None] | None = None
    """新回合开始。(turn_count)"""

    on_need_input: Callable[[str, str, list], None] | None = None
    """需要用户手动输入参数。(call_id, tool_name, params_list)"""

    on_done: Callable[[dict], None] | None = None
    """Agent 运行完成。(result_dict with keys: ok, error, trace)"""

    on_trace: Callable[[str, dict], None] | None = None
    """Trace 事件回调。(event_name, event_data)"""

    # ── 便捷构造 ──

    @classmethod
    def silent(cls) -> "AgentCallbacks":
        """创建丢弃所有事件的静默实例，用于测试。"""
        return cls()

    @classmethod
    def print(cls) -> "AgentCallbacks":
        """创建打印到 stdout 的调试实例。"""
        return cls(
            on_text_chunk=lambda delta: print(delta, end="", flush=True),
            on_tool_start=lambda cid, name, args: print(f"\n🔧 [{name}] {args}"),
            on_tool_done=lambda cid, name, result: print(f"   ✅ {name}: {result.get('status', '?')}"),
            on_state_change=lambda s: print(f"\n--- [{s}] ---"),
            on_new_turn=lambda tc: print(f"\n=== Turn {tc} ==="),
            on_done=lambda info: print(f"\n{'✅' if info.get('ok') else '❌'} {info.get('error', '')}"),
            on_trace=lambda event, data: print(f"\n📌 [{event}] {data}"),
        )

    @classmethod
    def collect(cls, collector: dict[str, list[Any]]) -> "AgentCallbacks":
        """创建收集所有事件到 dict 的实例，用于测试断言。

        collector 按事件类型收集:
            collector["text"]     → list[str]
            collector["tools"]    → list[tuple[str, str, dict]]
            collector["states"]   → list[str]
            collector["result"]   → list[dict]
            collector["traces"]   → list[tuple[str, dict]]
        """
        return cls(
            on_text_chunk=lambda delta: collector.setdefault("text", []).append(delta),
            on_tool_start=lambda cid, name, args: collector.setdefault("tools", []).append(
                ("start", name, args)
            ),
            on_tool_done=lambda cid, name, result: collector.setdefault("tools", []).append(
                ("done", name, result)
            ),
            on_state_change=lambda s: collector.setdefault("states", []).append(s),
            on_new_turn=lambda tc: collector.setdefault("turns", []).append(tc),
            on_done=lambda info: collector.setdefault("result", []).append(info),
            on_trace=lambda event, data: collector.setdefault("traces", []).append((event, data)),
        )