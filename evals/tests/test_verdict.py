"""Final task verdict precedence, including failure and uncertainty."""
import pytest

from nemo_eval.checks import verdict


@pytest.mark.parametrize("execution_status,check_status,complete,required,judge_status,criteria,expected", [
    ("error", "pass", True, True, "scored", ["pass"], "error"),
    ("timeout", "fail", False, True, "scored", ["pass"], "error"),
    ("completed", "error", True, True, "scored", ["pass"], "error"),
    ("completed", "fail", True, True, "scored", ["pass"], "fail"),
    ("completed", "fail", False, True, "abstain", ["unknown"], "fail"),
    ("completed", "pass", False, True, "scored", ["pass"], "inconclusive"),
    ("completed", "pass", True, True, None, [], "inconclusive"),
    ("completed", "pass", True, True, "abstain", ["unknown"], "inconclusive"),
    ("completed", "pass", True, True, "error", [], "inconclusive"),
    ("completed", "pass", True, True, "scored", ["unknown"], "inconclusive"),
    ("completed", "pass", True, True, "scored", ["pass", "fail", "unknown"], "fail"),
    ("completed", "pass", True, True, "scored", ["pass", "pass"], "pass"),
    ("completed", None, True, True, "scored", ["pass"], "pass"),
    ("completed", None, True, False, None, [], "inconclusive"),
    ("completed", "pass", True, False, "scored", ["fail"], "pass"),
], ids=[
    "execution-error-first", "timeout-first", "check-error-first", "hard-fail-beats-judge-pass",
    "hard-fail-beats-missing-evidence", "incomplete-evidence", "missing-judge", "judge-abstains",
    "judge-errors", "judge-unknown", "judge-fail-beats-unknown", "all-criteria-pass",
    "judge-only-acceptance", "no-acceptance", "optional-judge-does-not-override",
])
def test_verdict_precedence(execution_status, check_status, complete, required, judge_status, criteria, expected):
    execution = {"execution_status": execution_status, "evidence_complete": complete}
    checks = [{"status": check_status}] if check_status else []
    assessment = ({"status": judge_status, "criteria": [{"verdict": v} for v in criteria]}
                  if judge_status else None)
    assert verdict(execution, checks, judge_required=required, judge=assessment) == expected


def test_declared_expected_error_can_pass_when_task_acceptance_succeeds():
    execution = {"execution_status": "error", "expected_statuses": ["error"], "evidence_complete": True}
    assert verdict(execution, [{"status": "pass"}]) == "pass"


def test_check_error_takes_precedence_over_other_failed_checks():
    execution = {"execution_status": "completed", "evidence_complete": True}
    assert verdict(execution, [{"status": "fail"}, {"status": "error"}]) == "error"
