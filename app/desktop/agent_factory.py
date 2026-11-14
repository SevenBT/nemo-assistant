"""Explicit desktop Agent composition; importing the core never calls this."""
from __future__ import annotations

from app.adapters.agent.checkpoint import FileCheckpointStore
from app.adapters.agent.tools import RegistryToolRuntime
from app.agent.agent_context import AgentContext
from app.agent.contracts import ModelStream, NullTraceSink, TraceSink
from app.config.runtime_paths import SESSIONS_DIR
from app.conversation.agent_hooks import ConsolidatorHook
from app.desktop.agent_thread import AgentThread
from app.observability.agent_hooks import IterationTraceHook, SecurityAuditHook
from app.tools.registry import ToolRegistry


def create_agent_worker(
    *, llm_gateway: ModelStream, registry: ToolRegistry, api_messages: list[dict],
    session_id: str, trace_store: TraceSink | None = None,
    consolidator=None, max_turns: int = 10,
) -> AgentThread:
    hooks = []
    if trace_store is not None:
        # Audit is observational by default; execution gates live in the registry.
        hooks.extend([SecurityAuditHook(trace_store), IterationTraceHook(trace_store)])
    if consolidator is not None:
        hooks.append(ConsolidatorHook(consolidator))
    context = AgentContext(
        llm_gateway=llm_gateway, registry=RegistryToolRuntime(registry), hooks=hooks,
        checkpoint_store=FileCheckpointStore(SESSIONS_DIR),
        trace_store=trace_store if trace_store is not None else NullTraceSink(),
    )
    return AgentThread(
        context=context, api_messages=api_messages,
        session_id=session_id, max_turns=max_turns,
    )
