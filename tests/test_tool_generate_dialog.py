"""UI contract tests for staged review and explicit generated-tool installation."""
from __future__ import annotations

import inspect
import json
import threading
from dataclasses import replace

import pytest
from PyQt6.QtCore import QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog, QMessageBox, QScrollArea, QWidget

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
        self.review_calls: list[tuple[str, frozenset[ToolPermission], frozenset[str]]] = []
        self.install_calls: list[tuple[str, frozenset[ToolPermission], bool, frozenset[str]]] = []

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


def test_generate_worker_streams_text_and_reports_provider_error(monkeypatch):
    worker = _GenerateWorker("requirement")
    chunks: list[str] = []
    completed: list[str] = []
    errors: list[str] = []
    worker.chunk.connect(chunks.append)
    worker.result_ready.connect(completed.append)
    worker.error.connect(errors.append)
    monkeypatch.setattr(
        "app.ui.tool_build_workers.stream_generate",
        lambda *_args, **_kwargs: iter(
            [
                {"type": "text", "delta": "first"},
                {"type": "text", "delta": " second"},
            ]
        ),
    )

    worker.run()

    assert chunks == ["first", " second"]
    assert completed == ["first second"]
    assert errors == []


def test_generate_worker_stops_after_provider_error(monkeypatch):
    worker = _GenerateWorker("requirement")
    completed: list[str] = []
    errors: list[str] = []
    worker.result_ready.connect(completed.append)
    worker.error.connect(errors.append)
    monkeypatch.setattr(
        "app.ui.tool_build_workers.stream_generate",
        lambda *_args, **_kwargs: iter([{"type": "error", "message": "offline"}]),
    )

    worker.run()

    assert completed == []
    assert errors == ["offline"]


def test_finished_parse_error_keeps_install_disabled(qtbot, monkeypatch):
    dialog = _dialog(qtbot, FakeToolBuildService(_review()))
    monkeypatch.setattr(
        "app.ui.tool_generate_dialog.parse_result",
        lambda _text: ("", "", "invalid response"),
    )

    dialog._on_finished("not valid")

    assert "invalid response" in dialog._status_label.text()
    assert dialog._install_btn.isEnabled() is False


def test_finished_populates_editors_and_derives_name_then_auto_reviews(qtbot, monkeypatch):
    service = FakeToolBuildService(_review())
    dialog = _dialog(qtbot, service)
    monkeypatch.setattr(
        "app.ui.tool_generate_dialog.parse_result",
        lambda _text: (MANIFEST_TEXT, SCRIPT_TEXT, ""),
    )

    dialog._on_finished("valid")
    _wait_for_build_idle(qtbot, dialog)

    # The name is derived from the manifest and staging runs automatically.
    assert json.loads(dialog._manifest_edit.toPlainText())["name"] == "safe_tool"
    assert dialog._script_edit.toPlainText() == SCRIPT_TEXT
    assert dialog._name_edit.text() == "safe_tool"
    assert dialog._toggle_code_btn.isEnabled() is True
    assert dialog._current_review is not None


def test_build_service_is_injected_and_review_uses_current_editor_text(qtbot):
    review = _review()
    service = FakeToolBuildService(review)
    dialog = _dialog(qtbot, service)

    dialog._on_save()
    qtbot.waitUntil(lambda: bool(service.review_calls))

    assert dialog._build_service is service
    requirement, manifest_text, script_text = service.stage_calls[0]
    assert requirement == "Build a local tool"
    assert json.loads(manifest_text)["name"] == "safe_tool"
    assert script_text == SCRIPT_TEXT
    assert service.review_calls == [("build-1", frozenset(), frozenset())]


def test_stage_review_and_install_run_off_gui_thread_while_heartbeat_continues(qtbot):
    review = _review()
    gui_thread_id = threading.get_ident()
    entered = threading.Event()
    release = threading.Event()
    service_threads = []

    class SlowService(FakeToolBuildService):
        def stage(self, requirement, manifest_text, script_text):
            service_threads.append(threading.get_ident())
            entered.set()
            release.wait(1)
            return super().stage(requirement, manifest_text, script_text)

        def review(self, build_id, approved_permissions, *, acknowledged_overrides=frozenset()):
            service_threads.append(threading.get_ident())
            return super().review(
                build_id, approved_permissions, acknowledged_overrides=acknowledged_overrides
            )

        def install(self, build_id, approved_permissions, *, overwrite, acknowledged_overrides=frozenset()):
            service_threads.append(threading.get_ident())
            return super().install(
                build_id,
                approved_permissions,
                overwrite=overwrite,
                acknowledged_overrides=acknowledged_overrides,
            )

    service = SlowService(review)
    dialog = _dialog(qtbot, service)
    heartbeat = []

    dialog._on_save()
    qtbot.waitUntil(entered.is_set)
    QApplication.processEvents()
    heartbeat.append("alive")
    assert heartbeat == ["alive"]
    assert dialog._save_btn.isEnabled() is False

    release.set()
    qtbot.waitUntil(lambda: dialog._current_review is not None)
    dialog._install_review(overwrite=False)
    qtbot.waitUntil(lambda: bool(service.install_calls))
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)

    assert all(thread_id != gui_thread_id for thread_id in service_threads)
    assert len(service_threads) == 3


def test_stale_build_operation_result_is_ignored(qtbot):
    first_release = threading.Event()
    call_count = 0

    class OrderedService(FakeToolBuildService):
        def stage(self, requirement, manifest_text, script_text):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                first_release.wait(1)
                return replace(super().stage(requirement, manifest_text, script_text), build_id="old")
            return replace(super().stage(requirement, manifest_text, script_text), build_id="new")

        def review(self, build_id, approved_permissions, *, acknowledged_overrides=frozenset()):
            value = super().review(
                build_id, approved_permissions, acknowledged_overrides=acknowledged_overrides
            )
            return replace(value, build_id=build_id, report=replace(value.report, build_id=build_id))

    service = OrderedService(_review())
    dialog = _dialog(qtbot, service)
    dialog._on_save()
    qtbot.waitUntil(lambda: call_count == 1)
    dialog._invalidate_build_operation()
    first_release.set()
    qtbot.waitUntil(lambda: not dialog._live_build_workers)
    assert dialog._staged_build_id != "old"

    dialog._on_save()
    qtbot.waitUntil(lambda: dialog._staged_build_id == "new")

    assert dialog._staged_build_id == "new"


def test_close_defers_until_live_build_worker_finishes(qtbot):
    entered = threading.Event()
    release = threading.Event()

    class SlowService(FakeToolBuildService):
        def stage(self, requirement, manifest_text, script_text):
            entered.set()
            release.wait(1)
            return super().stage(requirement, manifest_text, script_text)

    dialog = _dialog(qtbot, SlowService(_review()))
    dialog._on_save()
    qtbot.waitUntil(entered.is_set)

    dialog.reject()

    assert dialog._is_closing is True
    assert dialog._pending_result == QDialog.DialogCode.Rejected
    release.set()
    qtbot.waitUntil(lambda: not dialog._live_build_workers)
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog._live_build_workers


def test_generate_dialog_has_no_user_tools_direct_write_path():
    import app.ui.tool_generate_dialog as module

    source = inspect.getsource(module)

    assert "USER_TOOLS_DIR" not in source
    assert ".mkdir(" not in source
    assert "open(tool_dir" not in source


def test_blocking_review_disables_install_and_shows_visible_reason(qtbot):
    blocking = ValidationIssue("BLOCKED", IssueSeverity.BLOCK, "Unsafe source detected")
    review = _review(blocking)
    dialog = _dialog(qtbot, FakeToolBuildService(review))

    dialog._show_review(review, frozenset())

    assert dialog._install_btn.isEnabled() is False
    assert dialog._install_reason_label.isVisibleTo(dialog)
    assert dialog._install_reason_label.text().strip()
    assert dialog._review_panel._summary_label.text().strip()
    assert dialog._review_panel._summary_label.accessibleDescription().strip()
    assert "Unsafe source detected" in dialog._review_panel._issues_edit.toPlainText()
    assert dialog._review_panel._issues_edit.isVisibleTo(dialog)


def _wait_for_service_call(qtbot, calls, count: int = 1) -> None:
    qtbot.waitUntil(lambda: len(calls) >= count)


def _wait_for_build_idle(qtbot, dialog: ToolGenerateDialog) -> None:
    qtbot.waitUntil(lambda: not dialog._live_build_workers)


def test_warning_requires_positive_confirmation_before_install(qtbot, monkeypatch):
    warning = ValidationIssue("CAUTION", IssueSeverity.WARNING, "Review this behavior")
    review = _review(warning)
    service = FakeToolBuildService(review)
    dialog = _dialog(qtbot, service)
    dialog._show_review(review, frozenset())
    answers = iter(
        [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: next(answers))

    dialog._install_review(overwrite=False)

    assert service.install_calls == []
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, service.install_calls)
    _wait_for_build_idle(qtbot, dialog)

    assert service.install_calls == [("build-1", frozenset(), False, frozenset())]


def test_overwrite_requires_explicit_confirmation_and_defaults_to_cancel(qtbot, monkeypatch):
    review = _review()
    service = FakeToolBuildService(review)
    registry = ToolRegistry()
    registry.register(_ExistingTool())
    dialog = _dialog(qtbot, service, registry)
    dialog._show_review(review, frozenset())
    captured_defaults: list[QMessageBox.StandardButton] = []
    answers = iter(
        [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    )

    def answer(*args, **kwargs):
        captured_defaults.append(args[4] if len(args) > 4 else kwargs["defaultButton"])
        return next(answers)

    monkeypatch.setattr(QMessageBox, "question", answer)

    dialog._install_review()

    assert service.install_calls == []
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._install_review()
    _wait_for_service_call(qtbot, service.install_calls)
    _wait_for_build_idle(qtbot, dialog)

    assert captured_defaults == [
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ]
    assert service.install_calls == [("build-1", frozenset(), True, frozenset())]


def test_name_conflict_from_service_requires_confirmation_before_overwrite_retry(
    qtbot, monkeypatch
):
    review = _review()
    service = FakeToolBuildService(
        review,
        install_results=[
            InstallResult(False, "safe_tool", "NAME_CONFLICT"),
            InstallResult(False, "safe_tool", "NAME_CONFLICT"),
            InstallResult(True, "safe_tool", ""),
        ],
    )
    dialog = _dialog(qtbot, service)
    dialog._show_review(review, frozenset())
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: next(answers)
    )

    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, service.install_calls)
    _wait_for_build_idle(qtbot, dialog)

    assert service.install_calls == [("build-1", frozenset(), False, frozenset())]
    assert dialog.result() != QDialog.DialogCode.Accepted

    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, service.install_calls, 3)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)

    assert service.install_calls == [
        ("build-1", frozenset(), False, frozenset()),
        ("build-1", frozenset(), False, frozenset()),
        ("build-1", frozenset(), True, frozenset()),
    ]
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_successful_install_uses_review_identity_emits_once_and_accepts(qtbot):
    review = _review()
    service = FakeToolBuildService(review)
    dialog = _dialog(qtbot, service)
    dialog._show_review(review, frozenset())
    emitted: list[str] = []
    dialog.tool_saved.connect(emitted.append)

    dialog._install_review(overwrite=False)
    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, service.install_calls)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)

    assert service.install_calls == [("build-1", frozenset(), False, frozenset())]
    assert emitted == ["safe_tool"]
    assert dialog.result() == QDialog.DialogCode.Accepted




def test_successful_install_waits_for_live_workers_before_accepting(qtbot, monkeypatch):
    workers: list[FakeGenerateWorker] = []

    def make_worker(requirement: str, model_override=None) -> FakeGenerateWorker:
        worker = FakeGenerateWorker(requirement, model_override)
        workers.append(worker)
        return worker

    monkeypatch.setattr("app.ui.tool_generate_dialog._GenerateWorker", make_worker)
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._req_edit.setPlainText("first generation")
    dialog._on_generate()
    dialog._show_review(review, frozenset())
    emitted: list[str] = []
    dialog.tool_saved.connect(emitted.append)

    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, dialog._build_service.install_calls)
    _wait_for_build_idle(qtbot, dialog)
    dialog.reject()

    assert workers[0].stopped is True
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog._pending_result == QDialog.DialogCode.Accepted
    assert emitted == ["safe_tool"]

    workers[0].finish()

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert emitted == ["safe_tool"]


def test_successful_install_without_live_worker_accepts_immediately(qtbot):
    review = _review()
    dialog = _dialog(qtbot, FakeToolBuildService(review))
    dialog._show_review(review, frozenset())

    dialog._install_review(overwrite=False)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)

    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog._pending_result is None


@pytest.mark.parametrize("reason", ["REVIEW_REQUIRED", "STALE_VALIDATION", "VALIDATION_FAILED"])
def test_install_review_failure_preserves_report_and_requires_rereview(
    qtbot, reason: str
):
    review = _review()
    service = FakeToolBuildService(
        review,
        InstallResult(False, "safe_tool", reason),
    )
    dialog = _dialog(qtbot, service)
    dialog._show_review(review, frozenset())
    emitted: list[str] = []
    dialog.tool_saved.connect(emitted.append)

    dialog._install_review(overwrite=False)
    _wait_for_service_call(qtbot, service.install_calls)
    _wait_for_build_idle(qtbot, dialog)

    assert emitted == []
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog._review_panel.isVisibleTo(dialog)
    assert dialog._install_btn.isEnabled() is False
    assert dialog._install_reason_label.text().strip()
    assert dialog._review_btn.isEnabled() is True


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
