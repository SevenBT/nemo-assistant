"""Budget boundaries and provider charge accounting; no local pricing."""
import copy

import pytest

from nemo_eval.budget import Budget, cost_summary, validate_config


@pytest.mark.parametrize("limits,message", [
    ({"max_model_calls": 2, "max_output_tokens": 30}, "Model call budget"),
    ({"max_model_calls": 3, "max_output_tokens": 20}, "Output token reservation"),
    ({"max_model_calls": 2, "max_output_tokens": 20}, "Model call budget"),
], ids=["call-limit", "token-limit", "both-limits"])
def test_exact_budget_limit_is_allowed_but_next_reservation_is_atomic(limits, message):
    profile = {"max_tokens": 10}
    budget = Budget(validate_config({"budget": limits}))
    budget.reserve(profile)
    budget.reserve(profile)
    assert (budget.calls, budget.output_reserved) == (2, 20)
    for _ in range(2):
        with pytest.raises(ValueError, match=message):
            budget.reserve(profile)
        assert (budget.calls, budget.output_reserved) == (2, 20)


def test_failed_output_reservation_leaves_room_for_smaller_request():
    budget = Budget({"budget": {"max_model_calls": 3, "max_output_tokens": 15}})
    budget.reserve({"max_tokens": 10})
    with pytest.raises(ValueError, match="Output token"):
        budget.reserve({"max_tokens": 10})
    assert (budget.calls, budget.output_reserved) == (1, 10)
    budget.reserve({"max_tokens": 5})
    assert (budget.calls, budget.output_reserved) == (2, 15)


@pytest.mark.parametrize("section", ["target", "judge"])
@pytest.mark.parametrize("pricing", [{}, {"input_per_1m": 1, "output_per_1m": 2}])
def test_obsolete_pricing_configuration_is_rejected(section, pricing):
    with pytest.raises(ValueError, match="remove pricing"):
        validate_config({section: {"model": "test", "api_key_env": "TEST_KEY", "pricing": pricing}})


def test_provider_charges_preserve_currency_zero_and_deduplicate_attempts():
    records = [
        {"attempt_id": "one", "provider_cost": {"amount": 0, "currency": "CNY"}},
        {"attempt_id": "two", "provider_cost": {"amount": "0.1", "currency": "USD"}},
        {"attempt_id": "three", "provider_cost": {"amount": 0.2, "currency": "USD"}},
        {"attempt_id": "three", "provider_cost": {"amount": 0.2, "currency": "USD"}},
    ]
    before = copy.deepcopy(records)
    result = cost_summary(records, expected_calls=3)
    assert result["provider_reported"] == {"CNY": 0, "USD": 0.3}
    assert result["reported_calls"] == 3 and result["unknown_calls"] == 0 and result["complete"]
    assert not {"known_cost_usd", "estimated_cost_usd", "pricing"} & result.keys()
    assert records == before


def test_usage_and_old_estimates_do_not_become_provider_charges():
    records = [{"attempt_id": "one", "usage": {"prompt_tokens": 1000, "completion_tokens": 100},
                "cost_usd": 3, "estimated_cost_usd": 4, "_response_cost": 5}]
    result = cost_summary(records, expected_calls=2)
    assert result["provider_reported"] == {}
    assert result["reported_calls"] == 0 and result["unknown_calls"] == 2
    assert not result["complete"]


def test_partial_reported_cost_keeps_missing_attempts_unknown():
    records = [{"provider_cost": {"amount": 0, "currency": "USD"}}, {}]
    result = cost_summary(records, expected_calls=3)
    assert result["provider_reported"] == {"USD": 0}
    assert result["reported_calls"] == 1 and result["unknown_calls"] == 2
    assert not result["complete"]


@pytest.mark.parametrize("charge", [
    {"amount": -1, "currency": "USD"},
    {"amount": True, "currency": "USD"},
    {"amount": "NaN", "currency": "USD"},
    {"amount": "Infinity", "currency": "USD"},
    {"amount": 1, "currency": "usd"},
    {"amount": 1},
], ids=["negative", "boolean", "nan", "infinity", "invalid-currency", "missing-currency"])
def test_invalid_provider_charge_is_unknown(charge):
    result = cost_summary([{"provider_cost": charge}])
    assert result["provider_reported"] == {} and result["unknown_calls"] == 1
    assert result["reported_calls"] == 0 and not result["complete"]


def test_no_recorded_calls_is_not_a_confirmed_free_run():
    result = cost_summary([])
    assert result["provider_reported"] == {} and not result["complete"]
