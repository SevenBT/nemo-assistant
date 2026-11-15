"""
Consolidator — 对话 token 超限时自动压缩旧消息为摘要。

工作流程：
  1. 桌面请求准备器按文本 token 估算检查请求视图
  2. 超过阈值时，取最旧的一批消息
  3. 调用 LLM 生成摘要
  4. 摘要存入 memories 表 (category=archive)
  5. 请求视图使用摘要和完整近期消息；不删除会话或 Agent 权威历史

maybe_consolidate 保留为旧调用方的列表转换接口；桌面使用每次运行独立的
ConsolidatingRequestPreparer，负责固定指令、工具组及摘要归档去重。
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.conversation.context_manager import MAX_CONSOLIDATION_RATIO, ContextManager, content_to_text
from app.models.memory import MemoryCategory, MemoryScope
from app.agent.request_context import RequestCancelled, check_cancelled
from app.runtime.cancellation import CancellationToken, _close_resource

if TYPE_CHECKING:
    from app.llm.llm_gateway import LLMGateway
    from app.storage.memory_manager import MemoryManager
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
    """将正文和工具参数转为有长度限制的摘要素材，隐藏图片载荷。"""
    lines = []
    for m in messages:
        role_label = {"user": "用户", "assistant": "AI", "system": "系统"}.get(m.role, m.role)
        content = content_to_text(m.content)
        if content:
            lines.append(f"{role_label}: {content[:500]}")
        for call in getattr(m, "tool_calls", None) or []:
            lines.append(f"工具 {call.name}: {str(call.arguments)[:500]}")
    return "\n".join(lines)


class Consolidator:
    """对话压缩器，token 超限时自动摘要旧消息。"""

    def __init__(
        self,
        llm_gateway: "LLMGateway",
        memory_mgr: "MemoryManager",
        model: str = "default",
        consolidation_ratio: float = MAX_CONSOLIDATION_RATIO,
    ):
        """
        Args:
            llm_gateway: LLM 网关
            memory_mgr: 记忆管理器
            model: 模型名称（用于确定上下文窗口和 encoding）
            consolidation_ratio: 摘要和保留消息占模型总上下文的比例（默认且最多 10%）
        """
        self._llm = llm_gateway
        self._mem = memory_mgr
        self._ratio = consolidation_ratio
        self._ctx_mgr = ContextManager(model=model, reserve_ratio=0.2)
        self._ctx_mgr.consolidation_budget(consolidation_ratio)

    @property
    def context_manager(self) -> ContextManager:
        return self._ctx_mgr

    @property
    def target_tokens(self) -> int:
        return self._ctx_mgr.consolidation_budget(self._ratio)

    def archive(self, summary: str, session_id: str, cancel_token: CancellationToken) -> None:
        check_cancelled(cancel_token)
        self._mem.add(
            content=summary, category=MemoryCategory.ARCHIVE, scope=MemoryScope.SESSION,
            session_id=session_id, importance=3, source="consolidator",
        )

    def summarize(self, messages: list["Message"], max_tokens: int,
                  cancel_token: CancellationToken) -> str:
        return self._summarize(messages, max_tokens, cancel_token=cancel_token)

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

        # 总预算包含摘要；先为摘要预留 20%，其余用于完整的近期消息。
        target_tokens = self._ctx_mgr.consolidation_budget(self._ratio)
        summary_budget = max(1, target_tokens // 5)
        keep_count = self._ctx_mgr.calculate_keep_count(
            messages,
            target_ratio=self._ratio,
            min_keep=4,
            reserved_tokens=summary_budget,
        )

        if keep_count >= len(messages):
            return messages

        to_compress = messages[: len(messages) - keep_count]
        to_keep = messages[len(messages) - keep_count:]

        # 调用 LLM 生成摘要
        summary_prefix = "[以下是之前对话的摘要]\n"
        available = max(0, target_tokens - self._ctx_mgr.count_messages_tokens(to_keep) - 1)
        summary = self._summarize(
            to_compress,
            max_tokens=max(1, available - self._ctx_mgr.count_tokens(summary_prefix)),
        )

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
            content=summary_prefix + summary,
            timestamp=time.time(),
        )
        # LLM 和 raw fallback 都可能超过提示词要求；将摘要标签和分隔符
        # 一并计数后强制执行预算。超大的近期消息也会进入摘要，而非越界保留。
        summary_msg.content = self._ctx_mgr.truncate_text(summary_msg.content, available)
        result = [summary_msg] + to_keep
        while self._ctx_mgr.count_messages_tokens(result) > target_tokens:
            available -= 1
            summary_msg.content = self._ctx_mgr.truncate_text(summary_msg.content, available)
        return result

    def _summarize(self, messages: list["Message"], max_tokens: int,
                   cancel_token: CancellationToken | None = None) -> str:
        """调用 LLM 生成摘要。失败时返回 raw 截断。"""
        text = _messages_to_text(messages)
        prompt = f"摘要正文不得超过 {max_tokens} tokens。\n\n" + _CONSOLIDATION_PROMPT + text

        stream = None
        try:
            check_cancelled(cancel_token)
            result_parts = []
            stream = self._llm.chat_stream(
                [{"role": "user", "content": prompt}],
                tools=None,
                cancel_token=cancel_token,
            )
            for event in stream:
                check_cancelled(cancel_token)
                if event["type"] == "text":
                    result_parts.append(event["delta"])
                elif event["type"] == "error":
                    raise RuntimeError(event["message"])
            check_cancelled(cancel_token)
            summary = "".join(result_parts).strip()
            if summary:
                return summary
        except RequestCancelled:
            raise
        except Exception as e:
            check_cancelled(cancel_token)
            logger.warning(f"[Consolidator] LLM summarization failed: {e}, using raw truncation")
        finally:
            _close_resource(stream)

        # fallback: 取每条消息的前 100 字符
        lines = []
        for m in messages:
            if m.content:
                lines.append(f"- {content_to_text(m.content)[:100]}")
            for call in getattr(m, "tool_calls", None) or []:
                lines.append(f"- {call.name}: {str(call.arguments)[:100]}")
        return "\n".join(lines[-20:])
