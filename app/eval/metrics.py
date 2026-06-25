"""指标聚合与改动前后对比 —— 让「换模型 / 改 prompt 到底变好没有」可量化。

聚合：把一次 run 里逐用例的 rule_scores（来自 rule_checks）按维度求平均。
对比：拿本次 run 的 avg 和 baseline run 的 avg 按维度比，标出改善 / 退步。

对比方向遵循 rule_checks 里的 HIGHER_IS_BETTER / LOWER_IS_BETTER：大多数维度
越大越好，redundant_call_rate 越小越好——所以「Δ 的好坏」要按维度方向解读，
不能一律「正数=变好」。
"""
from __future__ import annotations

from typing import Any

from app.eval import rule_checks

# 相对退步超过此比例即视为「显著退步」（文章给的经验阈值 ~5%，单机放宽到此处
# 仅用于 UI 标红提示，不做发布拦截）。
REGRESSION_THRESHOLD = 0.05


def aggregate(per_case_scores: list[dict[str, Any]]) -> dict[str, float]:
    """把逐用例的分数 dict 列表按维度求平均（只对出现过的维度求均值）。

    每个维度的分母是「该维度有值的用例数」，不是用例总数——避免不适用维度
    （某些 run 没有工具调用）把均值拉偏。
    """
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for scores in per_case_scores:
        for dim, val in (scores or {}).items():
            if not isinstance(val, (int, float)):
                continue
            sums[dim] = sums.get(dim, 0.0) + val
            counts[dim] = counts.get(dim, 0) + 1
    return {dim: round(sums[dim] / counts[dim], 4) for dim in sums}


def _is_improvement(dim: str, delta: float) -> bool:
    if dim in rule_checks.LOWER_IS_BETTER:
        return delta < 0
    return delta > 0


def compare(
    current: dict[str, Any], baseline: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """按维度对比 current vs baseline。

    返回每个维度一条记录：{dim, current, baseline, delta, improved, regressed}。
    baseline 为 None（首次评测无基线）时 delta/improved/regressed 均为 None。
    regressed：按维度方向判断的、且相对幅度超过阈值的退步——供 UI 标红。
    """
    rows: list[dict[str, Any]] = []
    dims = set(current) | set(baseline or {})
    for dim in sorted(dims):
        cur = current.get(dim)
        base = (baseline or {}).get(dim)
        row: dict[str, Any] = {
            "dim": dim, "current": cur, "baseline": base,
            "delta": None, "improved": None, "regressed": None,
        }
        if isinstance(cur, (int, float)) and isinstance(base, (int, float)):
            delta = round(cur - base, 4)
            improved = _is_improvement(dim, delta)
            # 相对幅度：以 baseline 为基准；baseline 为 0 时用绝对幅度兜底。
            rel = abs(delta) / abs(base) if base else abs(delta)
            row.update({
                "delta": delta,
                "improved": improved,
                "regressed": (not improved) and delta != 0 and rel >= REGRESSION_THRESHOLD,
            })
        rows.append(row)
    return rows


def has_regression(comparison: list[dict[str, Any]]) -> bool:
    """对比结果里是否存在任一显著退步维度。"""
    return any(row.get("regressed") for row in comparison)
