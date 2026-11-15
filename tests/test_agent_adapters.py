"""Behavioral compatibility of explicit tool, checkpoint and desktop adapters."""
import copy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from app.adapters.agent.checkpoint import FileCheckpointStore
from app.adapters.agent.tools import RegistryToolRuntime
from app.agent.agent import Agent
from app.agent.agent_context import AgentContext
from app.agent.agent_hooks import AgentHook
from app.agent.contracts import CheckpointSnapshot, ToolExecutionContext
from app.runtime.cancellation import CancellationToken
from app.tools.base import BuiltinTool
from app.tools.registry import ToolRegistry


class RecordingTool(BuiltinTool):
    name = "record"
    description = "Record an integer"
    parameters = {
        "type": "object", "required": ["count"],
        "properties": {"count": {"type": "integer"}},
    }

    def __init__(self, *, read_only=False, fail=False):
        self._read_only = read_only
        self.fail = fail
        self.calls = []

    @property
    def read_only(self):
        return self._read_only

    def execute(self, params):
        self.calls.append(copy.deepcopy(params))
        if self.fail:
            raise ConnectionError("offline test error")
        if "nested" in params:
            params["nested"]["items"].append("mutated")
        return {"status": "success", "data": params["count"]}


@pytest.mark.parametrize("scenario", ["cast", "invalid", "disabled", "retry_safe", "unsafe", "missing"])
def test_tool_adapter_preserves_registry_gates_validation_and_retry(monkeypatch, scenario):
    monkeypatch.setattr("app.tools.registry.time.sleep", lambda _: None)
    args = {} if scenario == "invalid" else {"count": "3"}
    outputs, counts = [], []
    for adapted in (False, True):
        registry = ToolRegistry()
        tool = RecordingTool(read_only=scenario == "retry_safe", fail=scenario in ("retry_safe", "unsafe"))
        tool.enabled = scenario != "disabled"
        registry.register(tool)
        name = "missing" if scenario == "missing" else tool.name
        if adapted:
            runtime = RegistryToolRuntime(registry)
            result = runtime.execute(name, args, ToolExecutionContext("", "trace", "call", CancellationToken()))
            formatted = runtime.format_result(result)
        else:
            result = registry.execute(name, args)
            formatted = registry.format_result(result)
        outputs.append((result, formatted))
        counts.append(len(tool.calls))
    assert outputs[0] == outputs[1]
    assert counts[0] == counts[1] == {
        "cast": 1, "invalid": 0, "disabled": 0, "retry_safe": 2, "unsafe": 1, "missing": 0,
    }[scenario]


@pytest.mark.parametrize("concurrent", [False, True])
def test_execution_context_and_hook_mutation_do_not_change_model_arguments(concurrent):
    registry = ToolRegistry()
    tool = RecordingTool(read_only=concurrent)
    registry.register(tool)
    original = {"count": 3, "nested": {"items": ["original"]}}
    observed = []

    class MutatingObserver(AgentHook):
        def before_execute_tools(self, ctx):
            ctx.tool_calls[0].arguments["nested"]["items"].append("hook mutation")

    class PolicyObserver(AgentHook):
        def before_execute_tools(self, ctx):
            observed.append(copy.deepcopy(ctx.tool_calls[0].arguments))

    class Model:
        calls = 0

        def chat_stream(self, messages, tools, **kwargs):
            self.calls += 1
            if self.calls == 1:
                for index in range(2):
                    yield {"type": "tool_call", "id": str(index), "name": "record", "arguments": original}
            else:
                yield {"type": "text", "delta": "done"}
            yield {"type": "done"}

    result = Agent(AgentContext(
        llm_gateway=Model(), registry=RegistryToolRuntime(registry),
        hooks=[MutatingObserver(), PolicyObserver()],
    ), [{"role": "user", "content": "run"}], session_id="session").run_sync()
    assert result["ok"]
    assert original == {"count": 3, "nested": {"items": ["original"]}}
    assert observed == [original]
    assert len(tool.calls) == 2
    assert all(params["_session_id"] == "session" for params in tool.calls)
    assert all(params["nested"] == original["nested"] for params in tool.calls)
    assistant = next(m for m in result["messages"] if m["role"] == "assistant")
    assert all(json.loads(call["function"]["arguments"]) == original for call in assistant["tool_calls"])


def snapshot():
    return CheckpointSnapshot(
        messages=[{"role": "user", "content": "original"}],
        assistant_msg={"role": "assistant", "content": None},
        completed_results=[], pending_tool_calls=[{"id": "pending", "name": "record"}],
    )


def test_checkpoint_writes_compatible_format_and_restores_old_files(tmp_path):
    store = FileCheckpointStore(tmp_path)
    state = snapshot()
    store.save("new", state)
    assert json.loads((tmp_path / "new.checkpoint.json").read_text(encoding="utf-8")) == asdict(state)
    # An existing-format file, independent of the new writer.
    old = {
        "messages": [], "assistant_msg": {}, "completed_results": [],
        "pending_tool_calls": [{"id": "legacy-call", "name": "save_file"}],
    }
    (tmp_path / "old.checkpoint.json").write_text(json.dumps(old), encoding="utf-8")
    restored = store.restore("old")
    assert {key: restored[key] for key in old} == old
    assert restored["error_results"][0]["tool_call_id"] == "legacy-call"
    assert not store.has_checkpoint("old")
    assert store.has_checkpoint("new")


def test_checkpoint_write_failure_keeps_previous_file_and_removes_temp(monkeypatch, tmp_path):
    store = FileCheckpointStore(tmp_path)
    store.save("session", snapshot())
    path = tmp_path / "session.checkpoint.json"
    original = path.read_bytes()

    def fail(*args):
        raise OSError("test replacement failure")

    monkeypatch.setattr("app.adapters.agent.checkpoint.os.replace", fail)
    with pytest.raises(OSError, match="test replacement failure"):
        store.save("session", snapshot())
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_checkpoint_failure_is_fatal_while_trace_failure_is_isolated():
    class BrokenCheckpoints:
        def save(self, session_id, state):
            raise OSError("checkpoint failure")

        def clear(self, session_id):
            pass

    class BrokenTrace:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise OSError("trace failure")
            return fail

    class Model:
        calls = 0

        def chat_stream(self, messages, tools, **kwargs):
            self.calls += 1
            if self.calls == 1:
                for index in range(2):
                    yield {"type": "tool_call", "id": str(index), "name": "record", "arguments": {"count": 1}}
            else:
                yield {"type": "text", "delta": "ok"}
            yield {"type": "done"}

    registry = ToolRegistry()
    tool = RecordingTool()
    registry.register(tool)
    context = AgentContext(llm_gateway=Model(), registry=RegistryToolRuntime(registry), trace_store=BrokenTrace())
    assert Agent(context, [{"role": "user"}], session_id="session").run_sync()["ok"]
    tool.calls.clear()
    context = AgentContext(
        llm_gateway=Model(), registry=RegistryToolRuntime(registry),
        checkpoint_store=BrokenCheckpoints(), trace_store=BrokenTrace(),
    )
    result = Agent(context, [{"role": "user"}], session_id="session").run_sync()
    assert not result["ok"] and result["error"] == "checkpoint failure"
    assert len(tool.calls) == 1


def test_desktop_composes_independent_contexts_with_explicit_storage(monkeypatch, tmp_path):
    from app.desktop import agent_factory
    from app.llm.cancellation import CancellationToken as LegacyToken

    assert LegacyToken is CancellationToken
    monkeypatch.setattr(agent_factory, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(agent_factory, "AgentThread", lambda **kwargs: SimpleNamespace(**kwargs))
    registry = ToolRegistry()
    registry.register(RecordingTool())
    args = dict(llm_gateway=object(), registry=registry, api_messages=[], session_id="test")
    first = agent_factory.create_agent_worker(**args)
    second = agent_factory.create_agent_worker(**args)
    assert first.context.cancel_token is not second.context.cancel_token
    assert first.context.hooks is not second.context.hooks
    assert isinstance(first.context.checkpoint_store, FileCheckpointStore)
    assert first.context.checkpoint_store.directory == tmp_path
    assert first.context.registry.definitions() == registry.get_openai_functions()
    assert list(tmp_path.iterdir()) == []  # composition itself never writes


def test_disabled_tool_remains_blocked_without_observability(monkeypatch, tmp_path):
    from app.desktop import agent_factory

    monkeypatch.setattr(agent_factory, "SESSIONS_DIR", tmp_path)
    monkeypatch.setattr(agent_factory, "AgentThread", lambda **kwargs: SimpleNamespace(**kwargs))
    registry = ToolRegistry()
    tool = RecordingTool()
    tool.enabled = False
    registry.register(tool)
    worker = agent_factory.create_agent_worker(
        llm_gateway=object(), registry=registry, api_messages=[], session_id="test",
    )
    assert worker.context.hooks == []
    result = worker.context.registry.execute(
        "record", {"count": 1}, ToolExecutionContext("test", "trace", "call", worker.context.cancel_token),
    )
    assert result["data"]["error_type"] == "permission"
    assert tool.calls == []


def test_qt_worker_bridges_events_and_saves_checkpoint_between_batches(monkeypatch, tmp_path, qapp):
    from app.desktop import agent_factory

    monkeypatch.setattr(agent_factory, "SESSIONS_DIR", tmp_path)
    path = tmp_path / "session.checkpoint.json"

    class InspectingTool(RecordingTool):
        def execute(self, params):
            if self.calls:
                saved = json.loads(path.read_text(encoding="utf-8"))
                assert saved["completed_results"][0]["tool_call_id"] == "0"
                assert saved["pending_tool_calls"] == [{"id": "1", "name": "record"}]
            return super().execute(params)

    class Model:
        calls = 0

        def chat_stream(self, messages, tools, **kwargs):
            self.calls += 1
            if self.calls == 1:
                for index in range(2):
                    yield {"type": "tool_call", "id": str(index), "name": "record", "arguments": {"count": 1}}
            else:
                yield {"type": "text", "delta": "complete"}
            yield {"type": "done"}

    registry = ToolRegistry()
    tool = InspectingTool()
    registry.register(tool)
    worker = agent_factory.create_agent_worker(
        llm_gateway=Model(), registry=registry,
        api_messages=[{"role": "user", "content": "run"}], session_id="session",
    )
    chunks, results, events = [], [], []
    worker.text_chunk.connect(chunks.append)
    worker.done.connect(results.append)
    worker.tool_event.connect(lambda *event: events.append(event))
    worker.start()
    assert worker.wait(5000)
    qapp.processEvents()
    assert chunks == ["complete"]
    assert results[-1]["ok"], results[-1]
    assert worker._trace_id == results[-1]["trace_id"]
    assert len(tool.calls) == 2
    assert [event[0] for event in events if event[1] == "done"] == ["0", "1"]
    assert not path.exists()
