"""Dialog for testing a tool with custom parameters."""
from __future__ import annotations

import json
import time

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.i18n import t
from app.tools.registry import ToolRegistry
from app.tools.script_adapter import ScriptToolAdapter


class _ExecWorker(QThread):
    """Run tool execution in a background thread."""

    finished = pyqtSignal(dict, float)  # result, elapsed_seconds

    def __init__(self, registry: ToolRegistry, tool_name: str, params: dict):
        super().__init__()
        self._registry = registry
        self._tool_name = tool_name
        self._params = params

    def run(self):
        t0 = time.time()
        result = self._registry.execute(self._tool_name, self._params)
        elapsed = time.time() - t0
        self.finished.emit(result, elapsed)


class ToolTestDialog(QDialog):
    """Interactive test runner for a single tool."""

    def __init__(
        self,
        tool: ScriptToolAdapter,
        registry: ToolRegistry,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._tool = tool
        self._registry = registry
        self._worker: _ExecWorker | None = None
        self.setWindowTitle(t("tooldlg.test.title", name=tool.name))
        self.setMinimumSize(520, 500)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Tool info ────────────────────────────────────────────────
        info = QLabel(f"{self._tool.name} — {self._tool.description}")
        info.setStyleSheet("font-size: 13px; font-weight: 600;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # ── Parameter inputs ─────────────────────────────────────────
        params_label = QLabel(t("tooldlg.test.params"))
        params_label.setStyleSheet("font-size: 12px; font-weight: 600; margin-top: 6px;")
        layout.addWidget(params_label)

        self._param_inputs: dict[str, QLineEdit] = {}
        properties = self._tool.parameters.get("properties", {})
        required_list = self._tool.parameters.get("required", [])

        if properties:
            for pname, pdata in properties.items():
                row = QHBoxLayout()
                req_mark = " *" if pname in required_list else ""
                label = QLabel(f"{pname}{req_mark}:")
                label.setFixedWidth(120)
                label.setToolTip(pdata.get("description", ""))
                row.addWidget(label)
                edit = QLineEdit()
                ptype = pdata.get("type", "string")
                pdesc = pdata.get("description", "")
                edit.setPlaceholderText(f"{ptype} — {pdesc}")
                row.addWidget(edit)
                layout.addLayout(row)
                self._param_inputs[pname] = edit
        else:
            layout.addWidget(QLabel(t("tooldlg.test.no_params")))

        # ── Run button ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton(t("tooldlg.test.run"))
        self._run_btn.setObjectName("sendBtn")
        self._run_btn.setFixedHeight(36)
        self._run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self._run_btn)

        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Output area ──────────────────────────────────────────────
        output_label = QLabel(t("tooldlg.test.result"))
        output_label.setStyleSheet("font-size: 12px; font-weight: 600; margin-top: 6px;")
        layout.addWidget(output_label)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        self._output.setPlaceholderText(t("tooldlg.test.result_ph"))
        layout.addWidget(self._output, 1)

    def _on_run(self):
        # Collect params
        params = {}
        properties = self._tool.parameters.get("properties", {})
        for pname, edit in self._param_inputs.items():
            val = edit.text().strip()
            ptype = properties.get(pname, {}).get("type", "string")
            if ptype == "number" and val:
                try:
                    params[pname] = float(val) if "." in val else int(val)
                except ValueError:
                    params[pname] = val
            elif ptype == "boolean" and val:
                params[pname] = val.lower() in ("true", "1", "yes")
            elif ptype in ("array", "object") and val:
                try:
                    params[pname] = json.loads(val)
                except json.JSONDecodeError:
                    params[pname] = val
            elif val:
                params[pname] = val

        self._run_btn.setEnabled(False)
        self._status_label.setText(t("tooldlg.test.running"))
        self._output.setPlainText("")

        self._worker = _ExecWorker(self._registry, self._tool.name, params)
        self._worker.finished.connect(self._on_result)
        self._worker.start()

    def _on_result(self, result: dict, elapsed: float):
        self._run_btn.setEnabled(True)
        status = result.get("status", "unknown")
        icon = "✓" if status == "success" else "✗"
        self._status_label.setText(f"{icon} {status}  ({elapsed:.2f}s)")

        if status == "success":
            self._status_label.setStyleSheet("font-size: 11px; color: #34D399;")
        else:
            self._status_label.setStyleSheet("font-size: 11px; color: #F87171;")

        formatted = json.dumps(result, ensure_ascii=False, indent=2)
        self._output.setPlainText(formatted)
        self._worker = None

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.terminate()
            self._worker.wait(2000)
        super().closeEvent(event)
