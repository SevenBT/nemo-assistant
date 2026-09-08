"""
Consolidator — 对话 token 超限时自动压缩旧消息为摘要。

工作流程：
  1. 每轮对话前检查当前 session 消息的 token 精确计数（使用 tiktoken）
  2. 超过阈值时，取最旧的一批消息
  3. 调用 LLM 生成摘要
  4. 摘要存入 memories 表 (category=archive)
  5. 从 session 消息列表中移除已压缩的消息，替换为摘要系统消息
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.core.context_manager import ContextManager
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


def _messages_to_text(messages: list["Message"]) -> str:
    """将消息列表转为纯文本用于摘要（不包含 tool_calls，避免摘要过长）。"""
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
        model: str = "default",
        consolidation_ratio: float = 0.5,
    ):
        """
        Args:
            llm_gateway: LLM 网关
            memory_mgr: 记忆管理器
            model: 模型名称（用于确定上下文窗口和 encoding）
            consolidation_ratio: 压缩后的目标 token 占比（默认 50%）
        """
        self._llm = llm_gateway
        self._mem = memory_mgr
        self._ratio = consolidation_ratio
        self._ctx_mgr = ContextManager(model=model, reserve_ratio=0.2)

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
        # 使用 ContextManager 判断是否需要压缩
        if not self._ctx_mgr.should_consolidate(messages, threshold_ratio=0.7):
            return messages

        current_tokens = self._ctx_mgr.count_messages_tokens(messages)
        logger.info(f"[Consolidator] Token count {current_tokens} exceeds threshold, starting consolidation")

        # 计算需要保留多少消息（目标：压缩到 50%）
        keep_count = self._ctx_mgr.calculate_keep_count(
            messages,
            target_ratio=self._ratio,
            min_keep=4,
        )

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
            f"[Consolidator] Compressed {len(to_compress)} messages → summary {len(summary)} chars, "
            f"keeping {len(to_keep)} messages"
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
            logger.warning(f"[Consolidator] LLM summarization failed: {e}, using raw truncation")

        # fallback: 取每条消息的前 100 字符
        lines = []
        for m in messages:
            if m.content:
                lines.append(f"- {m.content[:100]}")
        return "\n".join(lines[-20:])
