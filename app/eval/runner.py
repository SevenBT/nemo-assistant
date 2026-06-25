"""评测运行器 —— 用当前 model/prompt 重跑用例集，规则打分并落库。

复用 AgentLoop（不另起一套执行逻辑）：AgentLoop 是 QThread，但 run() 可在当前
线程直接调用同步执行——它的 Qt 信号在无接收者时是 no-op，且每次 run 都会把全链路
落进 TraceStore。所以运行器对每条用例：
    1. 直接 new AgentLoop(...).run()（同步、阻塞）→ 产出一个新 trace_id。
    2. 从 TraceStore 取回该 trace → rule_checks 算分 → metrics 聚合。
    3. 落 eval_runs / eval_results，供 compare 与 UI。

baseline：默认取上一次 run 作基线，让「这次改动相对上次变好没有」自动可比。
judge 可选：传入 judge_fn 时对每条用例的最终答复叠加 LLM-as-Judge 分。
"""
from __future__ import annotations

import logging
import subprocess
import uuid
from typing import Any, Callable

from app.core.agent_loop import AgentLoop
from app.eval import metrics, rule_checks

logger = logging.getLogger(__name__)

# judge_fn 签名：接收 (case, trace_data) 返回 {维度: 分} 或 None。
JudgeFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]

# 进度回调：(完成数, 总数, 当前用例标题)。
ProgressFn = Callable[[int, int, str], None]


def run_eval(
    *,
    trace_store,
    llm_gateway,
    registry,
    prompt_builder=None,
    label: str | None = None,
    model: str | None = None,
    judge_fn: JudgeFn | None = None,
    progress_fn: ProgressFn | None = None,
    max_turns: int = 6,
) -> str | None:
    """跑一遍启用的回归用例集，返回 run_id；无用例或遥测禁用返回 None。

    prompt_builder（可选）：传入则用它把用例的 user 消息构建成完整 api_messages
    （带 system / 记忆等），更贴近真实运行；不传则直接用用例存的最小消息。
    """
    if trace_store is None or not getattr(trace_store, "enabled", False):
        return None
    cases = trace_store.list_eval_cases(enabled_only=True)
    if not cases:
        return None

    run_id = uuid.uuid4().hex
    baseline_run_id = _latest_run_id(trace_store)
    trace_store.start_eval_run(
        run_id=run_id,
        label=label,
        model=model,
        prompt_version=None,
        git_commit=_git_commit(),
        case_count=len(cases),
        baseline_run_id=baseline_run_id,
    )

    per_case_scores: list[dict[str, Any]] = []
    total = len(cases)
    for idx, case in enumerate(cases):
        if progress_fn:
            progress_fn(idx, total, case.get("title") or case.get("case_id", ""))
        try:
            scores = _run_one_case(
                case, trace_store, llm_gateway, registry,
                prompt_builder, run_id, judge_fn, max_turns,
            )
            if scores:
                per_case_scores.append(scores)
        except Exception:
            logger.exception("[runner] case %s failed", case.get("case_id"))

    avg = metrics.aggregate(per_case_scores)
    trace_store.finish_eval_run(run_id, avg_scores=avg)
    if progress_fn:
        progress_fn(total, total, "")
    return run_id


def _run_one_case(
    case: dict[str, Any],
    trace_store,
    llm_gateway,
    registry,
    prompt_builder,
    run_id: str,
    judge_fn: JudgeFn | None,
    max_turns: int,
) -> dict[str, Any]:
    """重跑一条用例 → 规则打分（+ 可选 judge）→ 落 eval_results。返回该用例分数。"""
    api_messages = _build_messages(case, prompt_builder)

    loop = AgentLoop(
        llm_gateway=llm_gateway,
        registry=registry,
        api_messages=api_messages,
        session_id="",  # 评测重跑不归属任何真实会话
        max_turns=max_turns,
        trace_store=trace_store,
        hooks=None,  # 重跑不需要安全/埋点 hook，trace 已自动落库
    )
    loop.run()  # 同步执行，阻塞至本 turn 结束
    trace_id = loop._trace_id  # AgentLoop 为本次 run 生成的统一 trace_id

    turn_data = trace_store.get_turn(trace_id)
    scores: dict[str, Any] = {}
    actual_output = None
    if turn_data:
        scores.update(rule_checks.score_turn(turn_data))
        scores.update(_expected_tools_score(case, turn_data))
        actual_output = _final_answer(turn_data)

    judge_scores = None
    if judge_fn is not None and turn_data and (actual_output or "").strip():
        try:
            judge_scores = judge_fn(case, turn_data)
        except Exception:
            logger.exception("[runner] judge_fn raised for case %s", case.get("case_id"))
        if judge_scores:
            scores.update({f"judge_{k}": v for k, v in judge_scores.items()})

    trace_store.add_eval_result(
        run_id=run_id,
        case_id=case["case_id"],
        trace_id=trace_id,
        actual_output=actual_output,
        rule_scores={k: v for k, v in scores.items() if not k.startswith("judge_")},
        judge_scores=judge_scores,
    )
    return scores


def _build_messages(case: dict[str, Any], prompt_builder) -> list[dict]:
    """构建喂给 AgentLoop 的消息。优先用 prompt_builder 贴近真实运行。

    prompt_builder.build() 接收的是 Message 实体列表（内部会调 .to_api_dict()），
    不是 dict——所以这里把用例的 user 输入包成 Message 再交给它。
    """
    user_input = case.get("user_input") or ""
    if prompt_builder is not None:
        try:
            from app.models.message import Message, MessageRole

            user_msg = Message(role=MessageRole.USER, content=user_input)
            return prompt_builder.build([user_msg], "")
        except Exception:
            logger.exception("[runner] prompt_builder failed, fall back to raw")
    import json
    stored = case.get("api_messages")
    if stored:
        try:
            return json.loads(stored) if isinstance(stored, str) else stored
        except (TypeError, ValueError):
            pass
    return [{"role": "user", "content": user_input}]


def _expected_tools_score(case: dict[str, Any], turn_data: dict) -> dict[str, float]:
    """期望工具命中率 = 实际调用到的期望工具 / 期望工具数。

    用例的 expected_tools 是行为基线；重跑时若漏调了基线工具，是退步信号。
    无 expected_tools 的用例不产出该维度。
    """
    import json
    raw = case.get("expected_tools")
    try:
        expected = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        expected = []
    if not expected:
        return {}
    actual = {t.get("name") for t in (turn_data.get("tool_calls") or [])}
    hit = sum(1 for name in expected if name in actual)
    return {"expected_tool_hit_rate": round(hit / len(expected), 4)}


def _final_answer(turn_data: dict) -> str | None:
    """取该 run 最后一轮的助手答复文本（评测最关心的产物）。"""
    samples = turn_data.get("eval_samples") or []
    for s in reversed(samples):
        if s.get("answer"):
            return s["answer"]
    return None


def _latest_run_id(trace_store) -> str | None:
    runs = trace_store.list_eval_runs(limit=1)
    return runs[0]["run_id"] if runs else None


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return out.stdout.strip() or None
    except Exception:
        return None
