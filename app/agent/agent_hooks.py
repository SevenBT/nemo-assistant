"""Agent 生命周期 Hook —— 把评测、安全审批等横切关注点从状态机核心解耦。

设计动机（对照 nanobot 的 AgentHook，但适配我们的同步 QThread 状态机）：
    Agent 的核心状态机应保持精简稳定。评测埋点、工具执行前安全审批、
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

三个关键挂载点：
    before_turn           每轮对话开始前，可读取/修改消息列表。
                          —— 对话压缩（consolidation）的天然挂载点。
    before_execute_tools  工具执行前，可读取 tool_calls 并裁决（放行/拒绝）。
                          —— 安全审批的天然挂载点。
    after_iteration       一轮 STREAM→EXECUTE 结束后，可读取工具结果。
                          —— 评测埋点的天然挂载点。
"""
from __future__ import annotations

import json as _json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.message import Message

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


@dataclass
class BeforeTurnContext:
    """before_turn 的上下文：每轮对话开始前的快照。

    hook 可返回新的消息列表来替换 ctx.messages（例如压缩后的消息）。
    返回 None 表示不修改。
    """

    trace_id: str
    session_id: str
    turn_count: int
    messages: list[dict[str, Any]]


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

    def before_turn(self, ctx: BeforeTurnContext) -> list[dict[str, Any]] | None:
        """每轮对话开始前调用。返回新的消息列表以替换，None 表示不修改。"""
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

    def before_turn(self, ctx: BeforeTurnContext) -> list[dict[str, Any]] | None:
        """顺序执行各 hook 的 before_turn，将前一个 hook 修改后的消息传给下一个。"""
        messages = ctx.messages
        changed = False
        for hook in self._hooks:
            try:
                result = hook.before_turn(
                    BeforeTurnContext(
                        trace_id=ctx.trace_id,
                        session_id=ctx.session_id,
                        turn_count=ctx.turn_count,
                        messages=messages,
                    )
                )
            except Exception:
                logger.exception(
                    "[Hook] %s.before_turn failed", type(hook).__name__
                )
                if hook.reraise:
                    raise
                continue
            if result is not None:
                messages = result
                changed = True
        return messages if changed else None

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


# ── 工具函数：API dict ↔ Message 转换 ──────────────────────────────────


def _api_dicts_to_messages(api_dicts: list[dict[str, Any]]) -> list["Message"]:
    """将 OpenAI API 格式的 dict 列表转换为 Message 对象列表（供 Consolidator 使用）。"""
    from app.models.message import Message as _Msg, ToolCall

    result: list["Message"] = []
    for d in api_dicts:
        tool_calls = []
        if d.get("tool_calls"):
            for tc in d["tool_calls"]:
                args_str = tc.get("function", {}).get("arguments", "{}")
                args = _json.loads(args_str) if isinstance(args_str, str) else args_str
                tool_calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args,
                                           extra_content=tc.get("extra_content", {})))
        result.append(_Msg(
            role=d["role"],
            content=d.get("content") or "",
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            reasoning_content=d.get("reasoning_content"),
            provider_state=d.get("provider_state", {}),
        ))
    return result


# ── 内置 Hook 实现 ─────────────────────────────────────────────────────


class ConsolidatorHook(AgentHook):
    """将 Consolidator 适配为 AgentHook，在每轮对话前自动压缩旧消息。

    用法::

        from app.conversation.consolidator import Consolidator
        from app.agent.agent_hooks import ConsolidatorHook

        consolidator = Consolidator(llm_gateway, memory_mgr, model="gpt-4o")
        hook = ConsolidatorHook(consolidator)
        agent = AgentThread(..., hooks=[hook])
    """

    def __init__(self, consolidator):
        from app.conversation.consolidator import Consolidator as _C

        if not isinstance(consolidator, _C):
            raise TypeError(f"Expected Consolidator, got {type(consolidator).__name__}")
        self._consolidator = consolidator

    def before_turn(self, ctx: BeforeTurnContext) -> list[dict[str, Any]] | None:
        messages = _api_dicts_to_messages(ctx.messages)
        compressed = self._consolidator.maybe_consolidate(messages, ctx.session_id)
        if compressed is not messages:
            logger.info(
                "[ConsolidatorHook] Compressed %d → %d messages",
                len(messages), len(compressed),
            )
            return [m.to_api_dict() for m in compressed]
        return None
