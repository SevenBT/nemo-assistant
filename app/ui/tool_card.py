import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ToolCard(QFrame):
    """Expandable card showing a tool execution: name, params, result."""

    def __init__(self, tool_name: str, params: dict, result: dict = None, parent=None):
        super().__init__(parent)
        self._tool_name = tool_name
        self._params = params
        self._result = result
        self._expanded = False
        self.setObjectName("toolCard")
        self._build()

    # ------------------------------------------------------------------ build
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 7)
        root.setSpacing(4)

        # Header
        header = QHBoxLayout()
        header.setSpacing(6)

        self._status_label = QLabel()
        self._status_label.setTextFormat(Qt.TextFormat.RichText)
        self._refresh_status()
        header.addWidget(self._status_label)
        header.addStretch()

        self._toggle_btn = QPushButton("展开")
        self._toggle_btn.setObjectName("toggleBtn")
        self._toggle_btn.setFixedSize(46, 22)
        self._toggle_btn.clicked.connect(self._toggle)
        header.addWidget(self._toggle_btn)
        root.addLayout(header)

        # Detail section
        self._detail = QWidget()
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(4)

        params_label = QLabel("参数:")
        params_label.setObjectName("detailLabel")
        detail_layout.addWidget(params_label)

        params_view = QTextEdit()
        params_view.setReadOnly(True)
        params_view.setMaximumHeight(90)
        params_view.setPlainText(json.dumps(self._params, ensure_ascii=False, indent=2))
        params_view.setObjectName("detailText")
        detail_layout.addWidget(params_view)

        self._result_label = QLabel("返回:")
        self._result_label.setObjectName("detailLabel")
        detail_layout.addWidget(self._result_label)

        self._result_view = QTextEdit()
        self._result_view.setReadOnly(True)
        self._result_view.setMaximumHeight(120)
        self._result_view.setObjectName("detailText")
        self._refresh_result_view()
        detail_layout.addWidget(self._result_view)

        self._detail.hide()
        root.addWidget(self._detail)

    # ------------------------------------------------------------------ update
    def update_result(self, result: dict):
        self._result = result
        self._refresh_status()
        self._refresh_result_view()

    def _refresh_status(self):
        if self._result is None:
            icon, color = "⟳", "#f9e2af"
        elif self._result.get("status") == "success":
            icon, color = "✓", "#a6e3a1"
        else:
            icon, color = "✗", "#f38ba8"
        self._status_label.setText(
            f'<span style="color:{color};font-weight:600">{icon}</span>'
            f'&nbsp;工具: <b>{self._tool_name}</b>'
        )

    def _refresh_result_view(self):
        if self._result is not None:
            self._result_view.setPlainText(
                json.dumps(self._result, ensure_ascii=False, indent=2)
            )
        else:
            self._result_view.setPlainText("执行中...")

    # ------------------------------------------------------------------ toggle
    def _toggle(self):
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        self._toggle_btn.setText("收起" if self._expanded else "展开")
