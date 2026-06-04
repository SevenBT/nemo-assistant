"""
状态机定义：TurnState、转换表、TurnContext。

状态流转：
    PREPARE → STREAM → EXECUTE → FEEDBACK → STREAM → ... → FINALIZE → DONE
                 ↓ (no_tools)                  ↓ (max_turns)
              FINALIZE                      FINALIZE
"""
import time
from dataclasses import dataclass, field
from enum import Enum, auto


class TurnState(Enum):
    """Agent 单轮对话的状态。"""

    PREPARE = auto()
    STREAM = auto()
    EXECUTE = auto()
    FEEDBACK = auto()
    FINALIZE = auto()
    DONE = auto()


# ── 转换表 ────────────────────────────────────────────────────────────────

TRANSITIONS: dict[tuple[TurnState, str], TurnState] = {
    (TurnState.PREPARE, "ok"): TurnState.STREAM,
    (TurnState.PREPARE, "empty"): TurnState.DONE,
    (TurnState.STREAM, "no_tools"): TurnState.FINALIZE,
    (TurnState.STREAM, "has_tools"): TurnState.EXECUTE,
    (TurnState.STREAM, "error"): TurnState.FINALIZE,
    (TurnState.STREAM, "cancelled"): TurnState.FINALIZE,
    (TurnState.EXECUTE, "ok"): TurnState.FEEDBACK,
    (TurnState.EXECUTE, "cancelled"): TurnState.FINALIZE,
    (TurnState.FEEDBACK, "continue"): TurnState.STREAM,
    (TurnState.FEEDBACK, "max_turns"): TurnState.FINALIZE,
    (TurnState.FINALIZE, "ok"): TurnState.DONE,
}


@dataclass
class StateTraceEntry:
    """记录单个状态的执行信息。"""

    state: TurnState
    event: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class TurnContext:
    """贯穿整个 turn 的上下文，替代散落的局部变量。"""

    messages: list[dict]
    tools: list[dict] | None
    max_turns: int = 10

    # ── 运行时状态 ──
    state: TurnState = TurnState.PREPARE
    turn_count: int = 0
    full_text: str = ""
    reasoning_content: str | None = None
    tool_calls: list[dict] = field(default_factory=list)
    error_message: str | None = None

    # ── 追踪 ──
    trace: list[StateTraceEntry] = field(default_factory=list)

    def reset_turn(self):
        """每轮 STREAM 开始前重置临时变量。"""
        self.full_text = ""
        self.reasoning_content = None
        self.tool_calls = []
