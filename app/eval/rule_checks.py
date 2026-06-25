"""规则评测 —— 在一次 run 的 trace 数据上算确定性指标（零 LLM 成本）。

这是评测里最该练、又最贴桌面 Agent 的一块。文章 Agent 章节强调「结果对不代表
路径对」：换模型后散文质量一眼看得出，但「边缘问法下从调 run_python 退化成瞎编」
「工具失败后不再重试」「多调了俩没必要的工具」这些藏在日常不走的路径里，靠体感
抓不到。规则评测专治这类盲区。

全部为纯函数：输入是 TraceStore.get_turn() 返回的 dict（或其子结构），输出是
结构化的指标 dict。不碰 LLM、不碰 DB、不抛异常——可单测、可组合、可回放。

指标口径（对齐文章「Agent 评测 / 结构化输出评测」两节，精简到可自动计算的）：
    tool_success_rate     工具调用成功率 = 成功调用 / 总调用
    error_recovery_rate   错误恢复率 = 工具失败后最终仍完成 / 工具失败发生数
    redundant_call_rate   不必要调用率 = 重复（同名同参）调用 / 总调用
    json_valid_rate       结构化工具入参 JSON 合法率
    completed             任务是否到达成功终点（turn.status == ok）

完成标准（completion_criteria）属于「用例级期望」，不在此模块——本模块只看
**实际发生了什么**；期望与实际的比对在 metrics/runner 里做。
"""
from __future__ import annotations

import json
from typing import Any

# 指标维度名（落库 / UI / 对比的统一 key，避免散落字符串拼错）。
DIM_TOOL_SUCCESS = "tool_success_rate"
DIM_ERROR_RECOVERY = "error_recovery_rate"
DIM_REDUNDANT = "redundant_call_rate"
DIM_JSON_VALID = "json_valid_rate"
DIM_COMPLETED = "completed"

# 越大越好的维度（对比时 +Δ 为改善）。redundant_call_rate 反向：越小越好。
HIGHER_IS_BETTER = frozenset({
    DIM_TOOL_SUCCESS, DIM_ERROR_RECOVERY, DIM_JSON_VALID, DIM_COMPLETED,
    # 运行器产出的用例级维度（期望工具命中率），同属越大越好。
    "expected_tool_hit_rate",
})
LOWER_IS_BETTER = frozenset({DIM_REDUNDANT})


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and result.get("status") == "error"


def tool_success_rate(tool_calls: list[dict]) -> float | None:
    """工具调用成功率。无工具调用返回 None（该维度对本 run 不适用）。"""
    if not tool_calls:
        return None
    ok = sum(1 for t in tool_calls if t.get("status") != "error")
    return ok / len(tool_calls)


def error_recovery_rate(tool_calls: list[dict], completed: bool) -> float | None:
    """错误恢复率 —— 工具失败后 Agent 能否兜回正轨。

    单 turn 粒度近似：本 run 内只要发生过工具失败，就看这次 run 最终是否仍到达
    成功终点（completed）。无工具失败返回 None（无可恢复之物）。这是保守近似——
    更精细的「每次失败后是否被后续成功调用纠正」需要逐调用配对，单机场景不值当。
    """
    failures = sum(1 for t in tool_calls if _is_error(t))
    if failures == 0:
        return None
    return 1.0 if completed else 0.0


def redundant_call_rate(tool_calls: list[dict]) -> float | None:
    """不必要调用率 = 重复调用数 / 总调用数。

    重复定义：同一 (name, arguments) 在本 run 内出现多次，第 2 次起记为冗余。
    arguments 已是 TraceStore 落库的 JSON 字符串，直接当指纹用。这是「瞎忙」的
    确定性信号——不抓语义冗余，只抓字面重复，零误判。
    """
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


def score_turn(turn_data: dict) -> dict[str, float]:
    """对一次 run（TraceStore.get_turn 的返回）算全部确定性指标。

    返回只含「适用」维度（值非 None）的 dict——不适用的维度直接缺席，避免把
    「无工具调用」误读成「成功率 0」。completed 用 0/1 表示，便于和其它比率
    一起做平均与对比。
    """
    turn = turn_data.get("turn") or {}
    tool_calls = turn_data.get("tool_calls") or []
    completed = (turn.get("status") == "ok")

    raw = {
        DIM_TOOL_SUCCESS: tool_success_rate(tool_calls),
        DIM_ERROR_RECOVERY: error_recovery_rate(tool_calls, completed),
        DIM_REDUNDANT: redundant_call_rate(tool_calls),
        DIM_JSON_VALID: json_valid_rate(tool_calls),
        DIM_COMPLETED: 1.0 if completed else 0.0,
    }
    return {k: round(v, 4) for k, v in raw.items() if v is not None}
