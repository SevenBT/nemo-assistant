import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.models.message import MessageRole
from app.ui.chat_session_controller import ChatSessionController


class FakeSignal:
    def connect(self, callback):
        self.callback = callback


class FakeWorker:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.text_chunk = FakeSignal()
        self.tool_event = FakeSignal()
        self.need_input = FakeSignal()
        self.new_turn = FakeSignal()
        self.done = FakeSignal()
        self.started = False
        self.cancelled = False
        FakeWorker.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def disconnect(self):
        pass


class FakeSessionManager:
    def __init__(self):
        self.session = SimpleNamespace(
            id="s1",
            title="old",
            messages=[],
            system_prompt="",
        )
        self.saved = []

    def get_sessions(self):
        return [self.session]

    def get(self, sid):
        return self.session if sid == self.session.id else None

    def add_message(self, sid, message):
        self.session.messages.append(message)
        if message.role == MessageRole.USER:
            self.session.title = message.content[:25].strip()

    def save_session(self, sid):
        self.saved.append(sid)


class ChatSessionControllerTest(unittest.TestCase):
    def setUp(self):
        FakeWorker.instances.clear()
        self.sessions = FakeSessionManager()
        self.chat = Mock()
        self.chat.last_bubble.return_value = None
        self.input = Mock()
        self.session_panel = Mock()
        self.tool_status = Mock()
        self.prompt_builder = Mock()
        self.prompt_builder.build.return_value = [{"role": "system", "content": "x"}]
        self.controller = ChatSessionController(
            parent=None,
            session_mgr=self.sessions,
            llm_gateway=Mock(),
            registry=Mock(),
            prompt_builder=self.prompt_builder,
            chat=self.chat,
            input_widget=self.input,
            session_panel=self.session_panel,
            tool_status=self.tool_status,
        )

    def test_submit_creates_messages_and_starts_worker(self):
        self.controller.switch_session("s1")

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")

        self.assertEqual(len(self.sessions.session.messages), 2)
        self.assertEqual(self.sessions.session.messages[0].role, MessageRole.USER)
        self.assertEqual(self.sessions.session.messages[1].role, MessageRole.ASSISTANT)
        self.chat.add_message.assert_called_once_with(self.sessions.session.messages[0])
        self.input.set_enabled.assert_called_with(False)
        self.chat.start_typing.assert_called_once()
        self.prompt_builder.build.assert_called_once()
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertTrue(FakeWorker.instances[0].started)


if __name__ == "__main__":
    unittest.main()
