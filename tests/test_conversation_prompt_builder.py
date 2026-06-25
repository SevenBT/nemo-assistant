import json
import unittest
from types import SimpleNamespace

from app.core.conversation_prompt_builder import ConversationPromptBuilder
from app.models.message import Message, MessageRole, ToolCall


class FakeConfig:
    systemPrompt = object()

    def __init__(self, system_prompt: str = ""):
        self._system_prompt = system_prompt

    def get(self, item):
        if item is self.systemPrompt:
            return self._system_prompt
        raise KeyError(item)


class FakeSessionManager:
    def __init__(self, session):
        self._session = session

    def get(self, session_id):
        return self._session


class FakeMemoryManager:
    def build_memory_context(self, session_id):
        return f"memory for {session_id}"


class ConversationPromptBuilderTest(unittest.TestCase):
    def test_session_prompt_memory_and_tool_results_are_preserved(self):
        session = SimpleNamespace(system_prompt="Session prompt")
        builder = ConversationPromptBuilder(
            session_mgr=FakeSessionManager(session),
            memory_mgr=FakeMemoryManager(),
            config=FakeConfig("Global prompt"),
            datetime_info_provider=lambda: "time info",
            time_hint_provider=lambda: "[time hint]",
        )

        tool_call = ToolCall(
            id="call-1",
            name="lookup",
            arguments={"query": "x"},
            result={"status": "success", "value": 42},
        )
        messages = [
            Message(role=MessageRole.USER, content="hello"),
            Message(role=MessageRole.ASSISTANT, content="", tool_calls=[tool_call]),
        ]

        result = builder.build(messages, session_id="s1")

        self.assertEqual(result[0]["role"], "system")
        self.assertIn("Session prompt", result[0]["content"])
        self.assertNotIn("Global prompt", result[0]["content"])
        self.assertIn("memory for s1", result[0]["content"])
        self.assertTrue(result[0]["content"].endswith("time info"))
        # 精确时间作为独立 system 消息追加在末尾（缓存优化）
        self.assertEqual(result[-1]["role"], "system")
        self.assertEqual(result[-1]["content"], "[time hint]")
        # 工具结果消息在时间 hint 之前
        self.assertEqual(result[-2]["role"], "tool")
        self.assertEqual(result[-2]["tool_call_id"], "call-1")
        self.assertEqual(json.loads(result[-2]["content"])["value"], 42)

    def test_incomplete_assistant_tool_call_is_omitted(self):
        session = SimpleNamespace(system_prompt="")
        builder = ConversationPromptBuilder(
            session_mgr=FakeSessionManager(session),
            config=FakeConfig("Global prompt"),
            datetime_info_provider=lambda: "time info",
            time_hint_provider=lambda: "[time hint]",
        )
        messages = [
            Message(role=MessageRole.USER, content="hello"),
            Message(
                role=MessageRole.ASSISTANT,
                content="",
                tool_calls=[
                    ToolCall(
                        id="call-1",
                        name="lookup",
                        arguments={"query": "x"},
                    )
                ],
            ),
        ]

        result = builder.build(messages, session_id="s1")

        self.assertEqual(
            [message["role"] for message in result], ["system", "user", "system"]
        )
        self.assertIn("Global prompt", result[0]["content"])
        self.assertEqual(result[-1]["content"], "[time hint]")


if __name__ == "__main__":
    unittest.main()
