"""失败案例回归集 —— 从 trace 一键回填用例（自维持的 Golden Set）。

不做 Golden Set 分层管理那套组织流程（单人养不起）。只做最朴素、最自维持的
一条：每条用例都因为「曾经坑过你」才入选——线上跑出问题的 trace，一键转成
回归用例。下次改 model / prompt 时重跑，确认旧 bug 没复活。

一条用例的本质 = 复现当时输入的最小材料：
    user_input       那次对话的用户问题（人读，用于列表展示）。
    api_messages     喂给 AgentLoop 的完整消息（重跑时原样复现输入语境）。
    expected_tools   期望调用到的工具名（来自原始 trace 实际成功调用过的工具，
                     作为「行为基线」；重跑时缺了它们是退步信号）。

关键约束：trace 本身不存 user / system 消息（只存 LLM 调用汇总、工具调用、
评测样本）。所以 user_input 必须由调用方（持有 SessionManager 的 UI 层）显式
传入——本模块不臆造、不从 answer 反推。
"""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def build_case_from_trace(
    trace_store,
    trace_id: str,
    *,
    user_input: str,
    title: str | None = None,
    completion_note: str | None = None,
) -> str | None:
    """把一条 trace 登记为回归用例，返回 case_id；失败返回 None。

    expected_tools 从 trace 实际成功调用过的工具名去重得到，作为行为基线。
    api_messages 回填一条只含该 user 输入的最小消息——重跑用例是「同样的问题，
    新的 model/prompt」，不需要复现旧的完整历史上下文。
    """
    if trace_store is None or not getattr(trace_store, "enabled", False):
        return None
    user_input = (user_input or "").strip()
    if not user_input:
        logger.warning("[cases] empty user_input, refuse to build case")
        return None

    data = trace_store.get_turn(trace_id) if trace_id else None
    expected_tools: list[str] = []
    if data:
        expected_tools = sorted({
            t["name"] for t in (data.get("tool_calls") or [])
            if t.get("name") and t.get("status") != "error"
        })

    case_id = uuid.uuid4().hex
    trace_store.add_eval_case(
        case_id=case_id,
        title=title or _auto_title(user_input),
        source_trace_id=trace_id or None,
        user_input=user_input,
        api_messages=[{"role": "user", "content": user_input}],
        expected_tools=expected_tools,
        completion_note=completion_note,
    )
    return case_id


def _auto_title(user_input: str) -> str:
    head = user_input.strip().splitlines()[0] if user_input.strip() else ""
    return head[:40] + ("…" if len(head) > 40 else "")
