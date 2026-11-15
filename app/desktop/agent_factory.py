"""Explicit desktop Agent composition; importing the core never calls this."""
from __future__ import annotations

from app.adapters.agent.checkpoint import FileCheckpointStore
from app.adapters.agent.tools import RegistryToolRuntime
from app.agent.agent_context import AgentContext
from app.agent.contracts import ModelStream, NullTraceSink, TraceSink
from app.config.runtime_paths import SESSIONS_DIR
from app.agent.request_context import IdentityRequestPreparer
from app.agent.execution_policy import ExecutionPolicy, resolve_policy
from app.conversation.request_preparer import ConsolidatingRequestPreparer
from app.desktop.agent_thread import AgentThread
from app.observability.agent_hooks import IterationTraceHook, SecurityAuditHook
from app.tools.registry import ToolRegistry


def create_agent_worker(
    *, llm_gateway: ModelStream, registry: ToolRegistry, api_messages: list[dict],
    session_id: str, trace_store: TraceSink | None = None,
    consolidator=None, max_turns: int | None = None, policy: ExecutionPolicy | None = None,
) -> AgentThread:
    hooks = []
    if trace_store is not None:
        # Audit is observational by default; execution gates live in the registry.
        hooks.extend([SecurityAuditHook(trace_store), IterationTraceHook(trace_store)])
    context = AgentContext(
        llm_gateway=llm_gateway, registry=RegistryToolRuntime(registry), hooks=hooks,
        checkpoint_store=FileCheckpointStore(SESSIONS_DIR),
        trace_store=trace_store if trace_store is not None else NullTraceSink(),
        request_preparer=(ConsolidatingRequestPreparer(consolidator)
                          if consolidator is not None else IdentityRequestPreparer()),
    )
    return AgentThread(
        context=context, api_messages=api_messages,
        session_id=session_id, policy=resolve_policy(max_turns, policy),
    )
