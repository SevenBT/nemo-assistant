#!/usr/bin/env python
"""Test LiteLLM cost calculation capability."""
from app.core.litellm_loader import load_litellm

ll = load_litellm()

# Test cost calculation
cost = ll.completion_cost(
    model='anthropic/claude-sonnet-4-6',
    prompt_tokens=1000,
    completion_tokens=500
)
print(f'Cost for 1000 prompt + 500 completion: ${cost:.6f}')

# Test with cached tokens
cost_cached = ll.completion_cost(
    model='anthropic/claude-sonnet-4-6',
    prompt_tokens=1000,
    completion_tokens=500,
    prompt_tokens_details={'cached_tokens': 800}
)
print(f'Cost with 800 cached: ${cost_cached:.6f}')
