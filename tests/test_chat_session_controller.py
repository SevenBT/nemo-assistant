import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PyQt6.QtWidgets import QApplication

from app.models.message import Message, MessageRole
from app.ui.chat_session_controller import ChatSessionController

_app = QApplication.instance() or QApplication([])


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class BindingBubble:
    """Fake the old UI behavior that writes rendered text to its bound message."""

    def __init__(self, message):
        self.message = message
        self.text = message.content
        self.tool_calls = []

    def bind_message(self, message):
        self.message = message

    def clear_text(self):
        self.text = ""

    def set_content_streaming(self, text):
        self.text = text
        self.message.content = text

    def set_content(self, text):
        self.text = text
        self.message.content = text

    def add_tool_card(self, call_id, name, params):
        self.tool_calls.append((call_id, name, params))

    def update_tool_card(self, call_id, result):
        pass


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
        # 点「编辑」只回填输入框并进入编辑模式，不立刻改动历史。
        self.controller.switch_session("s1")
        user_msg = Message(role=MessageRole.USER, content="original question")
        assistant_msg = Message(role=MessageRole.ASSISTANT, content="a1")
        self.sessions.session.messages = [user_msg, assistant_msg]

        self.controller.edit_last(user_msg)

        # 历史原样保留，输入框回填原文并记录目标消息身份。
        self.assertEqual(
            self.sessions.session.messages, [user_msg, assistant_msg]
        )
        self.input.begin_edit.assert_called_once_with(
            "original question", []
        )
        self.assertEqual(self.controller._pending_edit["s1"], user_msg.id)

    def test_normal_submit_does_not_consume_pending_edit(self):
        self.controller.switch_session("s1")
        user_msg = Message(role=MessageRole.USER, content="original question")
        assistant_msg = Message(role=MessageRole.ASSISTANT, content="a1")
        self.sessions.session.messages = [user_msg, assistant_msg]
        self.input.take_pending_attachments.return_value = []
        self.controller.edit_last(user_msg)

        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("new question")

        self.assertEqual(
            [m.content for m in self.sessions.session.messages],
            ["original question", "a1", "new question", ""],
        )
        self.input.end_edit.assert_called_once_with(clear=False)
        self.assertNotIn("s1", self.controller._pending_edit)

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
            self.controller.submit_edit("edited question")

        roles = [m.role for m in self.sessions.session.messages]
        self.assertEqual(roles, [MessageRole.USER, MessageRole.ASSISTANT])
        self.assertEqual(self.sessions.session.messages[0].content, "edited question")
        self.assertNotIn("s1", self.controller._pending_edit)

    def test_cancel_edit_preserves_history_and_next_submit_appends(self):
        self.controller.switch_session("s1")
        original = [
            Message(role=MessageRole.USER, content="q1"),
            Message(role=MessageRole.ASSISTANT, content="a1"),
        ]
        self.sessions.session.messages = original.copy()
        self.input.take_pending_attachments.return_value = []
        self.controller.edit_last(original[0])

        self.controller.cancel_edit()
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("q2")

        self.assertEqual(
            [m.content for m in self.sessions.session.messages],
            ["q1", "a1", "q2", ""],
        )
        self.input.end_edit.assert_not_called()

    def test_switch_session_discards_pending_edit(self):
        self.controller.switch_session("s1")
        self.controller._pending_edit["s1"] = "message-id"
        self.controller.switch_session("s1")  # 切回同一会话保留
        self.assertIn("s1", self.controller._pending_edit)
        self.controller.switch_session("s2")  # 切到别的会话丢弃
        self.assertNotIn("s1", self.controller._pending_edit)

    def test_switching_back_to_cancelling_session_stops_typing_when_finished(self):
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")
        worker = FakeWorker.instances[0]
        self.controller.cancel_worker("s1")
        self.controller.switch_session("other")
        self.controller.switch_session("s1")
        starts_before_finished = self.chat.start_typing.call_count

        worker.finished.emit()

        self.assertEqual(self.chat.start_typing.call_count, starts_before_finished)
        self.chat.stop_typing.assert_called()
        self.tool_status.hide.assert_called()

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
        self.input.set_cancelling.assert_called_with(True)
        self.chat.stop_typing.assert_called()
        self.assertEqual(self.sessions.saved, ["s1"])

    def test_cancelled_worker_blocks_retry_until_finished(self):
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")
            worker = FakeWorker.instances[0]
            self.controller.cancel_worker("s1")
            self.controller.submit("retry too early")

            self.assertEqual(len(FakeWorker.instances), 1)
            self.assertIs(self.controller._workers["s1"], worker)

            worker.finished.emit()
            self.controller.submit("retry now")

        self.assertEqual(len(FakeWorker.instances), 2)
        self.assertTrue(FakeWorker.instances[1].started)

    def test_cancelled_worker_ignores_late_text_and_finalizes_running_tools(self):
        bubble = Mock()
        self.chat.add_message.side_effect = [Mock(), bubble]
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")
        worker = FakeWorker.instances[0]
        worker.tool_event.emit(
            "call-1", "start", {"name": "search", "params": {}}
        )

        self.controller.cancel_worker("s1")
        cancelled_content = self.sessions.session.messages[-1].content
        worker.text_chunk.emit("late text")
        worker.new_turn.emit(2)
        worker.finished.emit()

        assistant = self.sessions.session.messages[-1]
        self.assertEqual(assistant.content, cancelled_content)
        self.assertEqual(len([
            m for m in self.sessions.session.messages
            if m.role == MessageRole.ASSISTANT
        ]), 1)
        self.assertEqual(assistant.tool_calls[0].status, "error")
        self.assertEqual(assistant.tool_calls[0].result["status"], "error")
        bubble.update_tool_card.assert_called_with(
            "call-1", assistant.tool_calls[0].result
        )

    def test_cancelled_worker_persists_late_tool_success(self):
        bubble = Mock()
        self.chat.add_message.side_effect = [Mock(), bubble]
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")
        worker = FakeWorker.instances[0]
        worker.tool_event.emit(
            "call-1", "start", {"name": "save_file", "params": {}}
        )

        self.controller.cancel_worker("s1")
        worker.tool_event.emit(
            "call-1", "done", {"result": {"status": "success"}}
        )
        worker.finished.emit()

        tool_call = self.sessions.session.messages[-1].tool_calls[0]
        self.assertEqual(tool_call.status, "success")
        self.assertEqual(tool_call.result["status"], "success")
        self.assertGreaterEqual(self.sessions.saved.count("s1"), 2)

    def test_cancelled_worker_persists_queued_start_and_done(self):
        bubble = Mock()
        self.chat.add_message.side_effect = [Mock(), bubble]
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("hello")
        worker = FakeWorker.instances[0]

        self.controller.cancel_worker("s1")
        worker.tool_event.emit(
            "call-1", "start", {"name": "save_file", "params": {}}
        )
        worker.tool_event.emit(
            "call-1", "done", {"result": {"status": "success"}}
        )
        worker.finished.emit()

        tool_calls = self.sessions.session.messages[-1].tool_calls
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0].name, "save_file")
        self.assertEqual(tool_calls[0].status, "success")
        bubble.add_tool_card.assert_not_called()

    def test_tool_multiturn_does_not_overwrite_previous_messages(self):
        bubbles = []

        def add_message(message):
            bubble = BindingBubble(message)
            bubbles.append(bubble)
            return bubble

        self.chat.add_message.side_effect = add_message
        self.controller.switch_session("s1")
        self.input.take_pending_attachments.return_value = []
        with patch("app.ui.chat_session_controller.AgentLoop", FakeWorker):
            self.controller.submit("question")

        self.controller._on_tool_event(
            "s1", "call-1", "start", {"name": "search", "params": {}}
        )
        self.controller._on_tool_event(
            "s1", "call-1", "done", {"result": {"status": "success"}}
        )
        self.controller._on_new_turn("s1", 1)
        self.controller._on_tool_event(
            "s1", "call-2", "start", {"name": "read", "params": {}}
        )
        self.controller._on_tool_event(
            "s1", "call-2", "done", {"result": {"status": "success"}}
        )
        self.controller._on_new_turn("s1", 2)
        self.controller._on_text_chunk("s1", "final answer")
        self.controller._on_done("s1", {"ok": True})

        assistant = [
            message
            for message in self.sessions.session.messages
            if message.role == MessageRole.ASSISTANT
        ]
        self.assertEqual([m.content for m in assistant], ["", "", "final answer"])
        self.assertEqual([[tc.id for tc in m.tool_calls] for m in assistant], [
            ["call-1"], ["call-2"], []
        ])


if __name__ == "__main__":
    unittest.main()
