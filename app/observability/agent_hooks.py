"""具体 Agent Hook 实现 —— 安全审计与运行观测。

与 agent_hooks.py 的分工：
    agent_hooks.py 提供机制（AgentHook 基类、裁决类型、组合器）。
    本文件提供策略（挂在扩展点上的两个实际 hook），把数据落到 TraceStore
    的 security_events / iteration_records 表，供运行回放与安全审计。

两个 hook 都 reraise=False —— 审计/观测「坏了也不该拖垮对话」，异常被
CompositeHook 吞掉并 log。安全 hook 默认只审计不拦截（记录所有高风险工具
调用），但保留软拒绝通道：blocked_tools 里的工具会被 reject，复用 AgentLoop
已建好的软拒绝回灌机制。
"""
from __future__ import annotations

import logging

from app.agent.agent_hooks import (
    AfterIterationContext,
    AgentHook,
    BeforeToolsContext,
    ToolDecision,
    reject,
)
from app.tools.registry import HIGH_RISK_TOOLS

logger = logging.getLogger(__name__)

# 裁决标签（落库用），与 ToolDecision.action 区分：这里记录的是审计语义。
_DECISION_ALLOW = "allow"
_DECISION_REJECT = "reject"


class SecurityAuditHook(AgentHook):
    """安全审计 hook —— 在工具执行前审计高风险工具调用。

    默认行为：只审计不拦截，把每次高风险工具调用（exec/run_python/save_file
    等）记入 security_events 表。可选 blocked_tools：命中即软拒绝，把该工具挡
    在执行之前。

    审计失败不应中止对话，故 reraise=False（默认）；落库走 TraceStore 的异常
    安全写入，再加一层 try/except 兜底。
    """

    def __init__(
        self,
        trace_store=None,
        *,
        high_risk: frozenset[str] = HIGH_RISK_TOOLS,
        blocked_tools: frozenset[str] | None = None,
    ):
        self._trace_store = trace_store
        self._high_risk = high_risk
        self._blocked = blocked_tools or frozenset()

    def before_execute_tools(
        self, ctx: BeforeToolsContext
    ) -> list[ToolDecision] | None:
        decisions: list[ToolDecision] = []
        for call in ctx.tool_calls:
            if call.name not in self._high_risk:
                continue
            blocked = call.name in self._blocked
            if blocked:
                msg = f"工具 {call.name} 已被安全策略禁用，本次调用被拒绝。"
                decisions.append(reject(call.id, msg))
            self._audit(
                ctx.trace_id,
                call_id=call.id,
                tool_name=call.name,
                decision=_DECISION_REJECT if blocked else _DECISION_ALLOW,
                reason=msg if blocked else None,
                arguments=call.arguments,
            )
        return decisions or None

    def _audit(
        self,
        trace_id: str,
        *,
        call_id: str,
        tool_name: str,
        decision: str,
        reason: str | None,
        arguments: dict,
    ) -> None:
        if self._trace_store is None:
            return
        try:
            self._trace_store.record_security_event(
                trace_id,
                call_id=call_id,
                tool_name=tool_name,
                risk="high",
                decision=decision,
                reason=reason,
                arguments=arguments,
            )
        except Exception:
            logger.debug("[SecurityAuditHook] record failed", exc_info=True)


class IterationTraceHook(AgentHook):
    """运行观测 hook —— 每轮迭代结束后采集运行记录。

    把这一轮的最终答复文本 + 工具/错误计数落入 iteration_records 表，记录不包含评分。AgentLoop 在纯文本收尾轮、工具轮、错误轮均会触发 after_iteration，
    故最终答复必被采集。
    """

    def __init__(self, trace_store=None):
        self._trace_store = trace_store

    def after_iteration(self, ctx: AfterIterationContext) -> None:
        if self._trace_store is None:
            return
        error_count = sum(
            1 for r in ctx.tool_results
            if isinstance(r, dict) and r.get("status") == "error"
        )
        try:
            self._trace_store.record_iteration(
                ctx.trace_id,
                turn=ctx.turn_count,
                answer=ctx.full_text or None,
                tool_count=len(ctx.tool_calls),
                error_count=error_count,
                had_error=bool(ctx.error),
            )
        except Exception:
            logger.debug("[IterationTraceHook] record failed", exc_info=True)
