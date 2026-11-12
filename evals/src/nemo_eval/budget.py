"""Conservative request/output reservations and explicit cost completeness."""
import math


def validate_config(config):
    allowed = {'language', 'target', 'judge', 'budget'}
    if set(config) - allowed:
        raise ValueError('Unknown run configuration fields')
    profile_allowed = {'model', 'provider', 'base_url', 'api_key_env', 'max_tokens', 'temperature', 'top_p', 'max_attempts', 'timeout_seconds', 'pricing'}
    for name in ('target', 'judge'):
        if name not in config:
            continue
        profile = config[name]
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
        if profile.get('pricing'):
            if set(profile['pricing']) - {'input_per_1m', 'output_per_1m', 'cache_read_per_1m'} or not {'input_per_1m', 'output_per_1m'} <= set(profile['pricing']):
                raise ValueError('Pricing requires explicit input_per_1m and output_per_1m')
            for key in ('input_per_1m', 'output_per_1m', 'cache_read_per_1m'):
                value = profile['pricing'].get(key, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    raise ValueError('Invalid explicit pricing')
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


def cost_summary(records, profile):
    pricing = profile.get('pricing')
    known, unknown = 0.0, 0
    seen = set()
    for record in records:
        ident = record.get('attempt_id')
        if ident and ident in seen:
            continue
        seen.add(ident)
        usage = record.get('usage')
        if not pricing or not usage or usage.get('prompt_tokens') is None or usage.get('completion_tokens') is None:
            unknown += 1
            continue
        cached = usage.get('cached_tokens', 0) or 0
        cost = (max(0, usage['prompt_tokens'] - cached) * pricing['input_per_1m'] + usage['completion_tokens'] * pricing['output_per_1m'] + cached * pricing.get('cache_read_per_1m', pricing['input_per_1m'])) / 1_000_000
        record['estimated_cost_usd'] = cost
        known += cost
    return {'known_cost_usd': known, 'unknown_calls': unknown, 'complete': bool(records) and unknown == 0, 'pricing': pricing, 'scope': 'Explicit linked model attempts only'}
