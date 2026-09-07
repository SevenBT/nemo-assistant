"""LLM 成本计算模块。

对接 LiteLLM 的 completion_cost() 和自定义定价表，把 token 统计转换为美元成本。

设计原则：
    1. 优先使用 LiteLLM 内置定价（自动跟进官方价格变更）
    2. 对 LiteLLM 不支持的模型（本地 Ollama、自定义端点）回退到自定义定价表
    3. 定价表缺失时返回 None（不假装知道，让上层决定怎么展示）
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 自定义定价表（美元/百万 token）— 只收录 LiteLLM 不支持的模型
# 格式：model_key -> (input_price_per_1M, output_price_per_1M, cache_read_price_per_1M)
_CUSTOM_PRICING: dict[str, tuple[float, float, float]] = {
    # Anthropic Claude 4.x 系列（2024-11 官方定价）
    # https://www.anthropic.com/pricing#anthropic-api
    "anthropic/claude-opus-4": (15.0, 75.0, 1.5),
    "anthropic/claude-sonnet-4": (3.0, 15.0, 0.3),
    "anthropic/claude-sonnet-4-6": (3.0, 15.0, 0.3),
    "anthropic/claude-haiku-4": (0.8, 4.0, 0.08),

    # 本地 Ollama 模型（零成本）
    "ollama/qwen2.5-coder": (0.0, 0.0, 0.0),
    "ollama/llama3.1": (0.0, 0.0, 0.0),
    "ollama/deepseek-coder": (0.0, 0.0, 0.0),
    # 其他自定义端点可在此添加
}


def calculate_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> float | None:
    """计算单次 LLM 调用的美元成本。

    Args:
        provider: 提供商（anthropic / openai / ollama / ...）
        model: 模型名（claude-sonnet-4-6 / gpt-4o / ...）
        prompt_tokens: 输入 token 数（不含缓存部分）
        completion_tokens: 输出 token 数
        cached_tokens: 缓存命中 token 数（Anthropic prompt caching）

    Returns:
        美元成本（浮点数），或 None（定价表缺失/计算失败）
    """
    if not prompt_tokens and not completion_tokens and not cached_tokens:
        return 0.0

    # 构造 LiteLLM 识别的模型标识
    model_key = f"{provider}/{model}"

    # 先尝试 LiteLLM 内置定价
    try:
        from app.core.litellm_loader import load_litellm

        ll = load_litellm()

        # LiteLLM 需要一个伪响应对象
        mock_response = type('MockResponse', (), {
            'usage': type('Usage', (), {
                'prompt_tokens': prompt_tokens or 0,
                'completion_tokens': completion_tokens or 0,
                'total_tokens': (prompt_tokens or 0) + (completion_tokens or 0),
            })(),
            'model': model_key,
            '_hidden_params': {
                'model': model_key,
                'custom_llm_provider': provider,
            }
        })()

        # 添加 cached_tokens 如果存在
        if cached_tokens:
            mock_response.usage.prompt_tokens_details = type('Details', (), {
                'cached_tokens': cached_tokens
            })()

        cost = ll.completion_cost(completion_response=mock_response)
        if cost > 0:
            return cost
    except Exception as e:
        logger.debug(f"[CostCalculator] LiteLLM pricing lookup failed for {model_key}: {e}")

    # 回退到自定义定价表
    if model_key in _CUSTOM_PRICING:
        input_price, output_price, cache_price = _CUSTOM_PRICING[model_key]

        # 计算各部分成本（价格单位是每百万 token，需要 /1e6）
        input_cost = (prompt_tokens or 0) * input_price / 1_000_000
        output_cost = (completion_tokens or 0) * output_price / 1_000_000
        cache_cost = (cached_tokens or 0) * cache_price / 1_000_000

        return input_cost + output_cost + cache_cost

    # 定价表缺失
    logger.warning(f"[CostCalculator] No pricing available for {model_key}")
    return None


def calculate_cost_from_usage(
    *,
    provider: str,
    model: str,
    usage: dict[str, int | None] | None,
) -> float | None:
    """从标准 usage 字典计算成本。

    Args:
        provider: 提供商
        model: 模型名
        usage: 包含 prompt_tokens / completion_tokens / cached_tokens 的字典

    Returns:
        美元成本，或 None
    """
    if not usage:
        return None

    return calculate_cost(
        provider=provider,
        model=model,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        cached_tokens=usage.get("cached_tokens"),
    )
