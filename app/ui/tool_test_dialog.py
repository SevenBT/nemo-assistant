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

from app.core.tool_manager import ToolManager
from app.models.tool_def import ToolDefinition


class _ExecWorker(QThread):
    """Run tool execution in a background thread."""

    finished = pyqtSignal(dict, float)  # result, elapsed_seconds

    def __init__(self, tool_mgr: ToolManager, tool_name: str, params: dict):
        super().__init__()
        self._tm = tool_mgr
        self._tool_name = tool_name
        self._params = params

    def run(self):
        t0 = time.time()
        result = self._tm.execute(self._tool_name, self._params)
        elapsed = time.time() - t0
        self.finished.emit(result, elapsed)


class ToolTestDialog(QDialog):
    """Interactive test runner for a single tool."""

    def __init__(
        self,
        tool: ToolDefinition,
        tool_mgr: ToolManager,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._tool = tool
        self._tool_mgr = tool_mgr
        self._worker: _ExecWorker | None = None
        self.setWindowTitle(f"测试工具 — {tool.name}")
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
        params_label = QLabel("参数")
        params_label.setStyleSheet("font-size: 12px; font-weight: 600; margin-top: 6px;")
        layout.addWidget(params_label)

        self._param_inputs: dict[str, QLineEdit] = {}
        ai_params = {
            n: p for n, p in self._tool.parameters.items()
            if p.source in ("ai", "manual")
        }
        config_params = {
            n: p for n, p in self._tool.parameters.items()
            if p.source == "config"
        }

        if ai_params:
            for pname, pdef in ai_params.items():
                row = QHBoxLayout()
                req_mark = " *" if pdef.required else ""
                label = QLabel(f"{pname}{req_mark}:")
                label.setFixedWidth(120)
                label.setToolTip(pdef.description)
                row.addWidget(label)
                edit = QLineEdit()
                edit.setPlaceholderText(f"{pdef.type} — {pdef.description}")
                if pdef.default:
                    edit.setText(str(pdef.default))
                row.addWidget(edit)
                layout.addLayout(row)
                self._param_inputs[pname] = edit
        else:
            layout.addWidget(QLabel("  此工具无需输入参数"))

        # Show config params as read-only
        if config_params:
            cfg_label = QLabel("配置参数 (来自设置，只读)")
            cfg_label.setStyleSheet("font-size: 11px; color: #9CA3AF; margin-top: 4px;")
            layout.addWidget(cfg_label)
            cfg_values = self._tool_mgr.get_config_params(self._tool.name)
            for pname, pdef in config_params.items():
                row = QHBoxLayout()
                label = QLabel(f"{pname}:")
                label.setFixedWidth(120)
                row.addWidget(label)
                val = cfg_values.get(pname, pdef.default or "")
                val_label = QLabel(str(val) if val else "(未配置)")
                val_label.setStyleSheet("color: #6B7280;")
                row.addWidget(val_label)
                layout.addLayout(row)

        # ── Run button ───────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._run_btn = QPushButton("▶ 运行测试")
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
        output_label = QLabel("执行结果")
        output_label.setStyleSheet("font-size: 12px; font-weight: 600; margin-top: 6px;")
        layout.addWidget(output_label)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        self._output.setPlaceholderText("点击「运行测试」查看结果...")
        layout.addWidget(self._output, 1)

    def _on_run(self):
        # Collect params
        params = {}
        for pname, edit in self._param_inputs.items():
            val = edit.text().strip()
            pdef = self._tool.parameters.get(pname)
            if pdef and pdef.type == "number" and val:
                try:
                    params[pname] = float(val) if "." in val else int(val)
                except ValueError:
                    params[pname] = val
            elif pdef and pdef.type == "boolean" and val:
                params[pname] = val.lower() in ("true", "1", "yes")
            elif pdef and pdef.type in ("array", "object") and val:
                try:
                    params[pname] = json.loads(val)
                except json.JSONDecodeError:
                    params[pname] = val
            elif val:
                params[pname] = val

        # Resolve with config params
        resolved = self._tool_mgr.resolve_params(self._tool.name, params)

        self._run_btn.setEnabled(False)
        self._status_label.setText("执行中...")
        self._output.setPlainText("")

        self._worker = _ExecWorker(self._tool_mgr, self._tool.name, resolved)
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
