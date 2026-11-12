"""Descriptive observations from legacy runtime traces, never task acceptance.

Normal completion after an error does not establish recovery. Repeated calls
may be necessary, and serialized argument validity may reflect trace truncation.
Use checks.evaluate with full execution evidence for acceptance decisions.
"""
from __future__ import annotations

import json
from typing import Any

# 指标维度名（落库 / UI / 对比的统一 key，避免散落字符串拼错）。
DIM_TOOL_SUCCESS = "tool_success_rate"
DIM_ERROR_RECOVERY = "execution_completed_after_tool_error"
DIM_REDUNDANT = "duplicate_call_rate"
DIM_JSON_VALID = "json_valid_rate"
DIM_COMPLETED = "execution_completed"

# 越大越好的维度（对比时 +Δ 为改善）。redundant_call_rate 反向：越小越好。
HIGHER_IS_BETTER = frozenset({
    DIM_TOOL_SUCCESS, DIM_ERROR_RECOVERY, DIM_JSON_VALID, DIM_COMPLETED,
})
LOWER_IS_BETTER = frozenset({DIM_REDUNDANT})


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and result.get("status") == "error"


def tool_success_rate(tool_calls: list[dict]) -> float | None:
    """工具调用成功率。无工具调用返回 None（该维度对本 run 不适用）。"""
    if not tool_calls:
        return None
    ok = sum(1 for t in tool_calls if t.get("status") in {"success", "ok"})
    return ok / len(tool_calls)


def error_recovery_rate(tool_calls: list[dict], completed: bool) -> float | None:
    """Whether execution ended normally after any tool error; not task recovery."""
    failures = sum(1 for t in tool_calls if _is_error(t))
    if failures == 0:
        return None
    return 1.0 if completed else 0.0


def redundant_call_rate(tool_calls: list[dict]) -> float | None:
    """Literal duplicate-call fraction; this does not imply unnecessary work."""
    if not tool_calls:
        return None
    seen: set[tuple[str, str]] = set()
    redundant = 0
    for t in tool_calls:
        key = (t.get("name", ""), t.get("arguments") or "")
        if key in seen:
            redundant += 1
        else:
            seen.add(key)
    return redundant / len(tool_calls)


def json_valid_rate(tool_calls: list[dict]) -> float | None:
    """结构化工具入参 JSON 合法率。

    arguments 是 TraceStore 已序列化的 JSON 字符串；能 json.loads 即合法。
    无入参的调用（arguments 为 None/空）不计入分母——没有结构化输出可评。
    """
    typed = [t for t in tool_calls if (t.get("arguments") or "").strip()]
    if not typed:
        return None
    valid = 0
    for t in typed:
        try:
            json.loads(t["arguments"])
            valid += 1
        except (TypeError, ValueError):
            pass
    return valid / len(typed)


def score_trace(trace_data: dict) -> dict[str, float]:
    """对一次完整 Trace（TraceStore.get_trace 的返回）算全部确定性指标。

    返回只含「适用」维度（值非 None）的 dict——不适用的维度直接缺席，避免把
    「无工具调用」误读成「成功率 0」。completed 用 0/1 表示，便于和其它比率
    一起做平均与对比。
    """
    trace = trace_data.get("trace") or {}
    tool_calls = trace_data.get("tool_calls") or []
    completed = (trace.get("status") == "ok")

    raw = {
        DIM_TOOL_SUCCESS: tool_success_rate(tool_calls),
        DIM_ERROR_RECOVERY: error_recovery_rate(tool_calls, completed),
        DIM_REDUNDANT: redundant_call_rate(tool_calls),
        DIM_JSON_VALID: json_valid_rate(tool_calls),
        DIM_COMPLETED: 1.0 if completed else 0.0,
    }
    return {k: round(v, 4) for k, v in raw.items() if v is not None}
