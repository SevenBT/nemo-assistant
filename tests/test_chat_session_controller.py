import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication

from app.models.message import Message, MessageRole
from app.ui.chat_session_controller import ChatSessionController

_app = QApplication.instance() or QApplication([])


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
        self.finished = FakeSignal()
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

    def create(self, title="", source=""):
        self.created = SimpleNamespace(id="reading1", title=title, source=source)
        return self.created


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

    def test_resolve_reading_session_force_new_creates_session(self):
        # 回归：_resolve_reading_session 曾引用未定义的 READING_SESSION_TITLE，
        # force_new=True 时必崩 NameError。此路径是划词「新建会话」的必经之处。
        from app.ui.chat_session_controller import reading_session_title

        with patch("app.ui.chat_session_controller.cfg") as fake_cfg:
            fake_cfg.get.return_value = ""
            sid = self.controller._resolve_reading_session(force_new=True)

        self.assertEqual(sid, "reading1")
        self.assertEqual(self.sessions.created.title, reading_session_title())

    def test_submit_creates_messages_and_starts_worker(self):
        self.controller.switch_session("s1")

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")

        self.assertEqual(len(self.sessions.session.messages), 2)
        self.assertEqual(self.sessions.session.messages[0].role, MessageRole.USER)
        self.assertEqual(self.sessions.session.messages[1].role, MessageRole.ASSISTANT)
        self.chat.add_message.assert_called_once_with(self.sessions.session.messages[0])
        self.input.set_running.assert_called_with(True)
        self.chat.start_typing.assert_called_once()
        self.prompt_builder.build.assert_called_once()
        self.assertEqual(len(FakeWorker.instances), 1)
        self.assertTrue(FakeWorker.instances[0].started)

    def test_regenerate_last_truncates_after_user_and_reruns(self):
        # 构造一轮完整对话：user + assistant。
        self.controller.switch_session("s1")
        self.sessions.session.messages = [
            Message(role=MessageRole.USER, content="q1"),
            Message(role=MessageRole.ASSISTANT, content="a1"),
        ]

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.regenerate_last()

        # 旧 assistant 回复被丢弃，末尾是新的空 assistant 占位。
        roles = [m.role for m in self.sessions.session.messages]
        self.assertEqual(roles, [MessageRole.USER, MessageRole.ASSISTANT])
        self.assertEqual(self.sessions.session.messages[0].content, "q1")
        self.assertEqual(self.sessions.session.messages[-1].content, "")
        self.assertTrue(FakeWorker.instances[0].started)

    def test_regenerate_noop_while_worker_running(self):
        self.controller.switch_session("s1")
        self.sessions.session.messages = [
            Message(role=MessageRole.USER, content="q1"),
            Message(role=MessageRole.ASSISTANT, content="a1"),
        ]
        self.controller._workers["s1"] = object()  # 模拟进行中的 worker

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.regenerate_last()

        self.assertEqual(len(FakeWorker.instances), 0)

    def test_edit_last_refills_input_without_truncating(self):
        # 点「编辑」只回填输入框、登记待生效下标，不立刻改动历史。
        self.controller.switch_session("s1")
        user_msg = Message(role=MessageRole.USER, content="original question")
        assistant_msg = Message(role=MessageRole.ASSISTANT, content="a1")
        self.sessions.session.messages = [user_msg, assistant_msg]

        self.controller.edit_last(user_msg)

        # 历史原样保留，输入框回填原文。
        self.assertEqual(
            self.sessions.session.messages, [user_msg, assistant_msg]
        )
        self.input.set_text.assert_called_once_with("original question")
        self.assertEqual(self.controller._pending_edit["s1"], 0)

    def test_edit_then_resubmit_truncates_old_turn(self):
        # 编辑后真正重发：旧轮（原 user + assistant）被截断，替换为新消息。
        self.controller.switch_session("s1")
        user_msg = Message(role=MessageRole.USER, content="original question")
        self.sessions.session.messages = [
            user_msg,
            Message(role=MessageRole.ASSISTANT, content="a1"),
        ]
        self.input.take_pending_attachments.return_value = []

        self.controller.edit_last(user_msg)
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("edited question")

        roles = [m.role for m in self.sessions.session.messages]
        self.assertEqual(roles, [MessageRole.USER, MessageRole.ASSISTANT])
        self.assertEqual(self.sessions.session.messages[0].content, "edited question")
        self.assertNotIn("s1", self.controller._pending_edit)

    def test_switch_session_discards_pending_edit(self):
        self.controller.switch_session("s1")
        self.controller._pending_edit["s1"] = 0
        self.controller.switch_session("s1")  # 切回同一会话保留
        self.assertIn("s1", self.controller._pending_edit)
        self.controller.switch_session("s2")  # 切到别的会话丢弃
        self.assertNotIn("s1", self.controller._pending_edit)

    def test_copy_reply_puts_text_on_clipboard(self):
        from PyQt6.QtWidgets import QApplication

        msg = Message(role=MessageRole.ASSISTANT, content="hello reply")
        self.controller.copy_reply(msg)

        self.assertEqual(QApplication.clipboard().text(), "hello reply")

    def test_cancel_keeps_partial_response_and_stops_worker(self):
        bubble = Mock()
        self.chat.add_message.side_effect = [Mock(), bubble]
        self.controller.switch_session("s1")

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")

        self.controller._on_text_chunk("s1", "partial")
        self.controller.cancel_worker("s1")

        self.assertTrue(FakeWorker.instances[0].cancelled)
        from app.i18n import t
        marker = t("chat.cancelled")
        self.assertEqual(self.sessions.session.messages[-1].content, f"partial\n\n{marker}")
        bubble.set_content.assert_any_call(f"partial\n\n{marker}")
        self.input.set_running.assert_called_with(False)
        self.chat.stop_typing.assert_called()
        self.assertEqual(self.sessions.saved, ["s1"])


if __name__ == "__main__":
    unittest.main()
