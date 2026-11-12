"""Exercise the retained user-facing runtime history and previewed export."""
import json

from PyQt6.QtWidgets import QDialog, QFileDialog, QPlainTextEdit, QLabel
from qfluentwidgets import HyperlinkButton

from app.observability.trace_store import TraceStore
from app.ui.settings_pages.trace_page import TracePage
from app.ui.settings_window import SettingsWindow
from app.i18n import t


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


def test_cost_labels_and_console_link_do_not_promote_old_estimates(qtbot):
    from app.ui.settings_pages.trace_page import _llm_card

    old = _llm_card({"cost_usd": 0.123, "provider": "deepseek"}, None)
    qtbot.addWidget(old)
    texts = [label.text() for label in old.findChildren(QLabel)]
    assert t("settings.trace.unreported_cost") in texts
    assert t("settings.trace.legacy_cost", amount="0.123") in texts
    assert not old.findChildren(HyperlinkButton)

    reported = _llm_card({"provider": "deepseek", "reported_cost_amount": 0,
        "reported_cost_currency": "CNY", "billing_url": "https://platform.deepseek.com/"}, None)
    qtbot.addWidget(reported)
    assert t("settings.trace.reported_cost", currency="CNY", amount="0") in [label.text() for label in reported.findChildren(QLabel)]
    assert len(reported.findChildren(HyperlinkButton)) == 1

    proxy = _llm_card({"provider": "openai", "billing_url": "https://proxy.example/?api_key=secret"}, None)
    qtbot.addWidget(proxy)
    assert not proxy.findChildren(HyperlinkButton)
