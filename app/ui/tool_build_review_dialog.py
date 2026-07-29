"""Compact review panel for generated-tool builds: status, issues, install."""
from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, IconWidget, PrimaryPushButton, PushButton

from app.core.tool_build import BuildReview, IssueSeverity, ToolPermission, ValidationIssue
from app.i18n import t
from app.ui import style


class ToolBuildReviewPanel(QWidget):
    """Show one build's readiness and collect only the install decision."""

    review_requested = pyqtSignal()
    install_requested = pyqtSignal()
    # Retained for signal compatibility with the dialog; permissions are no
    # longer approved in the UI, so these never fire.
    approvals_changed = pyqtSignal()
    auto_declare_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._cancel_button: QWidget | None = None
        self.focus_order: tuple[QWidget, ...] = ()
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(8)

        status_row = QHBoxLayout()
        self._status_icon = IconWidget(FluentIcon.INFO)
        self._status_icon.setFixedSize(18, 18)
        self._status_icon.setAccessibleName(t("tooldlg.review.a11y.status_icon"))
        status_row.addWidget(self._status_icon)
        self._summary_label = self._focusable_label()
        self._summary_label.setWordWrap(True)
        status_row.addWidget(self._summary_label, 1)
        root.addLayout(status_row)

        self._issues_edit = QPlainTextEdit()
        self._issues_edit.setReadOnly(True)
        self._issues_edit.setTabChangesFocus(True)
        self._issues_edit.setMaximumHeight(96)
        self._issues_edit.setAccessibleName(t("tooldlg.review.a11y.issues"))
        self._issues_edit.setVisible(False)
        root.addWidget(self._issues_edit)

        self._install_reason_label = QLabel()
        self._install_reason_label.setWordWrap(True)
        self._install_reason_label.setAccessibleName(t("tooldlg.review.a11y.install_reason"))
        root.addWidget(self._install_reason_label)

        actions = QHBoxLayout()
        actions.addStretch()
        self._review_btn = PushButton(t("tooldlg.review.review_again"))
        self._review_btn.setAccessibleName(t("tooldlg.review.a11y.review_action"))
        self._review_btn.setVisible(False)
        self._review_btn.clicked.connect(self.review_requested)
        actions.addWidget(self._review_btn)
        self._install_btn = PrimaryPushButton(t("tooldlg.review.install"))
        self._install_btn.setAccessibleName(t("tooldlg.review.a11y.install_action"))
        self._install_btn.clicked.connect(self.install_requested)
        actions.addWidget(self._install_btn)
        root.addLayout(actions)
        self.clear()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self._summary_label.setFocus(Qt.FocusReason.TabFocusReason)

    @staticmethod
    def _focusable_label() -> QLabel:
        label = QLabel()
        label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByKeyboard
            | Qt.TextInteractionFlag.TextSelectableByMouse
        )
        label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        return label

    @property
    def approved_permissions(self) -> frozenset[ToolPermission]:
        """Permissions are declared metadata only; nothing is approved here."""

        return frozenset()

    def acknowledged_overrides(self) -> frozenset[str]:
        """No blocking finding is user-overridable in the simplified flow."""

        return frozenset()

    def set_review(
        self,
        review: BuildReview,
        approved_permissions: frozenset[ToolPermission] = frozenset(),
    ) -> None:
        """Show one build's readiness: installable, or its blocking issues."""

        report = review.report
        blocking = [
            issue for issue in report.issues if issue.severity is IssueSeverity.BLOCK
        ]
        self._review_btn.setVisible(False)
        if not blocking:
            self._set_status(
                t("tooldlg.review.status.ready_simple", name=review.manifest.name),
                "success",
                FluentIcon.ACCEPT,
            )
            self._issues_edit.setVisible(False)
            self._issues_edit.clear()
            self.set_install_enabled(True)
            return
        self._set_status(
            t("tooldlg.review.status.blocked_simple"), "error", FluentIcon.CANCEL
        )
        self._issues_edit.setPlainText(self._format_issues(blocking))
        self._issues_edit.setVisible(True)
        self.set_install_enabled(False, t("tooldlg.review.install_blocked_simple"))

    def _set_status(self, text: str, color_key: str, icon: FluentIcon) -> None:
        color = style.get_current_theme()[color_key]
        self._status_icon.setIcon(icon)
        self._summary_label.setText(text)
        self._summary_label.setAccessibleName(text)
        self._summary_label.setAccessibleDescription(text)
        self._summary_label.setStyleSheet(f"font-weight: 600; color: {color};")
        self._status_icon.setAccessibleDescription(text)

    def set_install_enabled(self, is_enabled: bool, reason: str = "") -> None:
        self._install_btn.setEnabled(is_enabled)
        if is_enabled:
            self._install_reason_label.clear()
            self._install_reason_label.setAccessibleName(
                t("tooldlg.review.a11y.install_reason")
            )
            self._install_reason_label.setAccessibleDescription("")
            return
        concrete = reason or t("tooldlg.review.install_blocked_simple")
        self._install_reason_label.setText(concrete)
        accessible = t("tooldlg.review.a11y.install_reason_with_reason", reason=concrete)
        self._install_reason_label.setAccessibleName(accessible)
        self._install_reason_label.setAccessibleDescription(accessible)

    def _set_disabled_state(
        self, reason: str, *, clear_report: bool, review_enabled: bool = True
    ) -> None:
        self._set_status(reason, "warning", FluentIcon.INFO)
        self.set_install_enabled(False, reason)
        self._review_btn.setVisible(review_enabled)
        self._review_btn.setEnabled(review_enabled)
        if clear_report:
            self._issues_edit.clear()
            self._issues_edit.setVisible(False)

    def mark_requires_review(self, reason: str, *, clear_report: bool) -> None:
        self._set_disabled_state(reason, clear_report=clear_report)

    def mark_install_failed(self, reason: str) -> None:
        self._set_disabled_state(reason, clear_report=False)

    def mark_closing_wait(self) -> None:
        self._set_disabled_state(
            t("tooldlg.review.install_closing_wait"),
            clear_report=False,
            review_enabled=False,
        )

    def clear(self) -> None:
        self._set_status(
            t("tooldlg.review.status.not_generated"), "warning", FluentIcon.INFO
        )
        self._issues_edit.clear()
        self._issues_edit.setVisible(False)
        self.set_install_enabled(False, t("tooldlg.review.install_not_reviewed"))

    def set_focus_chain(self, cancel_button: QWidget) -> None:
        self._cancel_button = cancel_button
        self.focus_order = (
            self._summary_label,
            self._issues_edit,
            self._install_btn,
            cancel_button,
        )
        for current, following in zip(self.focus_order, self.focus_order[1:]):
            QWidget.setTabOrder(current, following)

    @staticmethod
    def _format_issues(issues: Iterable[ValidationIssue]) -> str:
        return "\n\n".join(
            t(
                "tooldlg.review.issue_row",
                severity=t(f"tooldlg.review.severity.{issue.severity.value}"),
                code=issue.code,
                message=issue.message,
            )
            for issue in issues
        )
