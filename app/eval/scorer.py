"""离线打分器 —— 把规则评测分数写回 eval_samples.scores，合上线上采集的闭环。

这是整套系统真正的缺口：EvalHook 每轮采集了样本，但 scores 列从建表到 UI
全程留空（trace_store 注释写着「留空待离线打分」，而离线打分一直不存在）。
本模块就是那个缺失的「离线打分」步骤。

设计：纯离线、手动触发（个人应用不需要在线自动评测，省 token 也不拖慢对话）。
默认只用规则评测（确定性、零成本）；judge 打分是可选项，由调用方传入 judge_fn
时才叠加（见 judge.py）。
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from app.eval import rule_checks

logger = logging.getLogger(__name__)

# judge_fn 签名：接收一条 eval_sample dict，返回 {维度: 分} 或 None。
JudgeFn = Callable[[dict[str, Any]], dict[str, Any] | None]


def score_unscored_samples(
    trace_store,
    *,
    limit: int = 500,
    judge_fn: JudgeFn | None = None,
) -> int:
    """给所有 scores 为空的样本打分并回写。返回成功打分的样本数。

    每条样本独立 try/except：单条失败不影响其余（评测是辅助功能，坏一条不该
    中断整批）。规则分基于该样本所属 turn 的完整 trace 计算。
    """
    if trace_store is None or not getattr(trace_store, "enabled", False):
        return 0

    samples = trace_store.list_unscored_eval_samples(limit=limit)
    scored = 0
    for sample in samples:
        try:
            scores = _score_one(trace_store, sample, judge_fn)
            if scores:
                trace_store.update_eval_scores(sample["id"], scores)
                scored += 1
        except Exception:
            logger.exception(
                "[scorer] failed to score sample %s", sample.get("id")
            )
    return scored


def _score_one(
    trace_store, sample: dict[str, Any], judge_fn: JudgeFn | None
) -> dict[str, Any]:
    """对单条样本算规则分（+ 可选 judge 分），合并成一个 scores dict。"""
    trace_id = sample.get("trace_id")
    turn_data = trace_store.get_turn(trace_id) if trace_id else None

    scores: dict[str, Any] = {}
    if turn_data:
        scores.update(rule_checks.score_turn(turn_data))

    if judge_fn is not None and (sample.get("answer") or "").strip():
        try:
            judged = judge_fn(sample)
        except Exception:
            logger.exception("[scorer] judge_fn raised for sample %s", sample.get("id"))
            judged = None
        if judged:
            scores.update({f"judge_{k}": v for k, v in judged.items()})

    return scores
