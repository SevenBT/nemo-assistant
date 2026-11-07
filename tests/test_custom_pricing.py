"""用户自定义模型定价测试，不修改真实配置目录。"""
from __future__ import annotations

import json

import pytest

from app.core import cost_calculator


@pytest.fixture
def custom_pricing(tmp_path, monkeypatch):
    pricing_file = tmp_path / "model_pricing.json"
    pricing_file.write_text(
        json.dumps(
            {
                "custom/my-model": {
                    "input_per_1m": 1.0,
                    "output_per_1m": 2.0,
                    "cache_read_per_1m": 0.1,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cost_calculator, "_PRICING_FILE", pricing_file)
    monkeypatch.setattr(cost_calculator, "_CUSTOM_PRICING", {})
    return pricing_file


def test_user_override_is_loaded(custom_pricing):
    cost = cost_calculator.calculate_cost(
        provider="custom",
        model="my-model",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
        cached_tokens=1_000_000,
    )

    # $1 input + $1 output + $0.1 cache
    assert cost == pytest.approx(2.1)


def test_unknown_model_without_custom_price_returns_none(custom_pricing, monkeypatch):
    from app.core import litellm_loader

    def fail_loader():
        raise RuntimeError("no fallback pricing in this test")

    monkeypatch.setattr(litellm_loader, "load_litellm", fail_loader)

    cost = cost_calculator.calculate_cost(
        provider="custom",
        model="unknown-model",
        prompt_tokens=100,
        completion_tokens=50,
    )

    assert cost is None
