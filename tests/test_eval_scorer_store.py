"""scorer + trace_store 评测表的集成测试（用临时 DB）。"""
from __future__ import annotations

import json

from app.core.trace_store import TraceStore
from app.eval import scorer
from app.eval import rule_checks as rc


def _store(tmp_path):
    return TraceStore(db_path=tmp_path / "t.db")


def _seed_turn(store, trace_id, *, status="ok", tools=None):
    store.start_turn(trace_id, "sess")
    for tc in tools or []:
        store.record_tool_call(
            trace_id,
            call_id=tc.get("call_id", "c1"),
            name=tc["name"],
            arguments=tc.get("args", {}),
            result={"status": tc.get("status", "success"), "data": {}},
            duration_ms=1.0,
        )
    store.record_eval_sample(
        trace_id, turn=0, answer="答复", tool_count=len(tools or []),
        error_count=0, had_error=False,
    )
    store.finish_turn(trace_id, status=status, turn_count=1, duration_ms=10.0)


def test_scorer_fills_scores(tmp_path):
    store = _store(tmp_path)
    _seed_turn(store, "tr1", status="ok", tools=[
        {"name": "calc", "args": {"x": 1}, "status": "success"},
    ])

    # 打分前 scores 为空。
    before = store.list_unscored_eval_samples()
    assert len(before) == 1

    n = scorer.score_unscored_samples(store)
    assert n == 1

    # 打分后不再是 unscored，且 scores 含规则维度。
    assert store.list_unscored_eval_samples() == []
    sample = store.list_eval_samples()[0]
    scores = json.loads(sample["scores"])
    assert scores[rc.DIM_COMPLETED] == 1.0
    assert scores[rc.DIM_TOOL_SUCCESS] == 1.0


def test_scorer_idempotent_skips_already_scored(tmp_path):
    store = _store(tmp_path)
    _seed_turn(store, "tr1")
    assert scorer.score_unscored_samples(store) == 1
    # 第二次没有未打分样本。
    assert scorer.score_unscored_samples(store) == 0


def test_eval_cases_crud(tmp_path):
    store = _store(tmp_path)
    store.add_eval_case(
        case_id="c1", title="t", source_trace_id="tr1",
        user_input="问题", api_messages=[{"role": "user", "content": "问题"}],
        expected_tools=["calc"], completion_note=None,
    )
    cases = store.list_eval_cases()
    assert len(cases) == 1 and cases[0]["case_id"] == "c1"

    store.set_eval_case_enabled("c1", False)
    assert store.list_eval_cases(enabled_only=True) == []
    assert len(store.list_eval_cases(enabled_only=False)) == 1

    store.delete_eval_case("c1")
    assert store.list_eval_cases(enabled_only=False) == []


def test_eval_run_lifecycle(tmp_path):
    store = _store(tmp_path)
    store.start_eval_run(
        run_id="r1", label="L", model="m", prompt_version=None,
        git_commit="abc", case_count=2, baseline_run_id=None,
    )
    store.add_eval_result(
        run_id="r1", case_id="c1", trace_id="tr1", actual_output="out",
        rule_scores={rc.DIM_COMPLETED: 1.0}, judge_scores={"helpfulness": 5},
    )
    store.finish_eval_run("r1", avg_scores={rc.DIM_COMPLETED: 1.0})

    runs = store.list_eval_runs()
    assert len(runs) == 1 and runs[0]["run_id"] == "r1"
    assert json.loads(runs[0]["avg_scores"])[rc.DIM_COMPLETED] == 1.0
    results = store.get_eval_results("r1")
    assert len(results) == 1 and results[0]["case_id"] == "c1"
