"""规则评测纯函数测试 —— 确定性指标的口径与边界。"""
from __future__ import annotations

import json

from app.eval import rule_checks as rc


def _tool(name="t", args=None, status="success"):
    return {
        "name": name,
        "arguments": json.dumps(args) if args is not None else None,
        "status": status,
    }


# ── tool_success_rate ────────────────────────────────────────────────────

def test_tool_success_rate_none_when_no_calls():
    assert rc.tool_success_rate([]) is None


def test_tool_success_rate_counts_non_error():
    calls = [_tool(status="success"), _tool(status="error"), _tool(status="success")]
    assert rc.tool_success_rate(calls) == 2 / 3


# ── error_recovery_rate ──────────────────────────────────────────────────

def test_error_recovery_none_without_failure():
    calls = [_tool(status="success")]
    assert rc.error_recovery_rate(calls, completed=True) is None


def test_error_recovery_one_when_failed_but_completed():
    calls = [_tool(status="error"), _tool(status="success")]
    assert rc.error_recovery_rate(calls, completed=True) == 1.0


def test_error_recovery_zero_when_failed_and_not_completed():
    calls = [_tool(status="error")]
    assert rc.error_recovery_rate(calls, completed=False) == 0.0


# ── redundant_call_rate ──────────────────────────────────────────────────

def test_redundant_call_rate_detects_duplicate():
    calls = [
        _tool("search", {"q": "a"}),
        _tool("search", {"q": "a"}),  # 重复
        _tool("search", {"q": "b"}),
    ]
    assert rc.redundant_call_rate(calls) == 1 / 3


def test_redundant_call_rate_zero_when_all_unique():
    calls = [_tool("a", {"x": 1}), _tool("b", {"x": 1})]
    assert rc.redundant_call_rate(calls) == 0.0


# ── json_valid_rate ──────────────────────────────────────────────────────

def test_json_valid_rate_ignores_argless_calls():
    calls = [_tool(args=None), _tool(args=None)]
    assert rc.json_valid_rate(calls) is None


def test_json_valid_rate_flags_malformed():
    calls = [_tool(args={"ok": 1}), {"name": "x", "arguments": "{bad json", "status": "success"}]
    assert rc.json_valid_rate(calls) == 0.5


# ── score_turn ───────────────────────────────────────────────────────────

def test_score_turn_omits_inapplicable_dims():
    turn_data = {"turn": {"status": "ok"}, "tool_calls": []}
    scores = rc.score_turn(turn_data)
    # 无工具调用：成功率/恢复率/冗余/JSON 都不适用，只剩 completed。
    assert scores == {rc.DIM_COMPLETED: 1.0}


def test_score_turn_full():
    turn_data = {
        "turn": {"status": "ok"},
        "tool_calls": [
            _tool("a", {"x": 1}, status="error"),
            _tool("a", {"x": 1}, status="success"),  # 重复 + 恢复
        ],
    }
    scores = rc.score_turn(turn_data)
    assert scores[rc.DIM_COMPLETED] == 1.0
    assert scores[rc.DIM_TOOL_SUCCESS] == 0.5
    assert scores[rc.DIM_ERROR_RECOVERY] == 1.0
    assert scores[rc.DIM_REDUNDANT] == 0.5
    assert scores[rc.DIM_JSON_VALID] == 1.0
