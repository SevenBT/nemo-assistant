"""Public lifecycle, synchronous loop and request-boundary contracts."""
import copy
import json
import threading

import pytest

from app.agent.agent import Agent
from app.agent.agent_context import AgentContext
from app.agent.agent_hooks import AgentHook
from app.agent.agent_interface import AgentCallbacks
from app.agent.agent_loop import AgentLoop
from app.agent.contracts import ToolDescriptor
from app.agent.execution_policy import ExecutionPolicy
from app.agent.request_context import PreparedRequest, validate_messages


USER = [{"role": "user", "content": "run"}]
TEXT = [{"type": "text", "delta": "answer"}, {"type": "done"}]


def call(index="1", name="read"):
    return {"type": "tool_call", "id": index, "name": name, "arguments": {"value": [1]}}


class Model:
    def __init__(self, *responses):
        self.responses = list(responses or [TEXT])
        self.requests = []

    def chat_stream(self, messages, tools, **kwargs):
        self.requests.append(copy.deepcopy((messages, tools)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        yield from response


class Tools:
    def __init__(self):
        self.calls = []

    def definitions(self):
        return [{"type": "function", "function": {"name": "read"}}]

    def describe(self, name):
        return ToolDescriptor(name, read_only=name == "read")

    def execute(self, name, arguments, context):
        self.calls.append(context.call_id)
        return {"status": "success", "data": "ok"}

    def format_result(self, result):
        return json.dumps(result)


class Observer(AgentHook):
    def __init__(self):
        self.iterations = []

    def after_iteration(self, ctx):
        self.iterations.append(ctx)


@pytest.mark.parametrize("scenario", ["success", "error", "empty", "cancel", "definitions", "loop_init", "thread_start"])
def test_terminal_snapshot_exactly_once_even_when_setup_fails(monkeypatch, scenario):
    done = []
    model, tools = Model(), Tools()
    ctx = AgentContext(llm_gateway=model, registry=tools, callbacks=AgentCallbacks(on_done=done.append))
    agent = Agent(ctx, [] if scenario == "empty" else USER)
    if scenario == "error":
        model.responses = [RuntimeError("model failed")]
    if scenario == "cancel":
        agent.cancel()
    if scenario == "definitions":
        monkeypatch.setattr(tools, "definitions", lambda: (_ for _ in ()).throw(RuntimeError("definitions failed")))
    if scenario == "loop_init":
        monkeypatch.setattr("app.agent.agent.AgentLoop", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("init failed")))
    if scenario == "thread_start":
        monkeypatch.setattr(threading.Thread, "start", lambda self: (_ for _ in ()).throw(RuntimeError("launch failed")))
        with pytest.raises(RuntimeError, match="launch failed"):
            agent.start()
        result = agent.wait(0)
    else:
        result = agent.run_sync()
    assert done == [result] == [agent.result]
    assert set(result) == {"ok", "status", "trace_id", "answer", "messages", "error", "trace"}
    assert agent.wait(0) == result
    assert not agent.is_running
    assert result["status"] == ("ok" if scenario in ("success", "empty") else "cancelled" if scenario == "cancel" else "error")
    with pytest.raises(RuntimeError, match="single-use"):
        agent.run_sync()
    with pytest.raises(RuntimeError, match="single-use"):
        agent.start()


def test_callback_sees_result_cannot_mutate_it_or_wait_for_itself():
    seen = []

    def done(result):
        assert agent.is_running
        assert agent.result == result
        with pytest.raises(RuntimeError, match="itself"):
            agent.wait(0)
        with pytest.raises(RuntimeError, match="single-use"):
            agent.start()
        seen.append(copy.deepcopy(result))
        result["messages"].clear()
        raise RuntimeError("observer failure")

    agent = Agent(AgentContext(llm_gateway=Model(), registry=Tools(), callbacks=AgentCallbacks(on_done=done)), USER)
    result = agent.run_sync()
    assert seen == [result]
    result["messages"].clear()
    assert agent.result["messages"][-1]["content"] == "answer"


def test_start_competes_with_synchronous_run_and_waits_through_settlement():
    barrier, started, release, in_done, finish_done = threading.Barrier(3), threading.Event(), threading.Event(), threading.Event(), threading.Event()
    wins, errors = [], []

    class BlockingModel(Model):
        def chat_stream(self, *args, **kwargs):
            started.set()
            assert release.wait(3)
            yield from TEXT

    def done(result):
        in_done.set()
        assert finish_done.wait(3)

    agent = Agent(AgentContext(llm_gateway=BlockingModel(), registry=Tools(), callbacks=AgentCallbacks(on_done=done)), USER)

    def enter(method):
        barrier.wait()
        try:
            method()
            wins.append(True)
        except RuntimeError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=enter, args=(method,)) for method in (agent.start, agent.run_sync)]
    for thread in threads:
        thread.start()
    try:
        barrier.wait()
        assert started.wait(3) and agent.is_running
        assert agent.wait(.01) is None
        release.set()
        assert in_done.wait(3)
        assert agent.is_running and agent.result["ok"]
        assert agent.wait(.01) is None
    finally:
        release.set()
        finish_done.set()
        for thread in threads:
            thread.join(3)
    assert agent.wait(3)["ok"]
    assert wins == [True] and len(errors) == 1 and "single-use" in errors[0]


def test_loop_and_facade_use_identical_state_machine_and_history():
    done = []
    def context():
        return AgentContext(llm_gateway=Model([call(), {"type": "done"}], TEXT), registry=Tools(), callbacks=AgentCallbacks(on_done=done.append))
    loop = AgentLoop(context(), USER)
    direct = loop.run()
    assert done == []
    public = Agent(context(), USER).run_sync()
    for result in (direct, public):
        result.pop("trace_id")
        for state in result["trace"]:
            state.pop("duration_ms")
    assert public == direct and len(done) == 1
    assert direct["messages"][:len(USER)] == USER
    assert direct["messages"][-1] == {"role": "assistant", "content": "answer"}
    with pytest.raises(RuntimeError, match="single-use"):
        loop.run()


def test_prepare_every_request_including_wrap_up_without_reenabling_tools():
    observer = Observer()
    requests = []

    class Preparer:
        def prepare(self, request):
            requests.append(request)
            request.messages[0]["content"] = "request only"
            return PreparedRequest(request.messages, [{"reenabled": True}])

    model = Model([call(), {"type": "done"}], [call("2"), {"type": "done"}], TEXT)
    result = Agent(AgentContext(llm_gateway=model, registry=Tools(), request_preparer=Preparer(), hooks=[observer]),
                   USER, policy=ExecutionPolicy(max_turns=2)).run_sync()
    assert result["ok"]
    assert [(r.seq, r.mode) for r in requests] == [(0, "normal"), (1, "normal"), (2, "wrap_up")]
    assert requests[-1].tools is None and model.requests[-1][1] is None
    assert len(observer.iterations) == 3
    assert result["messages"][0] == USER[0]


@pytest.mark.parametrize("cancel", [False, True])
def test_preparation_failure_notifies_iteration_and_terminal_once(cancel):
    done, observer, model = [], Observer(), Model()

    class Preparer:
        def prepare(self, request):
            if cancel:
                request.cancel_token.cancel()
                return PreparedRequest(request.messages, None)
            raise ValueError("preparation failed")

    result = Agent(AgentContext(llm_gateway=model, registry=Tools(), request_preparer=Preparer(), hooks=[observer],
                               callbacks=AgentCallbacks(on_done=done.append)), USER).run_sync()
    assert done == [result] and len(observer.iterations) == 1 and model.requests == []
    assert result["status"] == ("cancelled" if cancel else "error")
    assert observer.iterations[0].error == (None if cancel else "preparation failed")


def test_legacy_hook_is_once_and_changes_only_initial_request_view():
    class Legacy(AgentHook):
        calls = 0
        def before_turn(self, ctx):
            self.calls += 1
            return [{"role": "user", "content": "view"}]
    hook = Legacy()
    model = Model([call(), {"type": "done"}], [{"type": "text", "delta": "final"},
                  {"type": "done", "reasoning_content": "reason", "provider_state": {"opaque": [1]}}])
    result = Agent(AgentContext(llm_gateway=model, registry=Tools(), hooks=[hook]), USER).run_sync()
    assert result["ok"] and hook.calls == 1
    assert all(request[0][0]["content"] == "view" for request in model.requests)
    assert result["messages"][0] == USER[0]
    assert result["messages"][-1]["provider_state"] == {"opaque": [1]}
    assert result["messages"][-1]["reasoning_content"] == "reason"


@pytest.mark.parametrize("workers", [1, 2])
def test_worker_limit_and_batch_order_are_policy_controlled(workers):
    ready, release, lock = threading.Event(), threading.Event(), threading.Lock()
    class BlockingTools(Tools):
        active = maximum = 0
        def execute(self, name, arguments, context):
            with lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                if self.active == workers:
                    ready.set()
            assert release.wait(3)
            with lock:
                self.active -= 1
            return super().execute(name, arguments, context)
    tools = BlockingTools()
    model = Model([call(str(i)) for i in range(3)] + [{"type": "done"}], TEXT)
    agent = Agent(AgentContext(llm_gateway=model, registry=tools), USER, policy=ExecutionPolicy(max_workers=workers))
    agent.start()
    try:
        assert ready.wait(3)
    finally:
        release.set()
    result = agent.wait(3)
    assert result["ok"] and tools.maximum == workers
    assert [m["tool_call_id"] for m in result["messages"] if m["role"] == "tool"] == ["0", "1", "2"]


def test_fatal_concurrent_result_retains_all_completed_evidence():
    class FatalTools(Tools):
        def execute(self, name, arguments, context):
            return {"status": "error", "data": {"error_type": "permission"}} if context.call_id == "1" else super().execute(name, arguments, context)
    result = Agent(AgentContext(llm_gateway=Model([call("1"), call("2"), {"type": "done"}]), registry=FatalTools()), USER).run_sync()
    assert result["status"] == "error"
    assert [m["tool_call_id"] for m in result["messages"] if m["role"] == "tool"] == ["1", "2"]
    validate_messages(result["messages"])


def test_failure_threshold_configurable_and_conflicting_turn_limit_rejected():
    class FailingTools(Tools):
        def execute(self, *args):
            return {"status": "error", "data": {"error_type": "runtime"}}
    model = Model([call("1"), {"type": "done"}], [call("2"), {"type": "done"}])
    ctx = AgentContext(llm_gateway=model, registry=FailingTools())
    policy = ExecutionPolicy(max_tool_failures=2)
    with pytest.raises(ValueError, match="conflicts"):
        Agent(ctx, USER, max_turns=3, policy=policy)
    result = Agent(ctx, USER, policy=policy).run_sync()
    assert result["status"] == "error" and "2" in result["error"]


def test_cancel_skips_queued_read_tasks_and_retains_completed_results():
    class CancellingTools(Tools):
        def execute(self, name, arguments, context):
            result = super().execute(name, arguments, context)
            context.cancel_token.cancel()
            return result
    tools, observer = CancellingTools(), Observer()
    model = Model([call(str(i)) for i in range(3)] + [{"type": "done"}])
    result = Agent(AgentContext(llm_gateway=model, registry=tools, hooks=[observer]),
                   USER, policy=ExecutionPolicy(max_workers=1)).run_sync()
    assert result["status"] == "cancelled" and tools.calls == ["0"]
    assert [m["tool_call_id"] for m in result["messages"] if m["role"] == "tool"] == ["0"]
    assert len(observer.iterations) == 1 and len(observer.iterations[0].tool_results) == 1


def test_policy_keeps_real_registry_disabled_gate():
    from app.adapters.agent.tools import RegistryToolRuntime
    from app.tools.registry import ToolRegistry
    from test_agent_adapters import RecordingTool
    registry, tool = ToolRegistry(), RecordingTool(read_only=True)
    tool.enabled = False
    registry.register(tool)
    result = Agent(AgentContext(llm_gateway=Model([call(name="record"), {"type": "done"}]),
                               registry=RegistryToolRuntime(registry)), USER,
                   policy=ExecutionPolicy(max_workers=1, max_tool_failures=100)).run_sync()
    assert result["status"] == "error" and "permission" in result["error"] and tool.calls == []


@pytest.mark.parametrize("limits", [{"max_workers": 0}, {"max_turns": -1}, {"max_tool_failures": 0}, {"max_workers": 1.5}, {"max_turns": True}])
def test_invalid_policy_limits_fail_at_construction(limits):
    with pytest.raises(ValueError, match="limits"):
        ExecutionPolicy(**limits)


def test_qt_cancellation_before_run_uses_context_without_starting_nested_agent(qapp, monkeypatch):
    from app.desktop.agent_thread import AgentThread
    monkeypatch.setattr(Agent, "start", lambda self: pytest.fail("nested top-level thread"))
    model = Model()
    worker = AgentThread(AgentContext(llm_gateway=model, registry=Tools()), USER)
    done = []
    worker.done.connect(done.append)
    worker.cancel()
    worker.start()
    assert worker.wait(3000)
    qapp.processEvents()
    assert len(done) == 1 and done[0]["status"] == "cancelled" and model.requests == []
