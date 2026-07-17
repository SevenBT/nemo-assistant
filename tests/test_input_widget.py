import unittest

from PyQt6.QtWidgets import QApplication

from app.models.attachment import Attachment
from app.ui.input_widget import InputWidget

_app = QApplication.instance() or QApplication([])


class InputWidgetEditModeTest(unittest.TestCase):
    def setUp(self):
        self.widget = InputWidget()

    def tearDown(self):
        self.widget.deleteLater()

    def test_begin_edit_routes_submit_to_edit_signal(self):
        normal = []
        edited = []
        self.widget.submitted.connect(normal.append)
        self.widget.edit_submitted.connect(edited.append)

        self.widget.begin_edit("original", [])
        self.widget.set_text("changed")
        self.widget._submit()

        self.assertEqual(normal, [])
        self.assertEqual(edited, ["changed"])
        self.assertFalse(self.widget.is_editing)

    def test_explicit_cancel_clears_edit_text_and_emits_request(self):
        requested = []
        self.widget.edit_cancel_requested.connect(lambda: requested.append(True))
        self.widget.begin_edit("original", [])

        self.widget.cancel_edit()

        self.assertEqual(requested, [True])
        self.assertEqual(self.widget._edit.toPlainText(), "")
        self.assertFalse(self.widget.is_editing)

    def test_explicit_cancel_restores_previous_draft_and_attachments(self):
        attachment = Attachment(
            file_path="draft.txt",
            file_name="draft.txt",
            file_type="text",
            file_size=5,
        )
        self.widget.set_text("draft")
        self.widget.add_pending_attachments([attachment])
        self.widget.begin_edit("original", [])

        self.widget.cancel_edit()

        self.assertEqual(self.widget._edit.toPlainText(), "draft")
        self.assertEqual(
            self.widget.take_pending_attachments(), [attachment]
        )
        self.assertFalse(self.widget.is_editing)

    def test_clearing_edit_draft_exits_edit_mode(self):
        requested = []
        self.widget.edit_cancel_requested.connect(lambda: requested.append(True))
        self.widget.begin_edit("original", [])

        self.widget._edit.clear()

        self.assertEqual(requested, [True])
        self.assertFalse(self.widget.is_editing)

    def test_cancelling_state_blocks_submit_and_second_cancel(self):
        submitted = []
        cancelled = []
        self.widget.submitted.connect(submitted.append)
        self.widget.cancel_requested.connect(lambda: cancelled.append(True))
        self.widget.set_text("draft")
        self.widget.set_running(True)
        self.widget.set_cancelling(True)

        self.widget._submit()
        self.widget._on_button_clicked()

        self.assertEqual(submitted, [])
        self.assertEqual(cancelled, [])
        self.assertFalse(self.widget._btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
