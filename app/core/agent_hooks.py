"""Agent 生命周期 Hook —— 把评测、安全审批等横切关注点从状态机核心解耦。

设计动机（对照 nanobot 的 AgentHook，但适配我们的同步 QThread 状态机）：
    AgentLoop 的核心状态机应保持精简稳定。评测埋点、工具执行前安全审批、
    指标上报这类横切逻辑，通过 hook 挂载而不是塞进状态机分支。新增能力 =
    新增一个 AgentHook 实现，零侵入核心路径。

两个关键挂载点：
    before_execute_tools  工具执行前，可读取 tool_calls 并裁决（放行/拒绝）。
                          —— 安全审批的天然挂载点。
    after_iteration       一轮 STREAM→EXECUTE 结束后，可读取工具结果。
                          —— 评测埋点的天然挂载点。

与 nanobot 的差异：
    nanobot 的 before_execute_tools 只能读、不能拦截，要中止只能抛异常（硬失败）。
    这里支持「软拒绝」：返回 ToolDecision(action="reject") 时，该工具不执行，
    转而向 LLM 回灌一条拒绝说明，loop 照常继续——LLM 能看到拒绝并改走别的路。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 裁决动作
ALLOW = "allow"
REJECT = "reject"


@dataclass(frozen=True)
class ToolCallView:
    """传给 hook 的工具调用只读视图（不暴露可变内部结构）。"""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolDecision:
    """hook 对单个工具调用的裁决。

    action=ALLOW   放行（默认，等价于不返回该 call 的裁决）。
    action=REJECT  软拒绝：不执行该工具，向 LLM 回灌 message 作为工具结果。
    """

    call_id: str
    action: str = ALLOW
    message: str = ""

    @property
    def is_reject(self) -> bool:
        return self.action == REJECT


def reject(call_id: str, message: str) -> ToolDecision:
    """构造一个软拒绝裁决的便捷函数。"""
    return ToolDecision(call_id=call_id, action=REJECT, message=message)


@dataclass
class BeforeToolsContext:
    """before_execute_tools 的上下文。"""

    trace_id: str
    session_id: str
    turn_count: int
    tool_calls: list[ToolCallView]


@dataclass
class AfterIterationContext:
    """after_iteration 的上下文：一轮迭代的完整快照。"""

    trace_id: str
    session_id: str
    turn_count: int
    full_text: str = ""
    tool_calls: list[ToolCallView] = field(default_factory=list)
    # 与 tool_calls 对应的执行结果（被拒绝的工具其结果为合成的拒绝说明）。
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class AgentHook:
    """Hook 基类。子类按需覆盖挂载点，未覆盖的默认 no-op。

    reraise=False（默认）：异常被 CompositeHook 吞掉并 log，不影响主流程
        —— 适合 UI 进度、评测埋点这类「坏了也不该拖垮对话」的 hook。
    reraise=True：异常透传 —— 适合安全 hook，「审批逻辑挂了就该中止」。
    """

    reraise: bool = False

    def before_execute_tools(
        self, ctx: BeforeToolsContext
    ) -> list[ToolDecision] | None:
        """工具执行前调用。返回裁决列表（按 call_id），None/空表示全部放行。"""
        return None

    def after_iteration(self, ctx: AfterIterationContext) -> None:
        """一轮 STREAM→EXECUTE 结束后调用。"""
        return None


class CompositeHook(AgentHook):
    """把多个 hook 组合成一个，顺序执行并做异常隔离。

    裁决聚合策略：最严格者胜——任一 hook 拒绝某 call，该 call 即被拒绝
    （安全语义：拒绝优先于放行）。
    """

    def __init__(self, hooks: list[AgentHook]):
        self._hooks = list(hooks)

    def before_execute_tools(
        self, ctx: BeforeToolsContext
    ) -> list[ToolDecision] | None:
        merged: dict[str, ToolDecision] = {}
        for hook in self._hooks:
            try:
                decisions = hook.before_execute_tools(ctx)
            except Exception:
                logger.exception(
                    "[Hook] %s.before_execute_tools failed", type(hook).__name__
                )
                if hook.reraise:
                    raise
                continue
            if not decisions:
                continue
            for decision in decisions:
                # 已被某 hook 拒绝的，不再被放行覆盖（最严格者胜）。
                existing = merged.get(decision.call_id)
                if existing is not None and existing.is_reject:
                    continue
                merged[decision.call_id] = decision
        return list(merged.values()) if merged else None

    def after_iteration(self, ctx: AfterIterationContext) -> None:
        for hook in self._hooks:
            try:
                hook.after_iteration(ctx)
            except Exception:
                logger.exception(
                    "[Hook] %s.after_iteration failed", type(hook).__name__
                )
                if hook.reraise:
                    raise
