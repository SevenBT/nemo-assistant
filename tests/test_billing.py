import pytest

from app.llm.billing import billing_url_for, normalize_provider_cost, validate_billing_url


@pytest.mark.parametrize("value", [None, {}, {"amount": True, "currency": "USD"},
    {"amount": -1, "currency": "USD"}, {"amount": "nan", "currency": "USD"},
    {"amount": float("inf"), "currency": "USD"}, {"amount": "bad", "currency": "USD"},
    {"amount": 0.1}, {"amount": 0.1, "currency": "<script>"}, {"amount": 1, "currency": "usd"}])
def test_untrusted_or_incomplete_charge_is_unknown(value):
    assert normalize_provider_cost(value) is None


def test_explicit_zero_is_valid_and_currency_is_preserved():
    assert normalize_provider_cost({"amount": 0, "currency": "CNY"}) == {"amount": 0, "currency": "CNY"}
    assert normalize_provider_cost({"amount": "0.001", "currency": "USD"}) == {"amount": 0.001, "currency": "USD"}


@pytest.mark.parametrize("endpoint", ["https://proxy.example/v1", "https://api.deepseek.com.evil/v1",
    "https://api.deepseek.com@evil.example/v1", "http://api.deepseek.com", "https://api.deepseek.com:8443",
    "https://secret@api.deepseek.com", "https://api.deepseek.com:bad", "https://["])
def test_custom_or_invalid_endpoints_do_not_link_official_billing(endpoint):
    assert billing_url_for("deepseek", endpoint) is None


def test_official_link_is_allowlisted_without_returning_endpoint_secrets():
    expected = "https://platform.deepseek.com/"
    assert billing_url_for("deepseek", "https://api.deepseek.com/beta?api_key=PRIVATE") == expected
    assert billing_url_for("deepseek") == expected
    assert billing_url_for("unknown") is None
    assert validate_billing_url("deepseek", "https://evil.example") is None
    assert validate_billing_url("deepseek", expected) == expected
    assert validate_billing_url("openai", expected) is None
