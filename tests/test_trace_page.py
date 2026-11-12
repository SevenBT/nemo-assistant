"""Exercise the retained user-facing runtime history and previewed export."""
import json

from PyQt6.QtWidgets import QDialog, QFileDialog, QPlainTextEdit

from app.core.trace_store import TraceStore
from app.ui.settings_pages.trace_page import TracePage
from app.ui.settings_window import SettingsWindow


def test_runtime_page_exports_preview_without_private_bodies(qtbot, tmp_path, monkeypatch):
    store = TraceStore(tmp_path / "traces.db")
    store.start_trace("synthetic", "private-session")
    store.record_iteration("synthetic", turn=0, answer="PRIVATE_ANSWER", tool_count=0, error_count=0, had_error=False)
    store.record_llm_call("synthetic", 0, {"attempt_id": "a", "status": "ok", "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}})
    store.finish_trace("synthetic", status="ok")
    page = TracePage(store)
    qtbot.addWidget(page)
    page.resize(1000, 700)
    page.show()
    assert page._export_btn.isEnabled()
    assert "eval" not in {name for _, name in SettingsWindow._PAGES}
    target = tmp_path / "diagnostic.json"

    def preview(dialog):
        editor = dialog.findChild(QPlainTextEdit)
        payload = json.loads(editor.toPlainText())
        assert payload["trace"]["total_tokens"] == 10
        assert "PRIVATE_ANSWER" not in editor.toPlainText()
        assert "private-session" not in editor.toPlainText()
        # The preview is editable, including removal before save.
        payload.pop("security_events")
        editor.setPlainText(json.dumps(payload))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", preview)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), "JSON"))
    page._on_export()
    assert "security_events" not in json.loads(target.read_text(encoding="utf-8"))
