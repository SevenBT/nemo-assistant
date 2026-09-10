"""LLM 成本计算模块。

对接用户自定义定价表和 LiteLLM 的 completion_cost()，把 token 统计转换为美元成本。

设计原则：
    1. 优先使用用户自定义定价（config/model_pricing.json）
    2. 用户未配置时回退到 LiteLLM 内置定价
    3. 都没有时返回 None（不假装知道，让上层决定怎么展示）

用户可通过编辑 config/model_pricing.json 自定义任意模型的定价。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认定价表（首次启动时写入 JSON）
_DEFAULT_PRICING = {
    "anthropic/claude-opus-4": {
        "input_per_1m": 15.0,
        "output_per_1m": 75.0,
        "cache_read_per_1m": 1.5,
        "source": "anthropic_official",
        "updated": "2024-11"
    },
    "anthropic/claude-opus-4-8": {
        "input_per_1m": 15.0,
        "output_per_1m": 75.0,
        "cache_read_per_1m": 1.5
    },
    "anthropic/claude-sonnet-4": {
        "input_per_1m": 3.0,
        "output_per_1m": 15.0,
        "cache_read_per_1m": 0.3
    },
    "anthropic/claude-sonnet-4-6": {
        "input_per_1m": 3.0,
        "output_per_1m": 15.0,
        "cache_read_per_1m": 0.3
    },
    "anthropic/claude-haiku-4": {
        "input_per_1m": 0.8,
        "output_per_1m": 4.0,
        "cache_read_per_1m": 0.08
    },
    "ollama/qwen2.5-coder": {
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "cache_read_per_1m": 0.0,
        "note": "本地模型，零成本"
    },
    "ollama/llama3.1": {
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "cache_read_per_1m": 0.0
    },
    "ollama/deepseek-coder": {
        "input_per_1m": 0.0,
        "output_per_1m": 0.0,
        "cache_read_per_1m": 0.0
    }
}

_PRICING_FILE = None  # 延迟初始化（避免导入时触发 CONFIG_DIR）
_CUSTOM_PRICING: dict[str, dict] = {}


def _get_pricing_file() -> Path:
    """延迟获取定价文件路径（避免循环导入）"""
    global _PRICING_FILE
    if _PRICING_FILE is None:
        from app.core.config import CONFIG_DIR
        _PRICING_FILE = CONFIG_DIR / "model_pricing.json"
    return _PRICING_FILE


def _load_custom_pricing() -> dict:
    """加载用户自定义定价表，不存在则创建默认配置"""
    pricing_file = _get_pricing_file()

    if not pricing_file.exists():
        pricing_file.parent.mkdir(parents=True, exist_ok=True)
        with open(pricing_file, "w", encoding="utf-8") as f:
            json.dump(_DEFAULT_PRICING, f, indent=2, ensure_ascii=False)
        logger.info(f"[CostCalc] Created default pricing config: {pricing_file}")
        return _DEFAULT_PRICING

    try:
        with open(pricing_file, "r", encoding="utf-8") as f:
            pricing = json.load(f)
        logger.info(f"[CostCalc] Loaded {len(pricing)} custom pricing entries from {pricing_file}")
        return pricing
    except Exception as e:
        logger.error(f"[CostCalc] Failed to load {pricing_file}: {e}, using defaults")
        return _DEFAULT_PRICING


def _calculate_from_custom_pricing(model_key: str, prompt_tokens: int, completion_tokens: int, cached_tokens: int) -> float | None:
    """从自定义定价表计算成本"""
    pricing = _CUSTOM_PRICING.get(model_key)
    if not pricing:
        logger.debug(f"[CostCalc] No custom pricing for '{model_key}'")
        return None

    input_cost = (prompt_tokens / 1_000_000) * pricing["input_per_1m"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output_per_1m"]
    cache_cost = (cached_tokens / 1_000_000) * pricing.get("cache_read_per_1m", 0.0)

    total = input_cost + output_cost + cache_cost
    logger.debug(
        f"[CostCalc] {model_key} (custom pricing): "
        f"{prompt_tokens}p + {completion_tokens}c + {cached_tokens}cached = ${total:.6f}"
    )
    return total


# 模块加载时初始化
def _init_pricing():
    """初始化定价表（仅在首次调用时执行）"""
    global _CUSTOM_PRICING
    if not _CUSTOM_PRICING:
        _CUSTOM_PRICING = _load_custom_pricing()


def calculate_cost(
    *,
    provider: str,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
) -> float | None:
    """计算单次 LLM 调用的美元成本。

    优先级：用户自定义定价 > LiteLLM 内置定价 > None

    Args:
        provider: 提供商（anthropic / openai / ollama / ...）
        model: 模型名（claude-sonnet-4-6 / gpt-4o / ...）
        prompt_tokens: 输入 token 数（不含缓存部分）
        completion_tokens: 输出 token 数
        cached_tokens: 缓存命中 token 数（Anthropic prompt caching）

    Returns:
        美元成本（浮点数），或 None（定价表缺失/计算失败）
    """
    _init_pricing()  # 确保定价表已加载

    if not prompt_tokens and not completion_tokens and not cached_tokens:
        return 0.0

    # 构造模型标识
    model_key = f"{provider}/{model}"
    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    cached_tokens = cached_tokens or 0

    # Layer 1: 优先使用用户自定义定价（用户配置即为准）
    custom_cost = _calculate_from_custom_pricing(model_key, prompt_tokens, completion_tokens, cached_tokens)
    if custom_cost is not None:
        return custom_cost

    # Layer 2: 回退到 LiteLLM 内置定价
    try:
        from app.core.litellm_loader import load_litellm

        ll = load_litellm()

        # LiteLLM 需要一个伪响应对象
        mock_response = type('MockResponse', (), {
            'usage': type('Usage', (), {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
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
            logger.debug(f"[CostCalc] {model_key} (LiteLLM pricing): ${cost:.6f}")
            return cost
    except Exception as e:
        logger.debug(f"[CostCalc] LiteLLM pricing lookup failed for {model_key}: {e}")

    # Layer 3: 定价表缺失
    logger.warning(f"[CostCalc] No pricing available for {model_key}, returning None")
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
