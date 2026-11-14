"""
AgentContext — Agent 运行的中央上下文。

将 Agent 运行所需的三类横切关注点打包为一个 dataclass：
    - callbacks     : 与外部世界的通信接口（替代 Qt 信号，支持 headless / 多 UI 框架）
    - hooks         : Agent 生命周期 hook（评测埋点、安全审批等）
    - cancel_token  : 线程安全的取消令牌

设计动机：
    当前 AgentThread.__init__ 接收大量零散参数。AgentContext 作为统一入口，
    让调用方只需构造一个上下文对象即可启动 Agent，降低参数传递复杂度，
    运行时依赖只指向核心协议。

与现有组件的关系：
    - agent_interface.AgentCallbacks   → 通信接口（已有）
    - agent_hooks.AgentHook            → 生命周期 hook（已有）
    - runtime.cancellation.CancellationToken    → 取消令牌（已有）
    - turn_context.TurnContext         → 单轮对话上下文（独立，不纳入此处）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from app.agent.agent_hooks import AgentHook, CompositeHook
from app.agent.agent_interface import AgentCallbacks
from app.agent.contracts import (
    CheckpointStore, ModelStream, NullCheckpointStore, NullTraceSink,
    ToolRuntime, TraceSink,
)
from app.runtime.cancellation import CancellationToken


@dataclass
class AgentContext:
    """Agent 运行的中央上下文。

    用法：
        ctx = AgentContext(
            callbacks=AgentCallbacks.print(),
            hooks=[MyAuditHook()],
        )

        # 传递给 Agent
        agent = Agent(ctx, messages)

        # 取消运行
        ctx.cancel()

        # 检查取消状态
        if ctx.is_cancelled:
            ...
    """

    # ── 通信接口 ──
    callbacks: AgentCallbacks = field(default_factory=AgentCallbacks.silent)
    """与外部世界的通信接口。默认静默（丢弃所有事件），适用于测试。"""

    # ── 生命周期 hook ──
    hooks: list[AgentHook] = field(default_factory=list)
    """Agent 生命周期 hook 列表。按顺序执行，空列表等于无 hook。"""

    # ── 取消令牌 ──
    cancel_token: CancellationToken = field(default_factory=CancellationToken)
    """线程安全的取消令牌。可跨线程安全地触发取消并关闭流式资源。"""

    # ── 核心依赖 ──
    llm_gateway: ModelStream | None = None
    """LLM 网关。Agent 运行时必需。"""

    registry: ToolRuntime | None = None
    """工具运行协议（字段名沿用 registry）。Agent 运行时必需。"""

    checkpoint_store: CheckpointStore = field(default_factory=NullCheckpointStore)
    """Explicit checkpoint backend; the default never writes to disk."""

    trace_store: TraceSink = field(default_factory=NullTraceSink)
    """Explicit trace backend; the default discards observations."""

    # ── 便捷属性 ──

    @property
    def composite_hook(self) -> CompositeHook | None:
        """将 hooks 列表组合为单个 CompositeHook。

        Returns:
            CompositeHook 实例（如果 hooks 非空），否则 None。
        """
        if not self.hooks:
            return None
        return CompositeHook(self.hooks)

    @property
    def is_cancelled(self) -> bool:
        """当前是否已被取消。"""
        return self.cancel_token.is_cancelled()

    # ── 便捷方法 ──

    def cancel(self) -> None:
        """请求取消当前 Agent 运行。

        线程安全：可从任意线程调用。
        幂等：重复调用无害。
        """
        self.cancel_token.cancel()
