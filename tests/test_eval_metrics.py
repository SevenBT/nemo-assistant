"""指标聚合与对比测试。"""
from __future__ import annotations

from app.eval import metrics
from app.eval import rule_checks as rc


def test_aggregate_averages_per_dim():
    per_case = [
        {rc.DIM_TOOL_SUCCESS: 1.0, rc.DIM_COMPLETED: 1.0},
        {rc.DIM_TOOL_SUCCESS: 0.0, rc.DIM_COMPLETED: 1.0},
    ]
    avg = metrics.aggregate(per_case)
    assert avg[rc.DIM_TOOL_SUCCESS] == 0.5
    assert avg[rc.DIM_COMPLETED] == 1.0


def test_aggregate_divides_by_present_count_only():
    # tool_success 只在一条里出现，均值应按 1 条算，不被另一条稀释。
    per_case = [{rc.DIM_TOOL_SUCCESS: 0.8}, {rc.DIM_COMPLETED: 1.0}]
    avg = metrics.aggregate(per_case)
    assert avg[rc.DIM_TOOL_SUCCESS] == 0.8


def test_compare_no_baseline():
    rows = metrics.compare({rc.DIM_COMPLETED: 1.0}, None)
    assert rows[0]["delta"] is None
    assert rows[0]["regressed"] is None


def test_compare_higher_is_better_improvement():
    rows = metrics.compare({rc.DIM_TOOL_SUCCESS: 0.9}, {rc.DIM_TOOL_SUCCESS: 0.8})
    row = rows[0]
    assert row["improved"] is True
    assert row["regressed"] is False


def test_compare_higher_is_better_regression():
    rows = metrics.compare({rc.DIM_TOOL_SUCCESS: 0.5}, {rc.DIM_TOOL_SUCCESS: 1.0})
    assert rows[0]["improved"] is False
    assert rows[0]["regressed"] is True


def test_compare_lower_is_better_direction():
    # redundant 越小越好：从 0.4 降到 0.1 是改善，不是退步。
    rows = metrics.compare({rc.DIM_REDUNDANT: 0.1}, {rc.DIM_REDUNDANT: 0.4})
    assert rows[0]["improved"] is True
    assert rows[0]["regressed"] is False


def test_has_regression():
    rows = metrics.compare({rc.DIM_TOOL_SUCCESS: 0.5}, {rc.DIM_TOOL_SUCCESS: 1.0})
    assert metrics.has_regression(rows) is True
