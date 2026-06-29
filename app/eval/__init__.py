"""Offline evaluation subsystem — deterministic rule checks, regression cases,
and run-to-run comparison on top of already-captured traces.

Design stance (a single-user desktop agent, not a multi-tenant product):
    The evaluation foundation (TraceStore's six tables + two hooks + the replay
    page) is already in place; this package only closes the half-finished loop
    — "samples are captured but never scored." It focuses on the deterministic,
    self-sustaining slice: rule checks surface blind spots, a failure-case
    regression set guards against old bugs resurfacing, and before/after
    comparison makes model/prompt changes quantifiable.

Out of scope (dead weight for single-user): tiered Golden Set management,
human judge-calibration loops, regression gating on release, canary bucketing,
continuous sampling re-evaluation.

Module breakdown:
    rule_checks  pure functions computing deterministic metrics on one run's
                 trace data (zero LLM cost).
    scorer       writes rule scores back to eval_samples.scores, closing the
                 loop with online capture.
    cases        failure-case regression set: one-click backfill from traces
                 (a self-sustaining Golden Set).
    runner       re-runs the case set with the current model/prompt (reusing
                 AgentLoop) -> rule scoring.
    metrics      aggregates one run's metrics and compares them dimension-wise
                 against the previous run (regressions flagged red).
    judge        optional LLM-as-Judge: scores open-ended answers on 3 axes,
                 triggered on demand.

离线评测子系统 —— 在已采集的 trace 之上做确定性规则评测、回归用例与对比。

设计立场（针对单机单用户桌面 Agent，而非多用户产品）：
    评测的地基（TraceStore 六表 + 两个 Hook + 回放页）已经铺好，本包只补上
    断在半路的闭环——「采集了样本却从不打分」。聚焦范式里**确定性、自维持**
    的那一小块：规则评测抓体感盲区，失败案例回归集防旧 bug 复活，改动前后对比
    让换模型/改 prompt 可量化。

不做（对单机是空转器官）：Golden Set 分层管理、judge 人工校准循环、回归门禁
拦截发布、灰度分桶、持续采样回评。

模块分工：
    rule_checks  纯函数：在一次 run 的 trace 数据上算确定性指标（零 LLM 成本）。
    scorer       把规则分数写回 eval_samples.scores，合上线上采集的闭环。
    cases        失败案例回归集：从 trace 一键回填用例（自维持的 Golden Set）。
    runner       用当前 model/prompt 重跑用例集（复用 AgentLoop）→ 规则打分。
    metrics      聚合一次 run 的指标，并与上一次 run 按维度对比（退步标红）。
    judge        可选 LLM-as-Judge：给开放回答打 3 维分，单次按需触发。
"""
