"""Final-review UI regressions for worker lifecycle and strict-tool boundaries."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from PyQt6.QtCore import QThread, Qt, pyqtSlot
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from app.core.tool_build import (
    BuildReview,
    BuildStatus,
    InstallResult,
    ToolManifest,
    ValidationReport,
)
from app.tools.registry import ToolRegistry
from app.tools.script_adapter import ScriptToolAdapter
from app.ui.tool_build_workers import _BuildWorker
from app.ui.toolbox_panel import _ToolCard, ToolboxPanel
from app.ui.tool_generate_dialog import ToolGenerateDialog

pytestmark = pytest.mark.ui


MANIFEST_TEXT = json.dumps(
    {
        "manifest_version": 1,
        "name": "safe_tool",
        "description": "safe",
        "script": "tool.py",
        "parameters": {},
        "output": {"type": "object"},
        "permissions": [],
        "dependencies": [],
    }
)


def _review(build_id: str = "build-1") -> BuildReview:
    manifest = ToolManifest(
        manifest_version=1,
        name="safe_tool",
        description="safe",
        script="tool.py",
        parameters={},
        output={"type": "object"},
        permissions=frozenset(),
        dependencies=(),
    )
    report = ValidationReport(
        build_id=build_id,
        status=BuildStatus.INSTALL_REVIEW,
        declared_permissions=frozenset(),
        detected_permissions=frozenset(),
        dependencies=(),
        file_hashes={"manifest.json": "a" * 64, "tool.py": "b" * 64},
        issues=(),
    )
    return BuildReview(build_id, manifest, "print('{}')", report)


class SlowService:
    def __init__(self, review: BuildReview) -> None:
        self.review_value = review
        self.install_entered = threading.Event()
        self.install_release = threading.Event()
        self.install_calls = 0

    def stage(
        self, requirement: str, manifest_text: str, script_text: str
    ) -> BuildReview:
        return self.review_value

    def review(
        self,
        build_id: str,
        approved_permissions: frozenset,
        *,
        acknowledged_overrides: frozenset = frozenset(),
    ) -> BuildReview:
        return self.review_value

    def install(
        self,
        build_id: str,
        approved_permissions: frozenset,
        *,
        overwrite: bool,
        acknowledged_overrides: frozenset = frozenset(),
    ) -> InstallResult:
        self.install_calls += 1
        self.install_entered.set()
        self.install_release.wait(2)
        return InstallResult(True, "safe_tool", "")


def _dialog(qtbot: pytest.QtBot, service: SlowService) -> ToolGenerateDialog:
    dialog = ToolGenerateDialog(ToolRegistry(), build_service=service)
    qtbot.addWidget(dialog)
    dialog._req_edit.setPlainText("req")
    dialog._name_edit.setText("safe_tool")
    dialog._manifest_edit.setPlainText(MANIFEST_TEXT)
    dialog._script_edit.setPlainText("print('{}')")
    dialog._show_review(service.review_value, frozenset())
    return dialog


def test_install_worker_remains_active_and_disables_all_mutating_controls(
    qtbot: pytest.QtBot,
) -> None:
    service = SlowService(_review())
    dialog = _dialog(qtbot, service)

    dialog._install_review(overwrite=False)
    qtbot.waitUntil(service.install_entered.is_set)
    worker = dialog._active_build_worker

    assert worker is not None
    assert dialog._active_build_operation == "install"
    for control in (
        dialog._gen_btn,
        dialog._regen_btn,
        dialog._toggle_code_btn,
        dialog._manifest_edit,
        dialog._script_edit,
        dialog._review_panel,
        dialog._cancel_btn,
    ):
        assert control.isEnabled() is False

    dialog._manifest_edit.setPlainText("changed")
    dialog._on_save()
    dialog._on_generate()
    dialog.reject()

    assert dialog._active_build_worker is worker
    assert service.install_calls == 1
    assert dialog._pending_result == QDialog.DialogCode.Rejected

    service.install_release.set()
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)


def test_successful_install_after_deferred_close_is_processed_exactly_once(
    qtbot: pytest.QtBot,
) -> None:
    service = SlowService(_review())
    dialog = _dialog(qtbot, service)
    saved: list[str] = []
    dialog.tool_saved.connect(saved.append)

    dialog._install_review(overwrite=False)
    qtbot.waitUntil(service.install_entered.is_set)
    dialog.reject()
    dialog.reject()
    service.install_release.set()

    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert saved == ["safe_tool"]
    assert service.install_calls == 1


def test_build_worker_error_and_result_paths_are_covered_without_base_exception_capture() -> None:
    runtime_errors: list[str] = []

    class Failing:
        def review(self, *_args: object) -> BuildReview:
            raise RuntimeError("private")

    worker = _BuildWorker(Failing(), 1, "review", ("build", frozenset()))
    worker.error.connect(lambda _token, _operation, reason: runtime_errors.append(reason))
    worker.run()
    assert runtime_errors == ["VALIDATION_FAILED"]

    passthrough: list[object] = []

    class Unknown:
        pass

    unknown = _BuildWorker(Unknown(), 2, "unknown", ())
    unknown.error.connect(lambda _token, _operation, reason: runtime_errors.append(reason))
    unknown.run()
    assert runtime_errors[-1] == "VALIDATION_FAILED"

    class StageService:
        def stage(self, *_args: object) -> BuildReview:
            return _review()

        def review(self, *_args: object) -> BuildReview:
            return _review()

    stage = _BuildWorker(StageService(), 3, "stage_review", ("req", "{}", "pass"))
    stage.result_ready.connect(lambda _token, _operation, result: passthrough.append(result))
    stage.run()
    assert isinstance(passthrough[-1], BuildReview)


def test_build_worker_runtime_error_is_redacted_and_visible(qtbot: pytest.QtBot) -> None:
    class FailingService(SlowService):
        def review(
            self,
            build_id: str,
            approved_permissions: frozenset,
            *,
            acknowledged_overrides: frozenset = frozenset(),
        ) -> BuildReview:
            raise RuntimeError("C:/private/generated/source")

    service = FailingService(_review())
    dialog = _dialog(qtbot, service)

    dialog._review_current_build()
    qtbot.waitUntil(lambda: not dialog._live_build_workers)

    summary = dialog._review_panel._summary_label.text()
    assert "revalidation failed" in summary.lower()
    assert "C:/private" not in summary


def test_real_build_qthread_delivers_result_and_finished_on_gui_thread(
    qtbot: pytest.QtBot,
) -> None:
    class ObservingDialog(ToolGenerateDialog):
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.result_thread: QThread | None = None
            self.finished_thread: QThread | None = None
            super().__init__(*args, **kwargs)

        @pyqtSlot(int, str, object)
        def _on_build_result(self, token: int, operation: str, result: object) -> None:
            self.result_thread = QThread.currentThread()
            super()._on_build_result(token, operation, result)

        @pyqtSlot()
        def _on_build_worker_finished(self) -> None:
            self.finished_thread = QThread.currentThread()
            super()._on_build_worker_finished()

    class ImmediateService(SlowService):
        def install(
            self,
            build_id: str,
            approved_permissions: frozenset,
            *,
            overwrite: bool,
            acknowledged_overrides: frozenset = frozenset(),
        ) -> InstallResult:
            return InstallResult(True, "safe_tool", "")

    service = ImmediateService(_review())
    dialog = ObservingDialog(ToolRegistry(), build_service=service)
    qtbot.addWidget(dialog)
    dialog._show_review(service.review_value, frozenset())

    dialog._install_review(overwrite=False)
    qtbot.waitUntil(lambda: dialog.result() == QDialog.DialogCode.Accepted)

    gui_thread = QApplication.instance().thread()
    assert dialog.result_thread is gui_thread
    assert dialog.finished_thread is gui_thread


def _adapter(tmp_path: Path, *, legacy: bool) -> ScriptToolAdapter:
    tool_dir = tmp_path / ("legacy" if legacy else "strict")
    tool_dir.mkdir()
    (tool_dir / "manifest.json").write_text(MANIFEST_TEXT, encoding="utf-8")
    (tool_dir / "tool.py").write_text("print('{}')", encoding="utf-8")
    return ScriptToolAdapter(
        tool_name="legacy_tool" if legacy else "strict_tool",
        tool_description="tool",
        tool_parameters={},
        script_path=str(tool_dir / "tool.py"),
        tool_dir=str(tool_dir),
        is_legacy_manifest=legacy,
    )


def test_strict_tool_edit_is_blocked_without_opening_legacy_editor_or_writing_manifest(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ToolRegistry()
    strict = _adapter(tmp_path, legacy=False)
    registry.register(strict)
    panel = ToolboxPanel(registry)
    qtbot.addWidget(panel)
    panel._current_tool = strict
    manifest_path = Path(strict.tool_dir) / "manifest.json"
    before = manifest_path.read_bytes()
    opened = False

    class ForbiddenEditor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal opened
            opened = True

    monkeypatch.setattr("app.ui.tool_editor_dialog.ToolEditorDialog", ForbiddenEditor)

    panel._on_edit()

    assert opened is False
    assert manifest_path.read_bytes() == before
    assert panel._detail_pane._edit_btn.isEnabled() is False
    assert panel._detail_pane._edit_btn.toolTip().strip()


def test_legacy_tool_keeps_direct_editor_behavior(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = ToolRegistry()
    legacy = _adapter(tmp_path, legacy=True)
    registry.register(legacy)
    panel = ToolboxPanel(registry)
    qtbot.addWidget(panel)
    panel._current_tool = legacy
    opened = 0

    class FakeEditor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            nonlocal opened
            opened += 1

        def exec(self) -> int:
            return 0

    monkeypatch.setattr("app.ui.tool_editor_dialog.ToolEditorDialog", FakeEditor)

    panel._on_edit()

    assert opened == 1


def test_status_toggle_is_keyboard_accessible_and_not_color_only(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    tool = _adapter(tmp_path, legacy=True)
    card = _ToolCard(tool, switchable=True)
    qtbot.addWidget(card)
    card.show()
    qtbot.waitExposed(card)
    toggle = card._toggle
    assert toggle is not None
    emitted: list[tuple[str, bool]] = []
    card.toggled.connect(lambda name, enabled: emitted.append((name, enabled)))

    assert toggle.minimumWidth() >= 24
    assert toggle.minimumHeight() >= 24
    assert toggle.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert tool.name in toggle.accessibleName()
    assert "enabled" in toggle.accessibleName().lower()
    assert toggle.accessibleDescription().strip()

    toggle.setFocus()
    QTest.keyClick(toggle, Qt.Key.Key_Space)
    assert emitted == [(tool.name, False)]
    assert "disabled" in toggle.accessibleName().lower()

    QTest.keyClick(toggle, Qt.Key.Key_Return)
    assert emitted[-1] == (tool.name, True)
