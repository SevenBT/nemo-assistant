"""Single-run Agent facade: lifecycle, cancellation, settlement and observation."""
from __future__ import annotations

import copy
from enum import Enum, auto
import logging
import queue
import threading
import time
import uuid

from app.agent.agent_context import AgentContext
from app.agent.agent_loop import AgentLoop
from app.agent.contracts import TraceSink
from app.agent.execution_policy import ExecutionPolicy, resolve_policy

logger = logging.getLogger(__name__)


class RunState(Enum):
    CREATED = auto()
    RUNNING = auto()
    SETTLING = auto()
    FINISHED = auto()


class Agent:
    """One execution, synchronously or on an owned background thread.

    Sessions belong to the application. Create a new Agent and context for each
    run; start/run_sync share the same atomic single-use registration.
    """

    def __init__(
        self, ctx: AgentContext, messages: list[dict], session_id: str = "",
        max_turns: int | None = None, trace_store: TraceSink | None = None, *,
        policy: ExecutionPolicy | None = None,
    ):
        if ctx.llm_gateway is None:
            raise ValueError("AgentContext.llm_gateway is required for Agent")
        if ctx.registry is None:
            raise ValueError("AgentContext.registry is required for Agent")
        self._ctx = ctx
        self._messages = copy.deepcopy(messages)
        self._session_id = session_id
        self._policy = resolve_policy(max_turns, policy)
        self._trace_store = trace_store if trace_store is not None else ctx.trace_store
        self._trace_id = uuid.uuid4().hex
        self._lock = threading.Lock()
        self._state = RunState.CREATED
        self._thread: threading.Thread | None = None
        self._execution_thread_id: int | None = None
        self._done_event = threading.Event()
        self._result: dict | None = None
        self._inject_queue: queue.Queue = queue.Queue()
        self._input_queue: queue.Queue = queue.Queue()

    def _begin(self) -> None:
        with self._lock:
            if self._state is not RunState.CREATED:
                raise RuntimeError("Agent is single-use and has already been started")
            self._state = RunState.RUNNING

    def start(self) -> None:
        self._begin()
        try:
            self._thread = threading.Thread(target=self._execute, daemon=True, name="agent")
            self._thread.start()
        except Exception as exc:
            # A failed thread launch must still publish a terminal result.
            self._execution_thread_id = threading.get_ident()
            self._trace_start()
            self._settle(self._error_result(exc), 0, time.perf_counter())
            raise

    def run_sync(self) -> dict:
        self._begin()
        self._execute()
        return self.result

    def _execute(self) -> None:
        self._execution_thread_id = threading.get_ident()
        t0 = time.perf_counter()
        self._trace_start()
        loop = None
        try:
            loop = AgentLoop(
                self._ctx, self._messages, session_id=self._session_id,
                trace_id=self._trace_id, trace_store=self._trace_store,
                policy=self._policy, injected_queue=self._inject_queue,
            )
            result = loop.run()
        except Exception as exc:
            logger.exception("[Agent] Failed to initialize execution")
            result = self._error_result(exc)
        self._settle(result, loop.turn_count if loop is not None else 0, t0)

    def _error_result(self, exc: Exception) -> dict:
        cancelled = self._ctx.is_cancelled
        return {
            "ok": False, "status": "cancelled" if cancelled else "error",
            "trace_id": self._trace_id, "answer": "",
            "messages": copy.deepcopy(self._messages),
            "error": None if cancelled else str(exc), "trace": [],
        }

    def _settle(self, result: dict, turn_count: int, started_at: float) -> None:
        try:
            with self._lock:
                self._state = RunState.SETTLING
                self._result = copy.deepcopy(result)
            self._trace_finish(result, turn_count, started_at)
            callback = self._ctx.callbacks.on_done
            if callback is not None:
                try:
                    callback(copy.deepcopy(result))
                except Exception:
                    logger.debug("[Agent] on_done callback raised", exc_info=True)
        finally:
            with self._lock:
                self._state = RunState.FINISHED
                self._execution_thread_id = None
                self._done_event.set()

    def cancel(self) -> None:
        self._ctx.cancel()
        self._input_queue.put({})

    def supply_input(self, params: dict) -> None:
        """Compatibility entry point; human-input resume is not implemented."""
        self._input_queue.put(copy.deepcopy(params))

    def inject_message(self, message: dict) -> None:
        self._inject_queue.put(copy.deepcopy(message))

    def wait(self, timeout: float | None = None) -> dict | None:
        with self._lock:
            if self._execution_thread_id == threading.get_ident() and self._state in (
                RunState.RUNNING, RunState.SETTLING,
            ):
                raise RuntimeError("Agent execution cannot wait for itself; read result in on_done")
        if self._done_event.wait(timeout):
            return self.result
        return None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._state in (RunState.RUNNING, RunState.SETTLING)

    @property
    def trace_id(self) -> str:
        return self._trace_id

    @property
    def result(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._result)

    def _trace_start(self) -> None:
        try:
            self._trace_store.start_trace(self._trace_id, self._session_id)
        except Exception:
            logger.debug("[Agent] trace start failed", exc_info=True)

    def _trace_finish(self, result: dict, turn_count: int, started_at: float) -> None:
        try:
            self._trace_store.record_state_trace(self._trace_id, copy.deepcopy(result["trace"]))
            self._trace_store.finish_trace(
                self._trace_id, status=result["status"], turn_count=turn_count,
                duration_ms=(time.perf_counter()-started_at)*1000, error=result["error"],
            )
        except Exception:
            logger.debug("[Agent] trace finish failed", exc_info=True)
