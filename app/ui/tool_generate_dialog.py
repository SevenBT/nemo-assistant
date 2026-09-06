"""Dialog for AI-assisted tool generation, review, and explicit installation."""
from __future__ import annotations

import json
import re

from PyQt6.QtCore import QSignalBlocker, QThread, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QCloseEvent, QGuiApplication
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PrimaryPushButton, PushButton, ScrollArea

from app.core.tool_build import (
    BuildReview,
    InstallResult,
    IssueSeverity,
    ToolBuildService,
    ToolPermission,
)
from app.core.tool_generator import ModelOverride, build_model_options, parse_result
from app.i18n import t
from app.tools.registry import ToolRegistry
from app.ui.tool_build_review_dialog import ToolBuildReviewPanel
from app.ui.tool_build_workers import (
    ToolBuildServiceProtocol,
    _BuildWorker,
    _GenerateWorker,
)

_REVIEW_AGAIN_REASONS = frozenset(
    {"REVIEW_REQUIRED", "STALE_VALIDATION", "VALIDATION_FAILED"}
)
_KNOWN_INSTALL_REASON_KEYS = {
    "REVIEW_REQUIRED": "tooldlg.review.install_reason.REVIEW_REQUIRED",
    "STALE_VALIDATION": "tooldlg.review.install_reason.STALE_VALIDATION",
    "VALIDATION_FAILED": "tooldlg.review.install_reason.VALIDATION_FAILED",
    "NAME_CONFLICT": "tooldlg.review.install_reason.NAME_CONFLICT",
    "WORKSPACE_INVALID": "tooldlg.review.install_reason.WORKSPACE_INVALID",
    "RESERVED_NAME": "tooldlg.review.install_reason.RESERVED_NAME",
    "INVALID_INPUT": "tooldlg.review.install_reason.INVALID_INPUT",
    "INSTALL_FAILED": "tooldlg.review.install_reason.INSTALL_FAILED",
}


class ToolGenerateDialog(QDialog):
    """AI-powered generation with isolated worker lifecycles and explicit install."""

    tool_saved = pyqtSignal(str)

    def __init__(
        self,
        registry: ToolRegistry,
        parent: QWidget | None = None,
        build_service: ToolBuildServiceProtocol | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry = registry
        self._build_service: ToolBuildServiceProtocol = build_service or ToolBuildService()
        self._active_worker: _GenerateWorker | None = None
        self._live_workers: set[_GenerateWorker] = set()
        self._worker_tokens: dict[_GenerateWorker, int] = {}
        self._generation_token = 0
        self._build_operation_token = 0
        self._active_build_worker: _BuildWorker | None = None
        self._active_build_operation: str | None = None
        self._live_build_workers: set[_BuildWorker] = set()
        self._queued_build_operation: tuple[str, tuple[object, ...]] | None = None
        self._pending_install_context: tuple[
            BuildReview, frozenset[ToolPermission], bool, frozenset[str]
        ] | None = None
        self._is_closing = False
        self._pending_result: QDialog.DialogCode | None = None
        self._full_text = ""
        self._current_review: BuildReview | None = None
        self._staged_build_id: str | None = None
        self._install_completed = False
        self._is_setting_sources = False
        self.setWindowTitle(t("tooldlg.gen.title"))
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.setMinimumSize(
                min(640, available.width()),
                min(480, available.height()),
            )
            self.resize(
                min(760, available.width()),
                min(760, available.height()),
            )
        else:
            self.setMinimumSize(640, 480)
            self.resize(760, 720)
        self.setModal(True)
        self._build()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self._build_requirement_controls(layout)
        self._build_source_editors(layout)
        self._build_review_controls(layout)
        self._build_actions(layout)
        self._manifest_edit.textChanged.connect(self._invalidate_review)
        self._script_edit.textChanged.connect(self._invalidate_review)
        self._set_end_to_end_focus_chain()

    def _build_requirement_controls(self, layout: QVBoxLayout) -> None:
        requirement_label = QLabel(t("tooldlg.gen.req_label"))
        self._req_edit = QTextEdit()
        self._req_edit.setAccessibleName(t("tooldlg.gen.a11y.requirement"))
        self._req_edit.setPlaceholderText(t("tooldlg.gen.req_ph"))
        self._req_edit.setMaximumHeight(90)
        requirement_label.setBuddy(self._req_edit)
        layout.addWidget(requirement_label)
        layout.addWidget(self._req_edit)

        model_row = QHBoxLayout()
        model_label = QLabel(t("tooldlg.gen.model"))
        self._model_combo = QComboBox()
        self._model_combo.setAccessibleName(t("tooldlg.gen.a11y.model"))
        self._model_combo.setMinimumWidth(260)
        model_label.setBuddy(self._model_combo)
        self._model_options: list[ModelOverride] = build_model_options()
        for option in self._model_options:
            self._model_combo.addItem(option.label)
        model_row.addWidget(model_label)
        model_row.addWidget(self._model_combo)
        model_row.addStretch()
        layout.addLayout(model_row)

        generation_row = QHBoxLayout()
        self._gen_btn = PrimaryPushButton(t("tooldlg.gen.generate"))
        self._gen_btn.setAccessibleName(t("tooldlg.gen.a11y.generate"))
        self._gen_btn.clicked.connect(self._on_generate)
        generation_row.addWidget(self._gen_btn)
        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setAccessibleName(t("tooldlg.gen.a11y.status"))
        generation_row.addWidget(self._status_label)
        generation_row.addStretch()
        layout.addLayout(generation_row)

    def _build_source_editors(self, layout: QVBoxLayout) -> None:
        self._toggle_code_btn = PushButton(t("tooldlg.gen.show_code"))
        self._toggle_code_btn.setAccessibleName(t("tooldlg.gen.a11y.toggle_code"))
        self._toggle_code_btn.setEnabled(False)
        self._toggle_code_btn.clicked.connect(self._toggle_code)
        toggle_row = QHBoxLayout()
        toggle_row.addWidget(self._toggle_code_btn)
        toggle_row.addStretch()
        layout.addLayout(toggle_row)

        self._tabs = QTabWidget()
        self._manifest_edit = self._source_editor(
            "tooldlg.gen.a11y.manifest", "tooldlg.gen.manifest_ph", 12
        )
        self._tabs.addTab(self._manifest_edit, "manifest.json")
        self._script_edit = self._source_editor(
            "tooldlg.gen.a11y.script", "tooldlg.gen.script_ph", 12
        )
        self._tabs.addTab(self._script_edit, "tool.py")
        self._raw_edit = self._source_editor(
            "tooldlg.gen.a11y.raw", "tooldlg.gen.raw_ph", 11
        )
        self._raw_edit.setReadOnly(True)
        self._tabs.addTab(self._raw_edit, t("tooldlg.gen.raw_tab"))
        self._tabs.setMaximumHeight(240)
        self._tabs.setVisible(False)
        layout.addWidget(self._tabs)

        # Internal-only state kept off-screen: the tool name is derived from the
        # manifest and staging is auto-triggered, so neither needs a control.
        self._name_edit = QLineEdit()
        self._name_edit.setVisible(False)
        self._save_btn = PushButton()
        self._save_btn.setVisible(False)
        self._save_btn.clicked.connect(self._on_save)

    def _toggle_code(self) -> None:
        show = not self._tabs.isVisible()
        self._tabs.setVisible(show)
        self._toggle_code_btn.setText(
            t("tooldlg.gen.hide_code" if show else "tooldlg.gen.show_code")
        )

    def _build_review_controls(self, layout: QVBoxLayout) -> None:
        self._review_panel = ToolBuildReviewPanel(self)
        self._review_panel.review_requested.connect(self._review_current_build)
        self._review_panel.install_requested.connect(self._install_review)
        self._review_panel.approvals_changed.connect(self._approval_changed)
        self._review_panel.auto_declare_requested.connect(self._approval_changed)
        self._review_scroll = ScrollArea(self)
        self._review_scroll.setWidgetResizable(True)
        self._review_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._review_scroll.setAccessibleName(t("tooldlg.review.a11y.scroll"))
        self._review_scroll.setWidget(self._review_panel)
        layout.addWidget(self._review_scroll, 1)
        self._install_btn = self._review_panel._install_btn
        self._review_btn = self._review_panel._review_btn
        self._install_reason_label = self._review_panel._install_reason_label

    def _build_actions(self, layout: QVBoxLayout) -> None:
        bottom = QHBoxLayout()
        self._regen_btn = PushButton(t("tooldlg.gen.regenerate"))
        self._regen_btn.setAccessibleName(t("tooldlg.gen.a11y.regenerate"))
        self._regen_btn.setEnabled(False)
        self._regen_btn.clicked.connect(self._on_generate)
        bottom.addWidget(self._regen_btn)
        bottom.addStretch()
        self._cancel_btn = PushButton(t("common.cancel"))
        self._cancel_btn.setAccessibleName(t("tooldlg.gen.a11y.cancel"))
        self._cancel_btn.clicked.connect(self._request_reject)
        bottom.addWidget(self._cancel_btn)
        layout.addLayout(bottom)
        self._review_panel.set_focus_chain(self._cancel_btn)

    def _set_end_to_end_focus_chain(self) -> None:
        self._review_panel.set_focus_chain(self._cancel_btn)

    def _source_editor(
        self, accessible_key: str, placeholder_key: str, font_size: int
    ) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setAccessibleName(t(accessible_key))
        editor.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; "
            f"font-size: {font_size}px;"
        )
        editor.setPlaceholderText(t(placeholder_key))
        return editor

    def _on_generate(self) -> None:
        if (
            self._is_closing
            or self._pending_result is not None
            or self._active_build_worker is not None
        ):
            return
        requirement = self._req_edit.toPlainText().strip()
        if not requirement:
            QMessageBox.warning(self, t("tooldlg.gen.tip_title"), t("tooldlg.gen.tip_no_req"))
            return
        self._stop_active_worker()
        self._generation_token += 1
        token = self._generation_token
        self._prepare_generation_ui()
        index = self._model_combo.currentIndex()
        model_override = self._model_options[index] if self._model_options else None
        worker = _GenerateWorker(requirement, model_override)
        self._active_worker = worker
        self._live_workers.add(worker)
        self._worker_tokens[worker] = token
        worker.chunk.connect(self._on_worker_chunk)
        worker.result_ready.connect(self._on_worker_result)
        worker.error.connect(self._on_worker_error)
        worker.finished.connect(self._on_worker_finished)
        worker.start()

    def _stop_active_worker(self) -> None:
        if self._active_worker is not None and self._active_worker.isRunning():
            self._active_worker.stop()

    def _prepare_generation_ui(self) -> None:
        self._full_text = ""
        self._raw_edit.clear()
        self._set_generated_sources("", "")
        self._name_edit.clear()
        self._save_btn.setEnabled(False)
        self._toggle_code_btn.setEnabled(False)
        self._regen_btn.setEnabled(False)
        self._gen_btn.setEnabled(False)
        self._set_status("tooldlg.gen.status_generating", "#9CA3AF")
        self._tabs.setCurrentIndex(2)

    def _is_current_worker(self, worker: _GenerateWorker, token: int) -> bool:
        return (
            not self._is_closing
            and worker is self._active_worker
            and token == self._generation_token
            and self._worker_tokens.get(worker) == token
        )

    def _signal_worker(self) -> tuple[_GenerateWorker, int] | None:
        sender = self.sender()
        worker = next(
            (candidate for candidate in self._worker_tokens if candidate is sender),
            None,
        )
        if worker is None:
            return None
        return worker, self._worker_tokens[worker]

    @pyqtSlot(str)
    def _on_worker_chunk(self, delta: str) -> None:
        worker_entry = self._signal_worker()
        if worker_entry is None:
            return
        worker, token = worker_entry
        if self._is_current_worker(worker, token):
            self._on_chunk(delta)

    @pyqtSlot(str)
    def _on_worker_result(self, text: str) -> None:
        worker_entry = self._signal_worker()
        if worker_entry is None:
            return
        worker, token = worker_entry
        if self._is_current_worker(worker, token):
            self._on_finished(text)

    @pyqtSlot(str)
    def _on_worker_error(self, message: str) -> None:
        worker_entry = self._signal_worker()
        if worker_entry is None:
            return
        worker, token = worker_entry
        if self._is_current_worker(worker, token):
            self._on_error(message)

    @pyqtSlot()
    def _on_worker_finished(self) -> None:
        sender = self.sender()
        worker = next(
            (candidate for candidate in self._live_workers if candidate is sender),
            None,
        )
        if worker is None:
            return
        self._live_workers.discard(worker)
        self._worker_tokens.pop(worker, None)
        if worker is self._active_worker:
            self._active_worker = None
        worker.deleteLater()
        if self._pending_result is not None:
            self._complete_pending_result_if_ready()

    def _on_chunk(self, delta: str) -> None:
        self._full_text += delta
        self._raw_edit.insertPlainText(delta)
        scrollbar = self._raw_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_finished(self, full_text: str) -> None:
        self._gen_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        manifest_text, script_text, error = parse_result(full_text)
        if error:
            self._set_status_text(t("tooldlg.gen.status_parse_error", error=error), "#F87171")
            return
        self._set_generated_sources(manifest_text, script_text)
        try:
            name = json.loads(manifest_text).get("name", "")
            self._name_edit.setText(name)
        except (json.JSONDecodeError, AttributeError):
            pass
        self._toggle_code_btn.setEnabled(True)
        self._tabs.setCurrentIndex(0)
        self._set_status("tooldlg.gen.status_validating", "#9CA3AF")
        # Auto-stage and validate: the user no longer clicks a review step.
        self._on_save()

    def _set_generated_sources(self, manifest_text: str, script_text: str) -> None:
        self._is_setting_sources = True
        manifest_blocker = QSignalBlocker(self._manifest_edit)
        script_blocker = QSignalBlocker(self._script_edit)
        try:
            self._manifest_edit.setPlainText(manifest_text)
            self._script_edit.setPlainText(script_text)
        finally:
            del manifest_blocker, script_blocker
            self._is_setting_sources = False
        self._current_review = None
        self._staged_build_id = None
        self._review_panel.clear()

    def _on_error(self, message: str) -> None:
        self._gen_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        self._set_status_text(t("tooldlg.gen.status_generation_error", error=message), "#F87171")

    def _on_save(self) -> None:
        if self._pending_result is not None or self._active_build_worker is not None:
            return
        prepared = self._prepared_source()
        if prepared is None:
            return
        manifest_text, script_text = prepared
        self._start_build_operation(
            "stage_review",
            (
                self._req_edit.toPlainText().strip(),
                manifest_text,
                script_text,
            ),
        )

    def _prepared_source(self) -> tuple[str, str] | None:
        manifest_text = self._manifest_edit.toPlainText().strip()
        script_text = self._script_edit.toPlainText().strip()
        try:
            manifest = json.loads(manifest_text)
            if not isinstance(manifest, dict):
                raise ValueError(t("tooldlg.gen.err_manifest_object"))
        except (json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(
                self, t("tooldlg.gen.err_title"), t("tooldlg.gen.err_bad_manifest", err=exc)
            )
            return None
        # The name lives in the manifest; the field is hidden and only tracks it.
        name = str(manifest.get("name", "")).strip()
        self._name_edit.setText(name)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            self._warn("tooldlg.gen.err_bad_name")
            return None
        manifest["name"] = name
        normalized = json.dumps(manifest, ensure_ascii=False, indent=2)
        if normalized != self._manifest_edit.toPlainText():
            self._is_setting_sources = True
            blocker = QSignalBlocker(self._manifest_edit)
            try:
                self._manifest_edit.setPlainText(normalized)
            finally:
                del blocker
                self._is_setting_sources = False
        return normalized, script_text

    def _show_review(
        self, review: BuildReview, approved_permissions: frozenset[ToolPermission]
    ) -> None:
        self._current_review = review
        self._staged_build_id = review.build_id
        self._review_panel.set_review(review, approved_permissions)
        self._save_btn.setEnabled(True)
        if review.report.is_installable:
            self._set_status("tooldlg.gen.status_ready", "#34D399")
        else:
            self._set_status("tooldlg.gen.status_has_issues", "#F87171")
        self._set_end_to_end_focus_chain()

    def _review_current_build(self) -> None:
        if self._pending_result is not None or self._active_build_worker is not None:
            return
        if self._staged_build_id is None:
            self._on_save()
            return
        approvals = self._review_panel.approved_permissions
        overrides = self._review_panel.acknowledged_overrides()
        self._start_build_operation(
            "review", (self._staged_build_id, approvals, overrides)
        )

    def _approval_changed(self) -> None:
        if self._pending_result is not None or self._staged_build_id is None:
            return
        self._current_review = None
        self._review_panel.mark_requires_review(
            t("tooldlg.review.permissions_changed"), clear_report=False
        )

    def _invalidate_review(self) -> None:
        if (
            self._pending_result is not None
            or self._is_setting_sources
            or self._active_build_operation == "install"
        ):
            return
        self._invalidate_build_operation()
        had_review = self._current_review is not None or self._staged_build_id is not None
        self._current_review = None
        self._staged_build_id = None
        if had_review:
            self._review_panel.mark_requires_review(
                t("tooldlg.review.source_changed"), clear_report=True
            )
        self._refresh_save_enabled()

    def _refresh_save_enabled(self) -> None:
        """Enable review from hand-edited source without a prior generation."""

        if (
            self._is_closing
            or self._pending_result is not None
            or self._active_build_worker is not None
        ):
            return
        has_source = bool(
            self._manifest_edit.toPlainText().strip()
            and self._script_edit.toPlainText().strip()
        )
        self._save_btn.setEnabled(has_source)

    def _install_review(self, overwrite: bool | None = None) -> None:
        if self._is_closing or self._install_completed or self._current_review is None:
            return
        review = self._current_review
        if any(issue.severity is IssueSeverity.WARNING for issue in review.report.issues):
            if not self._confirm("tooldlg.review.warning_title", "tooldlg.review.warning_confirm"):
                return
        should_overwrite = self._registry.get(review.manifest.name) is not None
        if overwrite is None:
            overwrite = should_overwrite
        if overwrite and not self._confirm(
            "tooldlg.review.overwrite_title",
            "tooldlg.review.overwrite_confirm",
            name=review.manifest.name,
        ):
            return
        overrides = self._review_panel.acknowledged_overrides()
        self._pending_install_context = (review, approvals, bool(overwrite), overrides)
        self._start_build_operation(
            "install", (review.build_id, approvals, bool(overwrite), overrides)
        )

    def _start_build_operation(
        self, operation: str, arguments: tuple[object, ...]
    ) -> None:
        if self._is_closing or self._active_build_worker is not None:
            return
        if operation == "install":
            self._generation_token += 1
            self._stop_active_worker()
        self._build_operation_token += 1
        token = self._build_operation_token
        worker = _BuildWorker(self._build_service, token, operation, arguments)
        self._active_build_worker = worker
        self._active_build_operation = operation
        self._live_build_workers.add(worker)
        worker.result_ready.connect(self._on_build_result)
        worker.error.connect(self._on_build_error)
        worker.finished.connect(self._on_build_worker_finished)
        self._set_build_busy(True)
        worker.start()

    def _invalidate_build_operation(self) -> None:
        """Invalidate stale stage/review results without releasing their worker."""

        if self._active_build_operation == "install":
            return
        self._build_operation_token += 1

    @pyqtSlot(int, str, object)
    def _on_build_result(self, token: int, operation: str, result: object) -> None:
        if token != self._build_operation_token and operation != "install":
            return
        if self._is_closing and operation != "install":
            return
        if operation in {"stage_review", "review"} and isinstance(result, BuildReview):
            approvals = (
                frozenset()
                if operation == "stage_review"
                else self._review_panel.approved_permissions
            )
            self._show_review(result, approvals)
        elif operation == "install" and isinstance(result, InstallResult):
            self._handle_install_result(result)

    @pyqtSlot(int, str, str)
    def _on_build_error(self, token: int, operation: str, reason: str) -> None:
        if token != self._build_operation_token and operation != "install":
            return
        if self._is_closing and operation != "install":
            return
        if operation == "install":
            self._pending_install_context = None
            if self._is_closing:
                self._pending_result = QDialog.DialogCode.Rejected
            else:
                self._show_build_error(self._safe_reason(reason))
            return
        self._show_build_error(self._safe_reason(reason))

    @pyqtSlot()
    def _on_build_worker_finished(self) -> None:
        sender = self.sender()
        worker = next(
            (candidate for candidate in self._live_build_workers if candidate is sender),
            None,
        )
        if worker is None:
            return
        self._live_build_workers.discard(worker)
        if worker is self._active_build_worker:
            self._active_build_worker = None
            self._active_build_operation = None
            self._set_build_busy(False)
        worker.deleteLater()
        queued = self._queued_build_operation
        self._queued_build_operation = None
        if queued is not None and not self._is_closing:
            self._start_build_operation(*queued)
        if self._pending_result is not None:
            self._complete_pending_result_if_ready()

    def _set_build_busy(self, is_busy: bool) -> None:
        if self._is_closing:
            return
        self._save_btn.setEnabled(not is_busy)
        self._review_btn.setEnabled(not is_busy and self._staged_build_id is not None)
        is_installing = is_busy and self._active_build_operation == "install"
        for control in (
            self._gen_btn,
            self._regen_btn,
            self._toggle_code_btn,
            self._manifest_edit,
            self._script_edit,
            self._cancel_btn,
        ):
            control.setEnabled(not is_installing)
        if is_installing:
            self._review_panel.setEnabled(False)
        elif not self._is_closing:
            self._review_panel.setEnabled(True)
        if is_busy:
            self._install_btn.setEnabled(False)
        elif self._current_review is not None:
            self._review_panel.set_review(
                self._current_review,
                self._review_panel.approved_permissions,
            )

    def _handle_install_result(self, result: InstallResult) -> None:
        context = self._pending_install_context
        self._pending_install_context = None
        if result.reason == "NAME_CONFLICT" and context is not None and not context[2]:
            review, approvals, _, overrides = context
            if self._confirm(
                "tooldlg.review.overwrite_title",
                "tooldlg.review.overwrite_confirm",
                name=review.manifest.name,
            ):
                self._pending_install_context = (review, approvals, True, overrides)
                self._queued_build_operation = (
                    "install", (review.build_id, approvals, True, overrides)
                )
            return
        if result.installed:
            self._install_completed = True
            self.tool_saved.emit(result.tool_name)
            self._pending_result = QDialog.DialogCode.Accepted
            self._is_closing = True
            self._set_closing_interactions_enabled(False)
            for worker in tuple(self._live_workers):
                worker.stop()
            return
        reason = self._reason_for_install_result(result.reason)
        if result.reason in _REVIEW_AGAIN_REASONS:
            self._current_review = None
            self._review_panel.mark_requires_review(reason, clear_report=False)
        else:
            self._review_panel.mark_install_failed(reason)
        self._set_status_text(reason, "#F87171")

    def _reason_for_install_result(self, reason: str) -> str:
        key = _KNOWN_INSTALL_REASON_KEYS.get(reason)
        if key is not None:
            return t(key)
        diagnostic_code = reason if re.fullmatch(r"[A-Z0-9_]{1,64}", reason) else "UNKNOWN"
        return t("tooldlg.review.install_reason.unknown", code=diagnostic_code)

    @staticmethod
    def _safe_reason(reason: str) -> str:
        return reason if re.fullmatch(r"[A-Z_]+", reason) else "VALIDATION_FAILED"

    def _confirm(self, title_key: str, body_key: str, **values: object) -> bool:
        answer = QMessageBox.question(
            self,
            t(title_key),
            t(body_key, **values),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _show_build_error(self, reason: str) -> None:
        self._current_review = None
        self._review_panel.mark_requires_review(
            self._reason_for_install_result(reason), clear_report=False
        )
        self._set_status_text(self._reason_for_install_result(reason), "#F87171")

    def _warn(self, key: str) -> None:
        QMessageBox.warning(self, t("tooldlg.gen.err_title"), t(key))

    def _set_status(self, key: str, color: str) -> None:
        self._set_status_text(t(key), color)

    def _set_status_text(self, text: str, color: str) -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(f"font-size: 11px; color: {color};")

    @pyqtSlot()
    def _request_reject(self) -> None:
        self.reject()

    def reject(self) -> None:
        self._request_dialog_result(QDialog.DialogCode.Rejected)

    def _request_dialog_result(self, result: QDialog.DialogCode) -> None:
        """Defer the final dialog result until every live worker has finished."""

        if self._pending_result is not None:
            return
        self._pending_result = result
        self._is_closing = True
        self._generation_token += 1
        if self._active_build_operation != "install":
            self._build_operation_token += 1
        self._set_closing_interactions_enabled(False)
        self._review_panel.mark_closing_wait()
        for worker in tuple(self._live_workers):
            worker.stop()
        self._complete_pending_result_if_ready()

    def _complete_pending_result_if_ready(self) -> None:
        if (
            self._pending_result is None
            or self._live_workers
            or self._live_build_workers
        ):
            return
        result = self._pending_result
        self._pending_result = None
        self._is_closing = False
        if result is QDialog.DialogCode.Accepted:
            super().accept()
        else:
            super().reject()

    def _set_closing_interactions_enabled(self, is_enabled: bool) -> None:
        for control in (
            self._req_edit,
            self._model_combo,
            self._gen_btn,
            self._tabs,
            self._toggle_code_btn,
            self._review_panel,
            self._regen_btn,
            self._cancel_btn,
        ):
            control.setEnabled(is_enabled)
        if not is_enabled:
            self._review_btn.setEnabled(False)
            self._install_btn.setEnabled(False)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.reject()
