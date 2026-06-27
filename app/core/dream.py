"""
Dream — 定时 LLM 代理，从对话摘要中提取结构化长期记忆。

工作流程：
  1. 读取未处理的 archive 记忆（Consolidator 生成的对话摘要）
  2. 连同现有全局记忆一起发给 LLM
  3. LLM 输出结构化指令（ADD / UPDATE / DELETE）
  4. 执行指令，更新 memories 表
  5. 标记已处理的 archive
"""
from __future__ import annotations

import json
import logging
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from app.models.memory import MemoryCategory, MemoryScope

if TYPE_CHECKING:
    from app.core.llm_gateway import LLMGateway
    from app.core.memory_manager import MemoryManager

logger = logging.getLogger(__name__)

# ADD 查重阈值：同 category 内 content 相似度超过此值视为重复，跳过新增
_DEDUP_THRESHOLD = 0.85

_DREAM_PROMPT = """你是记忆管理员。你的任务是从对话摘要中提取值得长期记住的信息，并管理已有记忆。

## 已有记忆

{existing_memories}

## 待处理的对话摘要

{archives}

## 输出规则

分析对话摘要，输出 JSON 数组，每个元素是一条指令：

```json
[
  {{"action": "ADD", "content": "记忆内容", "category": "分类", "importance": 5}},
  {{"action": "UPDATE", "id": 123, "content": "更新后的内容", "importance": 7}},
  {{"action": "DELETE", "id": 456, "reason": "已过时"}}
]
```

## 分类说明

- personality: AI 应该如何表现（语气、风格）— 极少新增
- user: 用户的身份、偏好、习惯
- project: 项目决策、技术选型、架构约定
- fact: 具体事实（文件位置、配置方式、部署流程等）

## 重要性评分 (1-10)

- 1-3: 临时性信息，可能很快过时
- 4-6: 一般性事实和偏好
- 7-9: 核心决策和重要约束
- 10: 绝对不能忘记的关键信息

## 注意事项

- 如果新信息与已有记忆冲突，输出 UPDATE 覆盖旧的
- 如果已有记忆明显过时或被否定，输出 DELETE
- 不要重复已有记忆的内容
- 如果没有值得提取的新信息，输出空数组 []
- 只输出 JSON 数组，不要输出其他内容
"""


class Dream:
    """定时记忆提取代理。"""

    def __init__(self, llm_gateway: "LLMGateway", memory_mgr: "MemoryManager"):
        self._llm = llm_gateway
        self._mem = memory_mgr

    def run(self) -> bool:
        """
        执行一次 Dream 处理。

        Returns:
            True 如果有工作被完成，False 如果没有待处理内容。
        """
        archives = self._mem.get_unprocessed_archives()
        if not archives:
            return False

        logger.info(f"[Dream] 开始处理 {len(archives)} 条未处理摘要")

        # 构建 prompt
        existing = self._mem.get_global()
        existing_text = self._format_existing(existing)
        archives_text = self._format_archives(archives)

        prompt = _DREAM_PROMPT.format(
            existing_memories=existing_text or "（暂无）",
            archives=archives_text,
        )

        # 调用 LLM
        try:
            response = self._call_llm(prompt)
            directives = self._parse_response(response)
            self._execute_directives(directives, existing)
        except Exception as e:
            logger.error(f"[Dream] 处理失败: {e}")
            return False

        # 标记已处理
        archive_ids = [a.id for a in archives]
        self._mem.mark_archives_processed(archive_ids)
        # 清理已提炼且超过保留期的 archive，避免 memories 表膨胀
        purged = self._mem.purge_processed_archives()
        logger.info(f"[Dream] 完成，处理了 {len(archives)} 条摘要，清理 {purged} 条旧 archive")
        return True

    def _format_existing(self, memories) -> str:
        lines = []
        for m in memories:
            lines.append(f"- [id={m.id}] [{m.category}] (重要性:{m.importance}) {m.content}")
        return "\n".join(lines)

    def _format_archives(self, archives) -> str:
        lines = []
        for a in archives:
            lines.append(f"---\n{a.content}")
        return "\n".join(lines)

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM 获取完整响应。"""
        parts = []
        for event in self._llm.chat_stream(
            [{"role": "user", "content": prompt}],
            tools=None,
        ):
            if event["type"] == "text":
                parts.append(event["delta"])
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return "".join(parts).strip()

    def _parse_response(self, response: str) -> list[dict]:
        """解析 LLM 响应为指令列表。"""
        # 尝试提取 JSON（可能被 markdown 代码块包裹）
        text = response.strip()
        if text.startswith("```"):
            # 去掉 ```json 和 ```
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        try:
            directives = json.loads(text)
            if isinstance(directives, list):
                return directives
        except json.JSONDecodeError:
            logger.warning(f"[Dream] JSON 解析失败: {text[:200]}")
        return []

    def _execute_directives(self, directives: list[dict], existing=None):
        """执行 LLM 输出的指令。"""
        valid_categories = {"personality", "user", "project", "fact"}
        # 已有同类记忆，用于 ADD 查重（含本轮新增的，避免一批指令内自我重复）
        existing_by_cat: dict[str, list[str]] = {}
        for m in existing or []:
            existing_by_cat.setdefault(m.category, []).append(m.content)

        for d in directives:
            action = d.get("action", "").upper()
            try:
                if action == "ADD":
                    category = d.get("category", "fact")
                    if category not in valid_categories:
                        category = "fact"
                    content = d["content"]
                    if self._is_duplicate(content, existing_by_cat.get(category, [])):
                        logger.info(f"[Dream] 跳过重复记忆: {content[:50]}")
                        continue
                    self._mem.add(
                        content=content,
                        category=category,
                        scope=MemoryScope.GLOBAL,
                        importance=min(max(d.get("importance", 5), 1), 10),
                        source="dream",
                    )
                    existing_by_cat.setdefault(category, []).append(content)
                elif action == "UPDATE":
                    memory_id = d.get("id")
                    if memory_id:
                        self._mem.update(
                            memory_id=memory_id,
                            content=d.get("content"),
                            importance=d.get("importance"),
                        )
                elif action == "DELETE":
                    memory_id = d.get("id")
                    if memory_id:
                        self._mem.delete(memory_id)
            except Exception as e:
                logger.warning(f"[Dream] 执行指令失败: {d} -> {e}")

    def _is_duplicate(self, content: str, existing_contents: list[str]) -> bool:
        """同 category 内判断 content 是否与已有记忆高度相似。"""
        norm = content.strip().lower()
        for other in existing_contents:
            ratio = SequenceMatcher(None, norm, other.strip().lower()).ratio()
            if ratio >= _DEDUP_THRESHOLD:
                return True
        return False
