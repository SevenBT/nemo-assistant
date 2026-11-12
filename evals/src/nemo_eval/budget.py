"""Request/output reservations and provider-reported charges; no price estimates."""
from decimal import Decimal, InvalidOperation
import math
import re


def validate_config(config):
    allowed = {'language', 'target', 'judge', 'budget'}
    if set(config) - allowed:
        raise ValueError('Unknown run configuration fields')
    profile_allowed = {'model', 'provider', 'base_url', 'api_protocol', 'api_key_env', 'max_tokens', 'temperature', 'top_p', 'max_attempts', 'timeout_seconds'}
    for name in ('target', 'judge'):
        if name not in config:
            continue
        profile = config[name]
        if 'pricing' in profile:
            raise ValueError('Local pricing estimates are no longer supported; remove pricing and consult provider billing')
        if profile.get('api_protocol', 'auto') not in ('auto', 'openai_chat', 'responses', 'anthropic_messages', 'cohere_chat'):
            raise ValueError('Unsupported API protocol')
        if set(profile) - profile_allowed:
            raise ValueError(f'Unknown {name} profile field; inline credentials are forbidden')
        if not profile.get('model') or not profile.get('api_key_env'):
            raise ValueError(f'Explicit model and api_key_env required for {name}')
        if profile.get('max_attempts', 1) != 1:
            raise ValueError('First release requires one provider attempt per budgeted request')
        if isinstance(profile.get('max_tokens', 1024), bool) or not isinstance(profile.get('max_tokens', 1024), int) or profile.get('max_tokens', 1024) <= 0:
            raise ValueError('max_tokens must be positive')
        for key in ('temperature', 'top_p', 'timeout_seconds'):
            value = profile.get(key, {'temperature': 0, 'top_p': 1, 'timeout_seconds': 60}[key])
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (key == 'timeout_seconds' and value == 0):
                raise ValueError(f'Invalid {key}')
    budget = config.get('budget', {})
    if set(budget) - {'max_model_calls', 'max_output_tokens'}:
        raise ValueError('Unsupported budget field')
    for key, value in budget.items():
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f'{key} must be a positive integer')
    return config


class Budget:
    def __init__(self, config):
        self.limit = config.get('budget', {})
        self.calls = 0
        self.output_reserved = 0

    def reserve(self, profile):
        output = profile.get('max_tokens', 1024)
        if self.calls + 1 > self.limit.get('max_model_calls', 20):
            raise ValueError('Model call budget exhausted')
        if self.output_reserved + output > self.limit.get('max_output_tokens', 20480):
            raise ValueError('Output token reservation budget exhausted')
        self.calls += 1
        self.output_reserved += output


def cost_summary(records, *, expected_calls=None):
    """Sum explicit charges by currency; missing charges never imply free calls."""
    unknown = 0
    seen = set()
    provider_reported = {}
    recorded = 0
    for record in records:
        ident = record.get('attempt_id')
        if ident and ident in seen:
            continue
        seen.add(ident)
        recorded += 1
        charge = record.get('provider_cost')
        amount = charge.get('amount') if isinstance(charge, dict) else None
        currency = charge.get('currency') if isinstance(charge, dict) else None
        if (isinstance(amount, bool) or not isinstance(amount, (int, float, str, Decimal))
                or not isinstance(currency, str) or not re.fullmatch(r'[A-Z]{3}', currency)):
            unknown += 1
            continue
        try:
            amount = Decimal(str(amount))
            if not amount.is_finite() or amount < 0 or not math.isfinite(float(amount)):
                raise ValueError('Invalid provider charge')
        except (InvalidOperation, ValueError, OverflowError):
            unknown += 1
            continue
        provider_reported[currency] = provider_reported.get(currency, Decimal(0)) + amount
    reported = recorded - unknown
    unobserved = max(0, (expected_calls or 0) - recorded)
    unknown += unobserved
    return {'provider_reported': {currency: float(amount) for currency, amount in provider_reported.items()},
            'reported_calls': reported, 'unknown_calls': unknown,
            'complete': recorded > 0 and unknown == 0,
            'scope': 'Provider-reported charges for recorded attempts only; consult provider billing'}
