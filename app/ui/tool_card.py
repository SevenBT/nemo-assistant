from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    TransparentPushButton,
)

from app.i18n import t
from app.ui import style


class ToolSummaryWidget(QFrame):
    """Compact summary of all tool calls in one message.

    Default: single line "⚡ 已调用 N 个工具"
    Expanded: list of tool names with status icons
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tools: list[dict] = []  # [{id, name, status, label}]
        self._detail_labels: list[CaptionLabel] = []
        self._expanded = False
        self.setObjectName("toolSummary")
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # Header row
        header = QHBoxLayout()
        header.setSpacing(6)
        self._summary_label = QLabel()
        self._summary_label.setObjectName("detailLabel")
        self._summary_label.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(self._summary_label)
        header.addStretch()

        self._toggle_btn = TransparentPushButton(t("toolcard.expand"))
        self._toggle_btn.setFixedHeight(24)
        # 宽度随文案自适应，避免英文 Expand/Collapse 被固定宽度截断
        self._toggle_btn.setMinimumWidth(0)
        self._toggle_btn.clicked.connect(self._toggle)
        self._toggle_btn.hide()
        header.addWidget(self._toggle_btn)
        root.addLayout(header)

        # Expandable detail: list of tool names
        self._detail = QWidget()
        self._detail_layout = QVBoxLayout(self._detail)
        self._detail_layout.setContentsMargins(4, 2, 0, 2)
        self._detail_layout.setSpacing(2)
        self._detail.hide()
        root.addWidget(self._detail)

        self._refresh_summary()

    # ------------------------------------------------------------------ public
    def add_tool(self, call_id: str, name: str) -> None:
        """Register a new tool call (pending state)."""
        tool = {"id": call_id, "name": name, "status": "pending"}
        self._tools.append(tool)
        label = self._append_detail(tool)
        tool["label"] = label
        self._refresh_summary()
        self._toggle_btn.setVisible(bool(self._tools))

    def update_tool(self, call_id: str, result: dict) -> None:
        """Mark a tool call as completed."""
        for tool in self._tools:
            if tool["id"] != call_id:
                continue
            tool["status"] = (
                "success" if result.get("status") == "success" else "error"
            )
            self._refresh_detail(tool)
            self._refresh_summary()
            return

    def refresh_theme(self) -> None:
        theme = style.get_current_theme()
        self._refresh_summary()
        for tool in self._tools:
            self._refresh_detail(tool, theme=theme)

    # ------------------------------------------------------------------ internal
    def _refresh_summary(self):
        n = len(self._tools)
        if n == 0:
            self._summary_label.setText("")
            return
        theme = style.get_current_theme()
        pending = sum(1 for t in self._tools if t["status"] == "pending")
        errors = sum(1 for t in self._tools if t["status"] == "error")
        if pending > 0:
            text = f'<span style="color:{theme["warning"]}">⟳</span> {t("toolcard.calling", n=n)}'
        elif errors > 0:
            text = f'<span style="color:{theme["error"]}">⚠</span> {t("toolcard.called_with_errors", n=n, errors=errors)}'
        else:
            text = f'<span style="color:{theme["success"]}">✓</span> {t("toolcard.called", n=n)}'
        self._summary_label.setText(text)

    def _append_detail(self, tool: dict) -> CaptionLabel:
        theme = style.get_current_theme()
        label = CaptionLabel()
        self._detail_labels.append(label)
        self._detail_layout.addWidget(label)
        tool["label"] = label
        self._refresh_detail(tool, theme=theme)
        return label

    def _refresh_detail(self, tool: dict, *, theme: dict | None = None) -> None:
        theme = theme or style.get_current_theme()
        if tool["status"] == "pending":
            icon, color = "⟳", theme["warning"]
        elif tool["status"] == "success":
            icon, color = "✓", theme["success"]
        else:
            icon, color = "✗", theme["error"]
        label = tool["label"]
        label.setText(f"  {icon} {tool['name']}")
        label.setStyleSheet(f"color: {color}")

    def _rebuild_detail(self) -> None:
        """Rebuild all detail rows after a theme change or full refresh."""
        while self._detail_layout.count():
            item = self._detail_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._detail_labels.clear()
        theme = style.get_current_theme()
        for tool in self._tools:
            label = self._append_detail(tool)
            tool["label"] = label

    def _toggle(self):
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        self._toggle_btn.setText(t("toolcard.collapse") if self._expanded else t("toolcard.expand"))
