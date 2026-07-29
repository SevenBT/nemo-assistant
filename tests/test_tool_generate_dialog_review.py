"""UI contract tests for staged review and explicit generated-tool installation."""
from __future__ import annotations

import json
from dataclasses import replace

import pytest
from PyQt6.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QScrollArea, QWidget

from app.i18n import t
from app.core.tool_build import (
    BuildReview,
    BuildStatus,
    InstallResult,
    IssueSeverity,
    ToolManifest,
    ToolPermission,
    ValidationIssue,
    ValidationReport,
)
from app.tools.registry import ToolRegistry
from app.ui.tool_generate_dialog import ToolGenerateDialog
from app.ui.tool_build_workers import _GenerateWorker

pytestmark = pytest.mark.ui


MANIFEST_TEXT = json.dumps(
    {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "A generated tool",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
)
SCRIPT_TEXT = "print('{}')"


def _manifest(
    *, permissions: frozenset[ToolPermission] = frozenset()
) -> ToolManifest:
    return ToolManifest(
        manifest_version=1,
        name="safe_tool",
        description="A generated tool",
        script="tool.py",
        parameters={},
        output={"type": "object"},
        permissions=permissions,
        dependencies=(),
    )


def _review(
    *issues: ValidationIssue,
    permissions: frozenset[ToolPermission] = frozenset(),
    detected: frozenset[ToolPermission] = frozenset(),
    dependencies: tuple[str, ...] = (),
) -> BuildReview:
    report = ValidationReport(
        build_id="build-1",
        status=(
            BuildStatus.INSTALL_REVIEW
            if not any(issue.severity is IssueSeverity.BLOCK for issue in issues)
            else BuildStatus.VALIDATION_FAILED
        ),
        declared_permissions=permissions,
        detected_permissions=detected,
        dependencies=dependencies,
        file_hashes={
            "manifest.json": "a" * 64,
            "tool.py": "b" * 64,
        },
        issues=issues,
    )
    return BuildReview("build-1", _manifest(permissions=permissions), SCRIPT_TEXT, report)


class FakeToolBuildService:
    def __init__(
        self,
        review: BuildReview,
        install_result: InstallResult | None = None,
        install_results: list[InstallResult] | None = None,
    ) -> None:
        self.review_value = review
        self.install_result = install_result or InstallResult(True, "safe_tool", "")
        self.install_results = list(install_results or [])
        self.stage_calls: list[tuple[str, str, str]] = []
        self.review_calls: list[tuple[str, frozenset[ToolPermission]]] = []
        self.install_calls: list[tuple[str, frozenset[ToolPermission], bool]] = []

    def stage(
        self, requirement: str, manifest_text: str, script_text: str
    ) -> BuildReview:
        self.stage_calls.append((requirement, manifest_text, script_text))
        return replace(self.review_value, report=replace(self.review_value.report, status=BuildStatus.STAGED))

    def review(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> BuildReview:
        self.review_calls.append((build_id, approved_permissions, acknowledged_overrides))
        return self.review_value

    def install(
        self,
        build_id: str,
        approved_permissions: frozenset[ToolPermission],
        *,
        overwrite: bool,
        acknowledged_overrides: frozenset[str] = frozenset(),
    ) -> InstallResult:
        self.install_calls.append(
            (build_id, approved_permissions, overwrite, acknowledged_overrides)
        )
        if self.install_results:
            return self.install_results.pop(0)
        return self.install_result


def _dialog(qtbot, service: FakeToolBuildService, registry: ToolRegistry | None = None):
    dialog = ToolGenerateDialog(
        registry=registry or ToolRegistry(),
        build_service=service,
    )
    qtbot.addWidget(dialog)
    dialog._req_edit.setPlainText("Build a local tool")
    dialog._name_edit.setText("safe_tool")
    dialog._manifest_edit.setPlainText(MANIFEST_TEXT)
    dialog._script_edit.setPlainText(SCRIPT_TEXT)
    return dialog


def _wait_for_service_call(qtbot, calls: list[object], count: int = 1) -> None:
    qtbot.waitUntil(lambda: len(calls) >= count)


def _wait_for_build_idle(qtbot, dialog: ToolGenerateDialog) -> None:
    qtbot.waitUntil(lambda: not dialog._live_build_workers)


@pytest.mark.parametrize("editor_name", ["_manifest_edit", "_script_edit"])
def test_editing_source_invalidates_review_immediately(qtbot, editor_name: str):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._show_review(review, frozenset())
    editor = getattr(dialog, editor_name)

    editor.insertPlainText("\n# changed")

    assert dialog._current_review is None
    assert dialog._install_btn.isEnabled() is False
    assert dialog._install_reason_label.text().strip()
    assert dialog._review_panel._issues_edit.toPlainText() == ""


def test_hand_pasted_source_enables_review_without_prior_generation(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._manifest_edit.clear()
    dialog._script_edit.clear()
    assert dialog._save_btn.isEnabled() is False

    dialog._manifest_edit.setPlainText(MANIFEST_TEXT)
    dialog._script_edit.setPlainText(SCRIPT_TEXT)

    assert dialog._save_btn.isEnabled() is True

    dialog._script_edit.clear()

    assert dialog._save_btn.isEnabled() is False


def test_programmatic_generation_fill_does_not_mark_review_stale(qtbot):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    # Simulate a prior review so a stray invalidation would be observable.
    dialog._show_review(review, frozenset())

    # Programmatic fill uses signal blockers, so it must not fire the
    # source-changed invalidation that hand edits trigger.
    dialog._set_generated_sources(MANIFEST_TEXT, SCRIPT_TEXT)

    panel = dialog._review_panel
    assert dialog._current_review is None
    assert dialog._install_btn.isEnabled() is False
    assert dialog._install_reason_label.text().strip()
    assert t("tooldlg.review.source_changed") not in panel._summary_label.text()


def test_unknown_install_reason_redacts_untrusted_diagnostic_text(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))

    reason = dialog._reason_for_install_result("C:/private/workspace/token")

    assert "C:/private" not in reason
    assert "UNKNOWN" in reason


def test_initial_review_has_visible_disabled_install_reason(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    panel = dialog._review_panel

    # Before any generation the panel is cleared: install is disabled with a
    # visible, accessible reason and the "not generated" status prompt is shown.
    assert dialog._install_btn.isEnabled() is False
    reason = dialog._install_reason_label.text()
    assert reason.strip()
    assert reason in dialog._install_reason_label.accessibleName()
    assert panel._summary_label.text().strip()
    assert panel._summary_label.text() == panel._summary_label.accessibleDescription()


def test_stale_worker_events_do_not_overwrite_current_generation(qtbot, monkeypatch):
    workers: list[FakeGenerateWorker] = []

    def make_worker(requirement: str, model_override=None) -> FakeGenerateWorker:
        worker = FakeGenerateWorker(requirement, model_override)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.ui.tool_generate_dialog._GenerateWorker", make_worker)
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._req_edit.setPlainText("first")
    dialog._on_generate()
    dialog._req_edit.setPlainText("second")
    dialog._on_generate()

    first, second = workers
    first.chunk.emit("stale")
    first.result_ready.emit("stale result")
    first.error.emit("stale error")
    second.chunk.emit("current")

    assert first.stopped is True
    assert first in dialog._live_workers
    assert dialog._raw_edit.toPlainText() == "current"
    assert "stale" not in dialog._status_label.text()

    first.finish()

    assert first not in dialog._live_workers
    assert first.deleted is True


def test_close_defers_until_all_live_workers_finish(qtbot, monkeypatch):
    workers: list[FakeGenerateWorker] = []

    def make_worker(requirement: str, model_override=None) -> FakeGenerateWorker:
        worker = FakeGenerateWorker(requirement, model_override)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.ui.tool_generate_dialog._GenerateWorker", make_worker)
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._req_edit.setPlainText("blocking")
    dialog._on_generate()
    event = QCloseEvent()

    dialog.closeEvent(event)

    assert event.isAccepted() is False
    assert dialog._is_closing is True
    assert workers[0].stopped is True
    assert dialog._gen_btn.isEnabled() is False
    assert dialog._install_btn.isEnabled() is False

    workers[0].finish()

    assert dialog._is_closing is False
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_worker_stop_cancels_gateway_token_and_suppresses_stale_result(monkeypatch):
    captured = []
    worker_holder = {}

    def cancellable_stream(_requirement, _model_override, *, cancel_token):
        captured.append(cancel_token)
        yield {"type": "text", "delta": "first"}
        worker_holder["worker"].stop()
        yield {"type": "text", "delta": "stale"}

    monkeypatch.setattr("app.ui.tool_build_workers.stream_generate", cancellable_stream)
    worker = _GenerateWorker("requirement")
    worker_holder["worker"] = worker
    chunks: list[str] = []
    results: list[str] = []
    worker.chunk.connect(chunks.append)
    worker.result_ready.connect(results.append)
    worker.run()

    assert captured
    assert captured[0].is_cancelled() is True
    assert chunks == ["first"]
    assert results == []


def test_close_waiting_disables_install_with_visible_accessible_reason(qtbot, monkeypatch):
    workers: list[FakeGenerateWorker] = []

    def make_worker(requirement: str, model_override=None) -> FakeGenerateWorker:
        worker = FakeGenerateWorker(requirement, model_override)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.ui.tool_generate_dialog._GenerateWorker", make_worker)
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._show_review(_review(), frozenset())
    dialog._req_edit.setPlainText("blocking")
    dialog._on_generate()

    dialog.closeEvent(QCloseEvent())

    reason = dialog._install_reason_label.text()
    assert dialog._install_btn.isEnabled() is False
    assert reason.strip()
    assert "waiting" in reason.lower()
    assert "waiting" in dialog._review_panel._summary_label.accessibleDescription().lower()

    workers[0].finish()

    assert dialog.result() == QDialog.DialogCode.Rejected


def test_review_status_exposes_text_icon_color_and_dynamic_accessibility(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    panel = dialog._review_panel

    dialog._show_review(_review(), frozenset())
    ready_text = t("tooldlg.review.status.ready_simple", name="safe_tool")
    assert panel._status_icon.isVisibleTo(dialog)
    assert panel._summary_label.text() == ready_text
    assert panel._summary_label.accessibleName() == ready_text
    assert "color:" in panel._summary_label.styleSheet()

    blocking = ValidationIssue("BLOCKED", IssueSeverity.BLOCK, "Unsafe source detected")
    dialog._show_review(_review(blocking), frozenset())
    blocked_text = t("tooldlg.review.status.blocked_simple")
    assert panel._summary_label.text() == blocked_text
    assert panel._summary_label.accessibleName() == blocked_text
    assert panel._summary_label.accessibleDescription() == blocked_text
    assert "color:" in panel._summary_label.styleSheet()
    assert panel._issues_edit.isVisibleTo(dialog)
    assert "BLOCKED" in panel._issues_edit.toPlainText()


def test_actual_focus_chain_reaches_review_after_source_editor(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._show_review(_review(), frozenset())
    panel = dialog._review_panel

    # The compact panel wires summary -> issues -> install -> cancel. With no
    # blocking issues the hidden issues editor is skipped by keyboard focus.
    assert panel.focus_order == (
        panel._summary_label,
        panel._issues_edit,
        panel._install_btn,
        dialog._cancel_btn,
    )
    assert panel._summary_label.nextInFocusChain() is panel._issues_edit
    assert panel._install_btn.nextInFocusChain() is dialog._cancel_btn

    dialog.show()
    qtbot.waitExposed(dialog)
    dialog.raise_()
    dialog.activateWindow()
    qtbot.waitUntil(lambda: dialog.isActiveWindow(), timeout=1000)
    panel._summary_label.setFocus()
    QTest.keyClick(panel._summary_label, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is panel._install_btn


def test_critical_controls_have_accessible_names_and_logical_focus_order(qtbot):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._show_review(review, frozenset())
    panel = dialog._review_panel
    controls: list[QWidget] = [
        dialog._req_edit,
        dialog._model_combo,
        dialog._manifest_edit,
        dialog._script_edit,
        panel._summary_label,
        panel._issues_edit,
        panel._install_reason_label,
        panel._review_btn,
        panel._install_btn,
        dialog._cancel_btn,
    ]

    assert all(control.accessibleName().strip() for control in controls)
    assert panel.focus_order == (
        panel._summary_label,
        panel._issues_edit,
        panel._install_btn,
        dialog._cancel_btn,
    )


def _assert_disabled_state_is_accessible(dialog: ToolGenerateDialog, reason_fragment: str) -> None:
    panel = dialog._review_panel
    reason = panel._install_reason_label.text()
    summary = panel._summary_label.text()
    assert panel._install_btn.isEnabled() is False
    assert reason_fragment.lower() in reason.lower()
    assert reason in panel._install_reason_label.accessibleName()
    assert reason in panel._install_reason_label.accessibleDescription()
    assert reason in summary
    assert reason in panel._summary_label.accessibleName()
    assert reason in panel._summary_label.accessibleDescription()
    assert "color:" in panel._summary_label.styleSheet()


def test_cancel_button_escape_and_title_close_share_deferred_worker_shutdown(qtbot, monkeypatch):
    for close_action in ("cancel", "escape", "title"):
        workers: list[FakeGenerateWorker] = []

        def make_worker(requirement: str, model_override=None) -> FakeGenerateWorker:
            worker = FakeGenerateWorker(requirement, model_override)
            workers.append(worker)
            return worker

        monkeypatch.setattr("app.ui.tool_generate_dialog._GenerateWorker", make_worker)
        dialog = _dialog(qtbot, FakeToolBuildService(_review()))
        dialog.show()
        dialog._req_edit.setPlainText(close_action)
        dialog._on_generate()

        if close_action == "cancel":
            QTest.mouseClick(dialog._cancel_btn, Qt.MouseButton.LeftButton)
        elif close_action == "escape":
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        else:
            dialog.close()

        qtbot.waitUntil(lambda: dialog._is_closing)
        assert workers[0].stopped is True
        assert dialog.isVisible() is True
        assert workers[0] in dialog._live_workers
        assert dialog._req_edit.isEnabled() is False

        workers[0].finish()
        qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Rejected)


def test_real_qthread_finished_is_delivered_to_dialog_slot_on_gui_thread(qtbot, monkeypatch):
    class ThreadObservingDialog(ToolGenerateDialog):
        def __init__(self, *args, **kwargs) -> None:
            self.finished_delivery_thread: QThread | None = None
            super().__init__(*args, **kwargs)

        @pyqtSlot()
        def _on_worker_finished(self) -> None:
            self.finished_delivery_thread = QThread.currentThread()
            super()._on_worker_finished()

    worker = _GenerateWorker("requirement")
    monkeypatch.setattr(
        "app.ui.tool_build_workers.stream_generate",
        lambda *_args, **_kwargs: iter(()),
    )
    monkeypatch.setattr(
        "app.ui.tool_generate_dialog._GenerateWorker",
        lambda *_args, **_kwargs: worker,
    )
    dialog = ThreadObservingDialog(
        registry=ToolRegistry(),
        build_service=FakeToolBuildService(_review()),
    )
    qtbot.addWidget(dialog)
    dialog._req_edit.setPlainText("Build a local tool")

    dialog._on_generate()

    qtbot.waitUntil(lambda: worker not in dialog._live_workers)
    assert dialog.finished_delivery_thread is QApplication.instance().thread()


def test_disabled_state_accessibility_updates_for_source_changes(qtbot):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._show_review(review, frozenset())

    # Hand editing the source invalidates the review, disables install, and
    # reveals the review button with an accessible source-changed reason.
    dialog._manifest_edit.insertPlainText(" ")

    _assert_disabled_state_is_accessible(dialog, "source")
    assert dialog._review_panel._review_btn.isVisibleTo(dialog) is True


@pytest.mark.parametrize("failure_method", ["stage", "review"])
def test_stage_and_review_exceptions_replace_installable_summary_accessibly(
    qtbot, failure_method: str
):
    review = _review()
    service = FakeToolBuildService(review)
    dialog = _dialog(qtbot, service)
    dialog._show_review(review, frozenset())

    def fail(*_args, **_kwargs):
        raise OSError("private/path/details")

    setattr(service, failure_method, fail)
    if failure_method == "stage":
        dialog._on_save()
    else:
        dialog._review_current_build()
    _wait_for_build_idle(qtbot, dialog)

    _assert_disabled_state_is_accessible(dialog, "revalidation failed")
    assert "private/path" not in dialog._review_panel._summary_label.text()


@pytest.mark.parametrize("reason", ["REVIEW_REQUIRED", "STALE_VALIDATION", "VALIDATION_FAILED"])
def test_service_failure_reasons_replace_installable_summary_accessibly(qtbot, reason: str):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._show_review(review, frozenset())

    dialog._handle_install_result(InstallResult(False, "safe_tool", reason))

    _assert_disabled_state_is_accessible(dialog, dialog._reason_for_install_result(reason))


def test_closing_wait_replaces_installable_summary_and_reason_accessibly(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    dialog._show_review(_review(), frozenset())

    dialog._review_panel.mark_closing_wait()

    _assert_disabled_state_is_accessible(dialog, "waiting")


def test_initial_dialog_size_is_clamped_to_available_screen(qtbot, monkeypatch):
    from PyQt6.QtCore import QRect

    class SmallScreen:
        @staticmethod
        def availableGeometry() -> QRect:
            return QRect(0, 0, 700, 640)

    monkeypatch.setattr(QGuiApplication, "primaryScreen", lambda: SmallScreen())
    dialog = ToolGenerateDialog(
        registry=ToolRegistry(),
        build_service=FakeToolBuildService(_review()),
    )
    qtbot.addWidget(dialog)

    assert dialog.minimumWidth() <= 700
    assert dialog.minimumHeight() <= 640
    assert dialog.width() <= 700
    assert dialog.height() <= 640


def test_dialog_height_is_screen_bounded_and_review_content_scrolls(qtbot):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    screen_height = QApplication.primaryScreen().availableGeometry().height()

    assert dialog.minimumHeight() <= min(screen_height, 720)
    assert dialog.height() <= screen_height
    assert isinstance(dialog._review_scroll, QScrollArea)
    assert dialog._review_scroll.widget() is dialog._review_panel
    assert dialog._review_scroll.widgetResizable() is True
    dialog.resize(700, 600)
    dialog.show()
    qtbot.waitExposed(dialog)


class FakeGenerateWorker(QThread):
    chunk = pyqtSignal(str)
    result_ready = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, requirement: str, model_override=None) -> None:
        super().__init__()
        self.requirement = requirement
        self.model_override = model_override
        self.running = False
        self.stopped = False
        self.deleted = False

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.stopped = True

    def isRunning(self) -> bool:
        return self.running

    def deleteLater(self) -> None:
        self.deleted = True

    def finish(self) -> None:
        self.running = False
        self.finished.emit()


class _ExistingTool:
    name = "safe_tool"
    description = "existing"
    parameters: dict = {}
    read_only = True
    retry_safe = False
    enabled = True
    unavailable_reason = ""

    def execute(self, params):
        return {"status": "success", "data": {}}
