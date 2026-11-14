"""Exercise Judge validation without trusting an actual model response."""
import json

import pytest
from jsonschema import ValidationError

from nemo_eval.artifacts import read_json
from nemo_eval.judge import assess_run, judge
from nemo_eval.reporting import make_view
from nemo_eval.runner import exit_code, run
from nemo_eval.suites import select_suite


def case_and_execution():
    return (
        {"input": {"mode": "scenario", "steps": [{"id": "ask", "user": "Answer from the supplied file"}]},
         "expectations": {}, "rubric": [{"id": "grounded", "description": "Use actual evidence"}]},
        {"answer": "42", "evidence_complete": True, "tool_calls": [], "artifacts": {}},
    )


def response():
    return {"status": "scored", "reason": "checked", "criteria": [
        {"id": "grounded", "verdict": "pass", "reason": "matches", "evidence_ids": ["answer"]},
    ]}


@pytest.mark.parametrize("raw", ["not JSON", "{", '```json\n{}\n```'])
def test_malformed_json_is_rejected(raw):
    case, execution = case_and_execution()
    with pytest.raises(json.JSONDecodeError):
        judge(case, execution, lambda _: raw)


@pytest.mark.parametrize("change", ["missing", "duplicate", "invented"])
def test_criteria_must_match_rubric_exactly_once(change):
    case, execution = case_and_execution()
    result = response()
    if change == "missing":
        result["criteria"] = []
    elif change == "duplicate":
        result["criteria"] *= 2
    else:
        result["criteria"][0]["id"] = "not-in-rubric"
    with pytest.raises(ValueError, match="omitted, duplicated or invented"):
        judge(case, execution, lambda _: json.dumps(result))


@pytest.mark.parametrize("evidence_ids,verdict", [
    (["artifact:missing.txt"], "pass"), ([], "pass"), ([], "fail"),
], ids=["invented-evidence", "pass-without-evidence", "fail-without-evidence"])
def test_definite_verdict_requires_existing_evidence(evidence_ids, verdict):
    case, execution = case_and_execution()
    result = response()
    result["criteria"][0].update(evidence_ids=evidence_ids, verdict=verdict)
    with pytest.raises(ValueError, match="nonexistent evidence|requires evidence"):
        judge(case, execution, lambda _: json.dumps(result))


@pytest.mark.parametrize("change", ["missing-field", "extra-field", "invalid-verdict"])
def test_invalid_response_schema_is_rejected(change):
    case, execution = case_and_execution()
    result = response()
    if change == "missing-field":
        del result["criteria"][0]["evidence_ids"]
    elif change == "extra-field":
        result["score"] = 100
    else:
        result["criteria"][0]["verdict"] = "probably"
    with pytest.raises(ValidationError):
        judge(case, execution, lambda _: json.dumps(result))


def test_unknown_verdict_can_abstain_without_inventing_evidence():
    case, execution = case_and_execution()
    execution["evidence_complete"] = False
    result = response()
    result.update(status="abstain")
    result["criteria"][0].update(verdict="unknown", evidence_ids=[])
    actual = judge(case, execution, lambda _: json.dumps(result))
    assert actual["status"] == "abstain" and actual["criteria"][0]["verdict"] == "unknown"


def test_incomplete_execution_cannot_receive_scored_response():
    case, execution = case_and_execution()
    execution["evidence_complete"] = False
    with pytest.raises(ValueError, match="must abstain"):
        judge(case, execution, lambda _: json.dumps(response()))


def test_oversized_evidence_fails_before_client_dispatch():
    case, execution = case_and_execution()
    execution["answer"] = "x" * 60001
    called = []
    with pytest.raises(ValueError, match="exceeds input limit"):
        judge(case, execution, lambda messages: called.append(messages))
    assert not called


@pytest.mark.parametrize("raw", [
    "{",
    json.dumps({"status": "scored", "reason": "invented", "criteria": [
        {"id": "grounded", "verdict": "pass", "reason": "claimed", "evidence_ids": ["artifact:missing.txt"]},
    ]}),
], ids=["invalid-json", "invented-evidence"])
def test_invalid_judge_is_recorded_with_spent_budget_and_cannot_pass(tmp_path, monkeypatch, raw):
    from nemo_eval.adapters import nemo
    case = select_suite("live-smoke").cases[0]
    case.update(rubric=case_and_execution()[0]["rubric"], judge_required=True)
    directory = tmp_path / "run"
    run([case], directory, mode="live", config={"target": {"model": "controlled", "api_key_env": "TEST_TARGET", "max_tokens": 100}},
        executor=lambda _: {"execution_status": "completed", "answer": "42", "evidence_complete": True,
                            "model_calls": 1, "output_reserved": 100})
    evidence = directory / "cases" / case["id"] / "1" / "execution.json"
    before = evidence.read_bytes()
    dispatched = []

    def gateway(profile, logger):
        class ControlledGateway:
            def chat_stream(self, messages, **kwargs):
                dispatched.append(messages)
                logger.write({"attempt_id": "judge-1", "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                              "provider_cost": {"amount": 0.02, "currency": "CNY"}})
                yield {"type": "text", "delta": raw}
                yield {"type": "done"}
        return ControlledGateway()

    monkeypatch.setattr(nemo, "make_live_gateway", gateway)
    rows = assess_run(directory, {"judge": {"model": "controlled", "api_key_env": "TEST_JUDGE", "max_tokens": 100},
                                  "budget": {"max_model_calls": 1, "max_output_tokens": 100}})
    assert len(dispatched) == 1 and rows[0]["status"] == "error"
    view = make_view(directory, rows[0]["assessment_id"])
    assert view["counts"]["inconclusive"] == 1 and exit_code(view) == 3
    summary = view["judge"]
    assert summary["budget_usage"] == {"model_calls": 1, "output_reserved": 100}
    assert summary["cost"]["provider_reported"] == {"CNY": 0.02}
    assert summary["cost"]["complete"]
    saved = directory / "assessments" / rows[0]["assessment_id"] / case["id"] / "1"
    assert read_json(saved / "raw_responses.json") == [raw]
    assert read_json(saved / "llm_calls.json")[0]["usage"]["completion_tokens"] == 5
    assert evidence.read_bytes() == before
