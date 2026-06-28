"""核心健壮性修复测试：consolidator token 估算、dream id 白名单、scheduler 异常上报。"""
import unittest
from unittest import mock

from app.core import consolidator as cons
from app.core.consolidator import _estimate_messages_tokens, _message_token_text
from app.core.dream import Dream
from app.models.message import Message, MessageRole, ToolCall


class ConsolidatorTokenTest(unittest.TestCase):
    def test_tool_calls_counted(self):
        """带 tool_calls 的消息 token 估算应显著高于只看 content。"""
        big_args = {"query": "x" * 2000}
        big_result = {"data": "y" * 2000}
        msg = Message(
            role=MessageRole.ASSISTANT,
            content="",
            tool_calls=[ToolCall(id="1", name="search", arguments=big_args, result=big_result)],
        )
        text = _message_token_text(msg)
        # content 为空，但 tool_calls 的参数与结果应进入估算文本
        self.assertIn("x" * 2000, text)
        self.assertIn("y" * 2000, text)
        self.assertGreater(_estimate_messages_tokens([msg]), 500)

    def test_plain_message_still_counted(self):
        msg = Message(role=MessageRole.USER, content="你好世界")
        self.assertEqual(_message_token_text(msg), "你好世界")


class _FakeMem:
    """记录 update/delete 调用的假 MemoryManager。"""

    def __init__(self):
        self.updated = []
        self.deleted = []

    def add(self, **kwargs):
        pass

    def update(self, memory_id, **kwargs):
        self.updated.append(memory_id)
        return True

    def delete(self, memory_id):
        self.deleted.append(memory_id)
        return True


class _Existing:
    def __init__(self, id, category="fact", content="c", importance=5):
        self.id = id
        self.category = category
        self.content = content
        self.importance = importance


class DreamIdWhitelistTest(unittest.TestCase):
    def setUp(self):
        self.mem = _FakeMem()
        self.dream = Dream(llm_gateway=mock.MagicMock(), memory_mgr=self.mem)
        self.existing = [_Existing(10), _Existing(20)]

    def test_update_within_whitelist_applied(self):
        self.dream._execute_directives(
            [{"action": "UPDATE", "id": 10, "content": "new"}], self.existing
        )
        self.assertEqual(self.mem.updated, [10])

    def test_delete_outside_whitelist_skipped(self):
        # id=999 不在 global existing 内（可能是某 session 记忆），必须跳过
        self.dream._execute_directives(
            [{"action": "DELETE", "id": 999}], self.existing
        )
        self.assertEqual(self.mem.deleted, [])

    def test_delete_within_whitelist_applied(self):
        self.dream._execute_directives(
            [{"action": "DELETE", "id": 20}], self.existing
        )
        self.assertEqual(self.mem.deleted, [20])


class SchedulerJobErrorTest(unittest.TestCase):
    def test_tool_exception_reported_via_callback(self):
        from app.core.scheduler import SchedulerManager

        results = []
        mgr = SchedulerManager()
        mgr._on_result = lambda jid, name, res: results.append(res)

        class _BoomTool:
            def execute(self, name, params):
                raise RuntimeError("boom")

        mgr._tool_manager = _BoomTool()
        mgr._jobs["j1"] = {"name": "测试", "tool_name": "x", "params": {}}

        mgr._run_job("j1")  # 不应抛出
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "error")
        self.assertIn("boom", results[0]["data"]["message"])


if __name__ == "__main__":
    unittest.main()
