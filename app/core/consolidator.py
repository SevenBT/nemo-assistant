"""
Consolidator — 对话 token 超限时自动压缩旧消息为摘要。

工作流程：
  1. 每轮对话前检查当前 session 消息的 token 估算值
  2. 超过阈值时，取最旧的一批消息
  3. 调用 LLM 生成摘要
  4. 摘要存入 memories 表 (category=archive)
  5. 从 session 消息列表中移除已压缩的消息，替换为摘要系统消息
"""
from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from app.models.memory import MemoryCategory, MemoryScope

if TYPE_CHECKING:
    from app.core.llm_gateway import LLMGateway
    from app.core.memory_manager import MemoryManager
    from app.models.message import Message

logger = logging.getLogger(__name__)

# 压缩提示词
_CONSOLIDATION_PROMPT = """你是对话摘要助手。请将以下对话内容压缩为简洁的要点摘要。

要求：
- 保留关键信息：用户的需求、做出的决策、重要的事实
- 丢弃寒暄、重复内容、中间调试过程
- 用中文bullet point格式输出
- 控制在原文 20% 的篇幅内

对话内容：
"""


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文约 1.5 字/token，英文约 4 字符/token。"""
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def _message_token_text(m: "Message") -> str:
    """单条消息用于 token 估算的全部文本：含 content + tool_calls(参数+结果)。

    仅用 m.content 会严重低估 —— assistant 的 tool_calls(arguments)、tool 角色的
    结果 JSON 往往体量很大，漏算会导致压缩触发过晚、实际超出上下文窗口。
    """
    parts = [m.content or ""]
    for tc in getattr(m, "tool_calls", None) or []:
        args = getattr(tc, "arguments", None)
        result = getattr(tc, "result", None)
        if args:
            parts.append(json.dumps(args, ensure_ascii=False))
        if result:
            parts.append(json.dumps(result, ensure_ascii=False))
    return "\n".join(p for p in parts if p)


def _estimate_messages_tokens(messages: list["Message"]) -> int:
    """估算整段消息的 token 总量（含 tool_calls）。"""
    return _estimate_tokens("\n".join(_message_token_text(m) for m in messages))


def _messages_to_text(messages: list["Message"]) -> str:
    """将消息列表转为纯文本用于摘要。"""
    lines = []
    for m in messages:
        role_label = {"user": "用户", "assistant": "AI", "system": "系统"}.get(m.role, m.role)
        if m.content:
            lines.append(f"{role_label}: {m.content[:500]}")
    return "\n".join(lines)


class Consolidator:
    """对话压缩器，token 超限时自动摘要旧消息。"""

    def __init__(
        self,
        llm_gateway: "LLMGateway",
        memory_mgr: "MemoryManager",
        max_context_tokens: int = 60000,
        consolidation_ratio: float = 0.5,
    ):
        self._llm = llm_gateway
        self._mem = memory_mgr
        self._max_tokens = max_context_tokens
        self._ratio = consolidation_ratio  # 压缩后目标占比

    def maybe_consolidate(
        self,
        messages: list["Message"],
        session_id: str,
    ) -> list["Message"]:
        """
        检查并执行压缩。返回处理后的消息列表（可能被截短）。

        如果不需要压缩，原样返回。
        如果压缩成功，返回 [摘要系统消息] + 保留的近期消息。
        如果 LLM 调用失败，做 raw 截断。
        """
        estimated_tokens = _estimate_messages_tokens(messages)

        threshold = int(self._max_tokens * 0.7)
        if estimated_tokens <= threshold:
            return messages

        logger.info(
            f"[Consolidator] token 估算 {estimated_tokens} > 阈值 {threshold}，开始压缩"
        )

        # 计算需要保留多少消息（目标：压缩到 50%）
        target_tokens = int(self._max_tokens * self._ratio)
        keep_count = len(messages)
        running_tokens = estimated_tokens
        for i, m in enumerate(messages):
            msg_tokens = _estimate_tokens(_message_token_text(m))
            running_tokens -= msg_tokens
            if running_tokens <= target_tokens:
                keep_count = len(messages) - i - 1
                break

        # 至少保留最近 4 条消息
        keep_count = max(keep_count, 4)
        if keep_count >= len(messages):
            return messages

        to_compress = messages[: len(messages) - keep_count]
        to_keep = messages[len(messages) - keep_count:]

        # 调用 LLM 生成摘要
        summary = self._summarize(to_compress)

        # 存入 memories 表
        self._mem.add(
            content=summary,
            category=MemoryCategory.ARCHIVE,
            scope=MemoryScope.SESSION,
            session_id=session_id,
            importance=3,
            source="consolidator",
        )

        logger.info(
            f"[Consolidator] 压缩 {len(to_compress)} 条消息 → 摘要 {len(summary)} 字符，"
            f"保留 {len(to_keep)} 条"
        )

        # 构造摘要消息插入到保留消息前面
        from app.models.message import Message, MessageRole
        summary_msg = Message(
            role=MessageRole.SYSTEM,
            content=f"[以下是之前对话的摘要]\n{summary}",
            timestamp=time.time(),
        )
        return [summary_msg] + to_keep

    def _summarize(self, messages: list["Message"]) -> str:
        """调用 LLM 生成摘要。失败时返回 raw 截断。"""
        text = _messages_to_text(messages)
        prompt = _CONSOLIDATION_PROMPT + text

        try:
            result_parts = []
            for event in self._llm.chat_stream(
                [{"role": "user", "content": prompt}],
                tools=None,
            ):
                if event["type"] == "text":
                    result_parts.append(event["delta"])
                elif event["type"] == "error":
                    raise RuntimeError(event["message"])
            summary = "".join(result_parts).strip()
            if summary:
                return summary
        except Exception as e:
            logger.warning(f"[Consolidator] LLM 摘要失败: {e}，使用 raw 截断")

        # fallback: 取每条消息的前 100 字符
        lines = []
        for m in messages:
            if m.content:
                lines.append(f"- {m.content[:100]}")
        return "\n".join(lines[-20:])
