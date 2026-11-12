"""Execute the production Agent with explicitly isolated dependencies."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

from nemo_eval.contracts import safe_path
from nemo_eval.budget import Budget, cost_summary, validate_config


class ScriptedGateway:
    def __init__(self, script):
        self.script = copy.deepcopy(script)
        self.requests = []

    def chat_stream(self, messages, tools=None, **kwargs):
        self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
        if not self.script:
            raise ValueError("Model script exhausted")
        call = self.script.pop(0)
        if isinstance(call, list):
            call = {"events": call}
        serialized = json.dumps(messages, ensure_ascii=False)
        for required in call.get("request_contains", []):
            if required not in serialized:
                raise ValueError(f"Model request missing expected context: {required}")
        for event in call["events"]:
            yield event


class IsolatedCheckpoints:
    def __init__(self, directory):
        self.directory = directory

    def save(self, session_id, *args):
        from nemo_eval.artifacts import write_json
        write_json(self.directory / "checkpoint.json", {"session_id": session_id, "state": args})

    def clear(self, session_id):
        (self.directory / "checkpoint.json").unlink(missing_ok=True)


class PromptConfig:
    systemPrompt = "system_prompt"
    def __init__(self, prompt):
        self.prompt = prompt
    def get(self, key):
        return self.prompt


def make_live_gateway(profile, logger):
    from app.core.llm_gateway import LLMGateway, RetryPolicy
    from app.core.runtime_config import GatewayConfig
    key_name = profile.get("api_key_env")
    if not profile.get("model") or not key_name or not os.environ.get(key_name):
        raise ValueError("Live model requires model and a populated api_key_env")
    return LLMGateway(config=GatewayConfig(
        model=profile["model"], provider=profile.get("provider", ""),
        base_url=profile.get("base_url", ""), api_key=os.environ[key_name],
        max_tokens=profile.get("max_tokens", 1024), temperature=profile.get("temperature", 0),
        top_p=profile.get("top_p", 1),
    ), logger=logger, retry_policy=RetryPolicy(max_attempts=profile.get("max_attempts", 1)))


def execute(case, workdir: Path, mode="offline", config=None):
    from app.core.agent import Agent
    from app.core.agent_context import AgentContext
    from app.core.agent_interface import AgentCallbacks
    from app.core.agent_hooks import AgentHook, reject
    from app.core.conversation_prompt_builder import ConversationPromptBuilder
    from app.i18n import init_language
    from app.models.message import Message, ToolCall
    from app.tools.registry import ToolRegistry

    config = validate_config(config or {})
    budget = Budget(config)
    fixture = case["fixtures"]
    init_language(config.get("language", "zh"))
    calls, events, requests, llm_calls = [], [], [], []
    workspace = workdir / "workspace"
    workspace.mkdir()
    for name, text in fixture.get("workspace_files", {}).items():
        path = safe_path(workspace, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    registry = ToolRegistry()
    if fixture.get("tool_profile") == "workspace-files":
        from app.tools.read_file import ReadFileTool
        from app.tools.save_file import SaveFileTool
        registry.register(ReadFileTool(workspace))
        registry.register(SaveFileTool(str(workspace), open_folder=False))

    class Logger:
        def write(self, record):
            llm_calls.append(copy.deepcopy(record))

    if mode == "offline":
        gateway = ScriptedGateway(fixture["model_script"])
    else:
        live_gateway = make_live_gateway(config["target"], Logger())
        class BudgetedGateway:
            def __init__(self):
                self.requests = []
            def chat_stream(self, messages, tools=None, **kwargs):
                budget.reserve(config["target"])
                self.requests.append({"messages": copy.deepcopy(messages), "tools": copy.deepcopy(tools)})
                yield from live_gateway.chat_stream(messages, tools=tools, **kwargs, stream_timeout=config["target"].get("timeout_seconds", 60))
        gateway = BudgetedGateway()

    sessions = SimpleNamespace(get=lambda _: SimpleNamespace(system_prompt=fixture.get("system_prompt", "")))
    memory = SimpleNamespace(build_memory_context=lambda _: "\n".join(fixture.get("memory", [])))
    builder = ConversationPromptBuilder(
        sessions, memory, config=PromptConfig(fixture.get("system_prompt", "")),
        datetime_info_provider=lambda: fixture.get("clock", "2026-11-09T09:00:00+08:00"),
        time_hint_provider=lambda: "", enabled_tools_provider=lambda: registry.tool_names,
        vision_enabled_provider=lambda: False,
    )
    history, step_results = [], []
    steps = case["input"].get("steps", [{"id": "snapshot"}])
    status, answer, error = "completed", "", None
    evidence_complete = True
    for step in steps:
        step_id = step["id"]
        if case["input"]["mode"] == "snapshot":
            messages = copy.deepcopy(case["input"]["messages"])
        else:
            history.append(Message(role="user", content=step["user"]))
            messages = builder.build(history, "eval-session")
        requests.append({"step": step_id, "messages": copy.deepcopy(messages), "tools": registry.get_openai_functions()})
        class EvidenceHook(AgentHook):
            reraise = True
            def before_execute_tools(self, ctx):
                rejected = []
                for call in ctx.tool_calls:
                    blocked = call.name in fixture.get("blocked_tools", [])
                    event = {"evidence_id": f"tool:{step_id}:{ctx.turn_count}:{call.id}", "call_id": call.id,
                             "step": step_id, "name": call.name, "arguments": copy.deepcopy(call.arguments),
                             "started_order": len(events) * 2, "iteration": ctx.turn_count, "rejected": blocked, "result": None}
                    calls.append(event)
                    if blocked:
                        rejected.append(reject(call.id, "Rejected by explicit evaluation policy"))
                return rejected
            def after_iteration(self, ctx):
                for call, result in zip(ctx.tool_calls, ctx.tool_results):
                    for saved in reversed(calls):
                        if saved["call_id"] == call.id and saved["step"] == step_id and saved["iteration"] == ctx.turn_count:
                            saved["result"] = copy.deepcopy(result)
                            saved["finished_order"] = len(events) * 2 + 1
                            break
                events.append({"step": step_id, "iteration": ctx.turn_count, "answer": ctx.full_text, "error": ctx.error})
        agent = Agent(AgentContext(
            llm_gateway=gateway, registry=registry, callbacks=AgentCallbacks.silent(),
            hooks=[EvidenceHook()], checkpoint_store=IsolatedCheckpoints(workdir),
        ), messages, session_id="", max_turns=case.get("limits", {}).get("max_iterations_per_step", 6))
        result = agent.run_sync()
        answer = result.get("answer", "")
        step_results.append({"step": step_id, "trace_id": agent.trace_id, "status": result["status"], "answer": answer, "error": result["error"]})
        if not result["ok"]:
            status, error = "error", result["error"]
            break
        if case["input"]["mode"] == "scenario":
            # Persist only this step's generated messages, not the rebuilt system
            # prompt or earlier history. Tool associations survive the next build.
            generated = result["messages"][len(messages):]
            tool_results = {m["tool_call_id"]: m["content"] for m in generated if m["role"] == "tool"}
            for message in generated:
                if message["role"] == "assistant":
                    tool_calls = []
                    for call in message.get("tool_calls", []):
                        raw = tool_results.get(call["id"])
                        try:
                            payload = json.loads(raw) if raw else None
                        except ValueError:
                            # Production format may append a localized error hint.
                            payload = next((c["result"] for c in calls if c["call_id"] == call["id"] and c["step"] == step_id), None)
                        tool_calls.append(ToolCall(id=call["id"], name=call["function"]["name"], arguments=json.loads(call["function"]["arguments"]), result=payload))
                    history.append(Message(role="assistant", content=message.get("content") or "", tool_calls=tool_calls))
            history.append(Message(role="assistant", content=answer))
    if mode == "offline" and gateway.script:
        status, error = "error", "Model script contains unused calls"
    artifacts = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file():
            if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
                raise ValueError("Artifact escaped workspace")
            if path.stat().st_size > 2_000_000:
                raise ValueError("Artifact exceeds 2 MB evidence limit")
            data = path.read_bytes()
            artifacts[path.relative_to(workspace).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "text": path.read_text(encoding="utf-8", errors="replace")}
    for call in calls:
        if call["result"] is None:
            call["result"] = {"status": "error", "data": {"message": "Missing tool completion evidence"}}
            status, error = "error", "Incomplete tool evidence"
            evidence_complete = False
    return {"execution_status": status, "error": error, "answer": answer, "tool_calls": calls,
            "events": events, "steps": step_results, "requests": requests, "model_requests": gateway.requests, "artifacts": artifacts,
            "llm_calls": llm_calls, "cost": cost_summary(llm_calls, config.get("target", {})), "model_calls": budget.calls, "output_reserved": budget.output_reserved, "evidence_complete": evidence_complete,
            "expected_statuses": case["expectations"].get("execution_statuses", ["completed"])}
