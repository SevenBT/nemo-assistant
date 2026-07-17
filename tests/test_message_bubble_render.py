import unittest
from unittest.mock import patch

from PyQt6.QtCore import QAbstractAnimation, QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.models.message import Message, MessageRole
from app.ui.chat_widget import ChatWidget, MessageBubble

_app = QApplication.instance() or QApplication([])


class MessageBubbleStreamingRenderTest(unittest.TestCase):
    """流式去抖渲染：窗口内多次 chunk 只重渲染一次，终态立即落地。"""

    def _ai_bubble(self) -> MessageBubble:
        return MessageBubble(Message(role=MessageRole.ASSISTANT, content=""))

    def test_streaming_defers_render_and_coalesces(self):
        bubble = self._ai_bubble()
        with patch.object(bubble._content, "set_text") as set_text:
            # 连续多个 chunk 到达，均在去抖窗口内。
            bubble.set_content_streaming("a")
            bubble.set_content_streaming("ab")
            bubble.set_content_streaming("abc")
            # 尚未 flush：一次真正的重渲染都没发生。
            set_text.assert_not_called()
            self.assertEqual(bubble._pending_text, "abc")
            # 渲染层只维护展示状态；持久化 Message 由控制器唯一写入。
            self.assertEqual(bubble.message.content, "")

            # 定时器触发后，只渲染最后一次的合并文本。
            bubble._flush_pending_render()
            set_text.assert_called_once_with("abc")
            self.assertIsNone(bubble._pending_text)

    def test_streaming_flush_requests_scroll_after_layout(self):
        bubble = self._ai_bubble()
        scroll_requests = []
        bubble.content_rendered.connect(lambda: scroll_requests.append(True))
        bubble.set_content_streaming("new content")

        bubble._flush_pending_render()

        self.assertEqual(scroll_requests, [True])

    def test_set_content_forces_immediate_render_and_cancels_pending(self):
        bubble = self._ai_bubble()
        bubble.set_content_streaming("partial")
        self.assertTrue(bubble._render_timer.isActive())

        with patch.object(bubble._content, "set_text") as set_text:
            bubble.set_content("final text")
            # 终态立即渲染。
            set_text.assert_called_once_with("final text")
        # 挂起的去抖被取消，不会再补一帧旧内容。
        self.assertIsNone(bubble._pending_text)
        self.assertFalse(bubble._render_timer.isActive())
        self.assertEqual(bubble.message.content, "")

    def test_bind_message_changes_action_target(self):
        bubble = self._ai_bubble()
        current = Message(role=MessageRole.ASSISTANT, content="final")

        bubble.bind_message(current)

        self.assertIs(bubble.message, current)

    def test_clear_text_cancels_pending_render(self):
        bubble = self._ai_bubble()
        bubble.set_content_streaming("half-streamed")
        self.assertTrue(bubble._render_timer.isActive())

        bubble.clear_text()
        self.assertIsNone(bubble._pending_text)
        self.assertFalse(bubble._render_timer.isActive())


class ChatWidgetSessionLoadBatchingTest(unittest.TestCase):
    """会话批量加载只在全部气泡就绪后统一完成派生 UI 工作。"""

    @staticmethod
    def _conversation() -> list[Message]:
        return [
            Message(role=MessageRole.USER, content="question 1"),
            Message(role=MessageRole.ASSISTANT, content="answer 1"),
            Message(role=MessageRole.USER, content="question 2"),
            Message(role=MessageRole.ASSISTANT, content="answer 2"),
        ]

    def test_load_session_refreshes_action_targets_once(self):
        chat = ChatWidget()
        self.addCleanup(chat.deleteLater)

        with patch.object(
            chat,
            "_refresh_action_targets",
            wraps=chat._refresh_action_targets,
        ) as refresh_action_targets:
            chat.load_session(self._conversation())

        refresh_action_targets.assert_called_once_with()

    def test_load_session_queues_only_final_scroll_and_anchor_rebuild(self):
        chat = ChatWidget()
        self.addCleanup(chat.deleteLater)
        scheduled = []

        with patch(
            "app.ui.chat_widget.QTimer.singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            chat.load_session(self._conversation())

        self.assertEqual(
            scheduled,
            [chat._scroll_bottom, chat._rebuild_anchors],
        )

    def test_add_message_keeps_realtime_refresh_and_scheduling(self):
        chat = ChatWidget()
        self.addCleanup(chat.deleteLater)
        scheduled = []
        message = Message(role=MessageRole.USER, content="live question")

        with (
            patch.object(
                chat,
                "_refresh_action_targets",
                wraps=chat._refresh_action_targets,
            ) as refresh_action_targets,
            patch(
                "app.ui.chat_widget.QTimer.singleShot",
                side_effect=lambda _delay, callback: scheduled.append(callback),
            ),
        ):
            bubble = chat.add_message(message)

        self.assertIs(chat.last_bubble(), bubble)
        refresh_action_targets.assert_called_once_with()
        self.assertEqual(
            scheduled,
            [chat._scroll_bottom, chat._rebuild_anchors],
        )


class ChatWidgetAutoFollowTest(unittest.TestCase):
    """用户主动指定滚动位置后，流式自动跟随应让出控制权。"""

    def test_custom_scrollbar_handle_press_pauses_auto_follow(self):
        chat = ChatWidget()
        custom_bar = chat._scroll.delegate.vScrollBar
        custom_bar.setRange(0, 100)
        custom_bar.resize(12, 200)
        custom_bar.show()
        custom_bar.handle.show()

        QTest.mousePress(
            custom_bar.handle,
            Qt.MouseButton.LeftButton,
            pos=custom_bar.handle.rect().center(),
        )

        self.assertFalse(chat._auto_follow_stream)
        QTest.mouseRelease(
            custom_bar.handle,
            Qt.MouseButton.LeftButton,
            pos=custom_bar.handle.rect().center(),
        )

    def test_custom_scrollbar_arrow_click_pauses_auto_follow(self):
        chat = ChatWidget()
        custom_bar = chat._scroll.delegate.vScrollBar
        native_bar = chat._scroll.verticalScrollBar()
        native_bar.setRange(0, 100)
        native_bar.setValue(50)
        custom_bar.setValue(50, useAni=False)

        QTest.mouseClick(
            custom_bar.groove.upButton,
            Qt.MouseButton.LeftButton,
            pos=custom_bar.groove.upButton.rect().center(),
        )
        QApplication.processEvents()

        self.assertFalse(chat._auto_follow_stream)

    def test_scrollbar_release_before_up_animation_keeps_auto_follow_paused(self):
        chat = ChatWidget()
        custom_bar = chat._scroll.delegate.vScrollBar
        native_bar = chat._scroll.verticalScrollBar()
        native_bar.setRange(0, 100)
        native_bar.setValue(100)
        chat._auto_follow_stream = False
        scheduled = []

        # release 事件处理完成后，箭头 clicked 会先启动动画；零延迟回调执行时，
        # 原生滚动条仍可能停在底部，动画首帧尚未向上移动。
        release = QEvent(QEvent.Type.MouseButtonRelease)
        with patch(
            "app.ui.chat_widget.QTimer.singleShot",
            side_effect=lambda _delay, callback: scheduled.append(callback),
        ):
            chat.eventFilter(custom_bar.groove.upButton, release)
        custom_bar.setValue(50)
        self.assertEqual(native_bar.value(), 100)

        scheduled[0]()
        custom_bar.ani.stop()

        self.assertFalse(chat._auto_follow_stream)

    def test_anchor_jump_pauses_auto_follow(self):
        chat = ChatWidget()
        bubble = chat.add_message(
            Message(role=MessageRole.USER, content="earlier question")
        )

        chat._scroll_to_bubble(bubble)

        self.assertFalse(chat._auto_follow_stream)

    def test_rendered_bubble_requests_controlled_scroll(self):
        chat = ChatWidget()
        with patch.object(chat, "scroll_bottom") as scroll_bottom:
            bubble = chat.add_message(
                Message(role=MessageRole.ASSISTANT, content="answer")
            )
            bubble.content_rendered.emit()

        scroll_bottom.assert_called_once_with()

    def test_wheel_event_pauses_auto_follow(self):
        chat = ChatWidget()
        bar = chat._scroll.verticalScrollBar()
        bar.setRange(0, 100)
        bar.setValue(50)
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        chat.eventFilter(chat._scroll.viewport(), event)

        self.assertFalse(chat._auto_follow_stream)

    def test_wheel_without_scroll_range_keeps_auto_follow(self):
        chat = ChatWidget()
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        chat.eventFilter(chat._scroll.viewport(), event)

        self.assertTrue(chat._auto_follow_stream)

    def test_wheel_down_at_bottom_keeps_auto_follow(self):
        chat = ChatWidget()
        bar = chat._scroll.verticalScrollBar()
        bar.setRange(0, 100)
        bar.setValue(100)
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, -120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )

        chat.eventFilter(chat._scroll.viewport(), event)

        self.assertTrue(chat._auto_follow_stream)

    def test_returning_to_bottom_restores_auto_follow(self):
        chat = ChatWidget()
        chat._auto_follow_stream = False
        bar = chat._scroll.verticalScrollBar()
        bar.setRange(0, 100)
        bar.setValue(100)

        chat._on_scroll_changed()

        self.assertTrue(chat._auto_follow_stream)

    def test_pending_auto_scroll_does_not_override_user_position(self):
        chat = ChatWidget()
        bar = chat._scroll.verticalScrollBar()
        bar.setRange(0, 100)
        bar.setValue(20)
        chat._auto_follow_stream = False

        # 模拟用户操作前已经由上一 chunk 排队的延迟回底任务。
        chat._scroll_bottom()

        self.assertEqual(bar.value(), 20)

    def test_scroll_bottom_stops_conflicting_smooth_animation(self):
        chat = ChatWidget()
        native_bar = chat._scroll.verticalScrollBar()
        custom_bar = chat._scroll.delegate.vScrollBar
        native_bar.setRange(0, 100)
        custom_bar.setRange(0, 100)
        custom_bar.setValue(100, useAni=False)
        custom_bar.setValue(0)
        self.assertEqual(
            custom_bar.ani.state(), QAbstractAnimation.State.Running
        )

        chat._scroll_bottom()
        QTest.qWait(custom_bar.ani.duration() + 50)

        self.assertEqual(
            custom_bar.ani.state(), QAbstractAnimation.State.Stopped
        )
        self.assertEqual(native_bar.value(), native_bar.maximum())


if __name__ == "__main__":
    unittest.main()
