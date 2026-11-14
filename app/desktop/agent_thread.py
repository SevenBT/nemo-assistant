"""
AgentThread — thin Qt shell around Agent.

Architecture:
    AgentThread subclasses QThread. On its background thread it creates an
    Agent (pure Python, zero Qt) and bridges its AgentCallbacks to
    Qt signals. All state machine logic lives in Agent; AgentThread is
    only responsible for the Qt adaptation layer.

AgentThread — Agent 的 Qt 壳。

整体架构：
    AgentThread 继承 QThread，在后台线程中创建 Agent（纯 Python，零 Qt 依赖）。
    通过 AgentCallbacks 将 Agent 的事件桥接到 Qt 信号，供 UI 层消费。
    所有状态机逻辑都在 Agent 中；AgentThread 仅负责 Qt 适配层。
"""
import logging

from PyQt6.QtCore import QThread, pyqtSignal

from app.agent.agent_hooks import AgentHook
from app.agent.agent_interface import AgentCallbacks
from app.llm.llm_gateway import LLMGateway
from app.agent.agent import Agent
from app.agent.agent_context import AgentContext
from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentThread(QThread):
    """Thin Qt wrapper around Agent.

    Bridges Agent's pure-Python callbacks to Qt signals for UI
    consumption.  The state machine (PREPARE → STREAM → EXECUTE →
    FEEDBACK → WRAP_UP → FINALIZE → DONE) is implemented entirely in
    Agent.

    Signals (unchanged from original AgentThread):
        text_chunk(str)          — streaming text delta
        state_changed(str)       — state machine state name
        tool_event(str,str,dict) — tool lifecycle (call_id, phase, payload)
        need_input(str,str,list) — manual parameter request
        new_turn(int)            — new turn started
        done(dict)               — agent finished {ok, error, trace}
    """

    # ── Qt Signals ──────────────────────────────────────────────────────────
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
        self._trace_store = trace_store
        self._hooks = hooks or []

        self._agent: Agent | None = None
        self._ctx: AgentContext | None = None

    # ── External Control Interface ──────────────────────────────────────────

    def cancel(self):
        """Request cancellation of the current agent run (thread-safe)."""
        if self._agent is not None:
            self._agent.cancel()

    def supply_input(self, params: dict):
        """Supply manual parameters (in response to need_input signal)."""
        if self._agent is not None:
            self._agent.supply_input(params)

    def inject_message(self, message: dict):
        """Mid-turn injection of a user message."""
        if self._agent is not None:
            self._agent.inject_message(message)

    @property
    def _trace_id(self) -> str:
        """Expose Agent's trace_id for eval runner post-run inspection."""
        if self._agent is not None:
            return self._agent._trace_id
        return ""

    # ── QThread Entry Point ─────────────────────────────────────────────────

    def run(self):
        """QThread entry point — build Agent, bridge callbacks, run to
        completion.

        Agent.run_sync() blocks the background thread until the state
        machine finishes.  The on_done callback fires during this call (so
        the Qt ``done`` signal is emitted before we return).  After
        returning, QThread emits ``finished``, which the controller uses
        for cleanup.
        """
        # Build callback bridge: Agent callbacks → Qt signals
        callbacks = AgentCallbacks(
            on_message_complete=lambda payload: self.tool_event.emit("", "message", payload),
            on_text_chunk=lambda delta: self.text_chunk.emit(delta),
            on_tool_start=lambda call_id, name, params: self.tool_event.emit(
                call_id, "start", {"name": name, "params": params}
            ),
            on_tool_done=lambda call_id, name, result: self.tool_event.emit(
                call_id, "done", {"name": name, "result": result}
            ),
            on_state_change=lambda state_name: self.state_changed.emit(state_name),
            on_new_turn=lambda turn_count: self.new_turn.emit(turn_count),
            on_need_input=lambda call_id, tool_name, param_names: self.need_input.emit(
                call_id, tool_name, param_names
            ),
            on_done=lambda info: self.done.emit(info),
        )

        self._ctx = AgentContext(
            callbacks=callbacks,
            hooks=list(self._hooks),
            llm_gateway=self._llm,
            registry=self._registry,
        )

        self._agent = Agent(
            ctx=self._ctx,
            messages=self._messages,
            session_id=self._session_id,
            max_turns=self._max_turns,
            trace_store=self._trace_store,
        )

        self._agent.run_sync()
