"""
ContextManager — 精确的 token 计数和上下文窗口管理。

替代 consolidator.py 中的字符启发式估算，使用 tiktoken 进行精确计数。
支持动态上下文窗口管理（从模型 metadata 读取真实窗口大小）。
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import tiktoken

if TYPE_CHECKING:
    from app.models.message import Message

logger = logging.getLogger(__name__)

# 模型到 tiktoken encoding 的映射
_MODEL_ENCODING_MAP = {
    # OpenAI models
    "gpt-4": "cl100k_base",
    "gpt-4-turbo": "cl100k_base",
    "gpt-4o": "o200k_base",
    "gpt-3.5-turbo": "cl100k_base",
    # Anthropic models (use cl100k_base as approximation)
    "claude-3": "cl100k_base",
    "claude-3.5": "cl100k_base",
    "claude-4": "cl100k_base",
    # Default fallback
    "default": "cl100k_base",
}

# 模型到上下文窗口的映射（单位：tokens）
_MODEL_CONTEXT_WINDOW = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4-32k": 32768,
    "gpt-4": 8192,
    "gpt-3.5-turbo-16k": 16385,
    "gpt-3.5-turbo": 16385,
    # Anthropic Claude 3.x
    "claude-3-opus": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3.5-sonnet": 200000,
    # Anthropic Claude 4.x
    "claude-4-opus": 200000,
    "claude-4-sonnet": 200000,
    "claude-4-haiku": 200000,
    # DeepSeek
    "deepseek-v4": 128000,
    "deepseek-chat": 32000,
    # Default fallback
    "default": 128000,
}


def get_encoding_for_model(model: str) -> tiktoken.Encoding:
    """
    获取模型对应的 tiktoken encoding。

    Args:
        model: 模型名称（如 "gpt-4-turbo", "claude-3.5-sonnet"）

    Returns:
        tiktoken.Encoding 实例
    """
    # 模型名称前缀匹配
    encoding_name = _MODEL_ENCODING_MAP.get("default")
    for prefix, enc in _MODEL_ENCODING_MAP.items():
        if model.startswith(prefix):
            encoding_name = enc
            break

    try:
        return tiktoken.get_encoding(encoding_name)
    except Exception as e:
        logger.warning(f"[ContextManager] Failed to load encoding {encoding_name}: {e}, using cl100k_base")
        return tiktoken.get_encoding("cl100k_base")


def get_context_window_for_model(model: str) -> int:
    """
    获取模型的上下文窗口大小。

    Args:
        model: 模型名称

    Returns:
        上下文窗口大小（tokens）
    """
    window = _MODEL_CONTEXT_WINDOW.get("default")
    for prefix, size in _MODEL_CONTEXT_WINDOW.items():
        if model.startswith(prefix):
            window = size
            break

    logger.debug(f"[ContextManager] Model '{model}' context window: {window} tokens")
    return window


def count_tokens(text: str, model: str = "default") -> int:
    """
    精确计算文本的 token 数量。

    Args:
        text: 要计数的文本
        model: 模型名称（用于选择正确的 encoding）

    Returns:
        token 数量
    """
    if not text:
        return 0

    encoding = get_encoding_for_model(model)
    try:
        tokens = encoding.encode(text)
        return len(tokens)
    except Exception as e:
        logger.warning(f"[ContextManager] Token counting failed: {e}, fallback to char/4")
        # Fallback to character-based estimation
        return len(text) // 4


def message_to_token_text(m: "Message") -> str:
    """
    提取单条消息用于 token 计数的全部文本。

    包含：
    - message.content
    - tool_calls 的 arguments
    - tool_calls 的 result

    Args:
        m: Message 对象

    Returns:
        用于计数的完整文本
    """
    parts = [m.content or ""]

    # 包含 tool_calls 的参数和结果
    for tc in getattr(m, "tool_calls", None) or []:
        args = getattr(tc, "arguments", None)
        result = getattr(tc, "result", None)
        if args:
            parts.append(json.dumps(args, ensure_ascii=False))
        if result:
            parts.append(json.dumps(result, ensure_ascii=False))

    return "\n".join(p for p in parts if p)


def count_messages_tokens(messages: list["Message"], model: str = "default") -> int:
    """
    计算一组消息的总 token 数量。

    Args:
        messages: Message 列表
        model: 模型名称

    Returns:
        总 token 数量
    """
    total_text = "\n".join(message_to_token_text(m) for m in messages)
    return count_tokens(total_text, model)


class ContextManager:
    """
    上下文窗口管理器。

    职责：
    1. 精确计算消息的 token 数量（使用 tiktoken）
    2. 根据模型动态设置上下文窗口阈值
    3. 判断是否需要压缩旧消息
    """

    def __init__(self, model: str = "default", reserve_ratio: float = 0.2):
        """
        Args:
            model: 模型名称（用于确定 encoding 和窗口大小）
            reserve_ratio: 为 completion 保留的窗口比例（默认 20%）
        """
        self.model = model
        self.reserve_ratio = reserve_ratio
        self._encoding = get_encoding_for_model(model)
        self._max_context = get_context_window_for_model(model)

        # 实际可用窗口 = 总窗口 - 保留给 completion 的部分
        self._usable_context = int(self._max_context * (1 - reserve_ratio))

        logger.info(
            f"[ContextManager] Initialized for model '{model}': "
            f"max={self._max_context}, usable={self._usable_context}, "
            f"reserve={int(self._max_context * reserve_ratio)} tokens"
        )

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数量。"""
        return count_tokens(text, self.model)

    def count_messages_tokens(self, messages: list["Message"]) -> int:
        """计算一组消息的 token 数量。"""
        return count_messages_tokens(messages, self.model)

    def should_consolidate(self, messages: list["Message"], threshold_ratio: float = 0.7) -> bool:
        """
        判断是否需要压缩消息。

        Args:
            messages: 当前消息列表
            threshold_ratio: 触发压缩的阈值比例（默认 70%）

        Returns:
            True 如果需要压缩
        """
        current_tokens = self.count_messages_tokens(messages)
        threshold = int(self._usable_context * threshold_ratio)

        if current_tokens > threshold:
            logger.info(
                f"[ContextManager] Token count {current_tokens} exceeds threshold {threshold} "
                f"({threshold_ratio*100:.0f}% of {self._usable_context})"
            )
            return True

        return False

    def calculate_keep_count(
        self,
        messages: list["Message"],
        target_ratio: float = 0.5,
        min_keep: int = 4,
    ) -> int:
        """
        计算需要保留多少条最近的消息。

        Args:
            messages: 消息列表
            target_ratio: 压缩后的目标 token 占比（默认 50%）
            min_keep: 最少保留的消息数（默认 4）

        Returns:
            应该保留的消息数量
        """
        target_tokens = int(self._usable_context * target_ratio)

        # 从后往前累加，找到第一个超过 target 的位置
        running_tokens = 0
        for i in range(len(messages) - 1, -1, -1):
            msg_text = message_to_token_text(messages[i])
            msg_tokens = self.count_tokens(msg_text)
            running_tokens += msg_tokens

            if running_tokens >= target_tokens:
                keep_count = len(messages) - i
                return max(keep_count, min_keep)

        # 如果全部消息都不超过 target，保留全部
        return max(len(messages), min_keep)
