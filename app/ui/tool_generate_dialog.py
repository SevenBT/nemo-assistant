"""Dialog for AI-assisted tool generation."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config import USER_TOOLS_DIR
from app.core.tool_generator import ModelOverride, build_model_options, parse_result, stream_generate
from app.i18n import t
from app.tools.registry import ToolRegistry


class _GenerateWorker(QThread):
    """Runs AI generation in a background thread."""

    chunk = pyqtSignal(str)       # text delta
    finished = pyqtSignal(str)    # full accumulated text
    error = pyqtSignal(str)

    def __init__(self, requirement: str, model_override: ModelOverride | None = None):
        super().__init__()
        self._requirement = requirement
        self._model_override = model_override
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        full = ""
        try:
            for event in stream_generate(self._requirement, self._model_override):
                if self._stopped:
                    return
                if event["type"] == "text":
                    delta = event["delta"]
                    full += delta
                    self.chunk.emit(delta)
                elif event["type"] == "error":
                    self.error.emit(event["message"])
                    return
            self.finished.emit(full)
        except Exception as e:
            self.error.emit(str(e))


class ToolGenerateDialog(QDialog):
    """AI-powered tool generation dialog."""

    tool_saved = pyqtSignal(str)  # tool name

    def __init__(
        self,
        registry: ToolRegistry,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._registry = registry
        self._worker: _GenerateWorker | None = None
        self._full_text = ""
        self._manifest_str = ""
        self._script_str = ""
        self.setWindowTitle(t("tooldlg.gen.title"))
        self.setMinimumSize(620, 600)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Requirement input ────────────────────────────────────────
        layout.addWidget(QLabel(t("tooldlg.gen.req_label")))
        self._req_edit = QTextEdit()
        self._req_edit.setPlaceholderText(t("tooldlg.gen.req_ph"))
        self._req_edit.setMaximumHeight(90)
        layout.addWidget(self._req_edit)

        # ── Model selector ───────────────────────────────────────────
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel(t("tooldlg.gen.model")))
        self._model_combo = QComboBox()
        self._model_combo.setMinimumWidth(260)
        self._model_options: list[ModelOverride] = build_model_options()
        for opt in self._model_options:
            self._model_combo.addItem(opt.label)
        model_row.addWidget(self._model_combo)
        model_row.addStretch()
        layout.addLayout(model_row)

        btn_row = QHBoxLayout()
        self._gen_btn = QPushButton(t("tooldlg.gen.generate"))
        self._gen_btn.setObjectName("sendBtn")
        self._gen_btn.setFixedHeight(34)
        self._gen_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._gen_btn)
        self._status_label = QLabel()
        self._status_label.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        btn_row.addWidget(self._status_label)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # ── Result tabs ──────────────────────────────────────────────
        self._tabs = QTabWidget()

        self._manifest_edit = QPlainTextEdit()
        self._manifest_edit.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        self._manifest_edit.setPlaceholderText(t("tooldlg.gen.manifest_ph"))
        self._tabs.addTab(self._manifest_edit, "manifest.json")

        self._script_edit = QPlainTextEdit()
        self._script_edit.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        self._script_edit.setPlaceholderText(t("tooldlg.gen.script_ph"))
        self._tabs.addTab(self._script_edit, "tool.py")

        # Raw output tab for debugging
        self._raw_edit = QPlainTextEdit()
        self._raw_edit.setReadOnly(True)
        self._raw_edit.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 11px;"
        )
        self._raw_edit.setPlaceholderText(t("tooldlg.gen.raw_ph"))
        self._tabs.addTab(self._raw_edit, t("tooldlg.gen.raw_tab"))

        layout.addWidget(self._tabs, 1)

        # ── Tool name + save ─────────────────────────────────────────
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(t("tooldlg.gen.tool_name")))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(t("tooldlg.gen.tool_name_ph"))
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        # ── Bottom buttons ───────────────────────────────────────────
        bottom = QHBoxLayout()
        self._regen_btn = QPushButton(t("tooldlg.gen.regenerate"))
        self._regen_btn.setObjectName("noteToolBtn")
        self._regen_btn.setEnabled(False)
        self._regen_btn.clicked.connect(self._on_generate)
        bottom.addWidget(self._regen_btn)

        bottom.addStretch()

        self._save_btn = QPushButton(t("tooldlg.gen.save"))
        self._save_btn.setObjectName("sendBtn")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        bottom.addWidget(self._save_btn)

        cancel_btn = QPushButton(t("common.cancel"))
        cancel_btn.setObjectName("noteToolBtn")
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        layout.addLayout(bottom)

    # ------------------------------------------------------------------ generate
    def _on_generate(self):
        requirement = self._req_edit.toPlainText().strip()
        if not requirement:
            QMessageBox.warning(self, t("tooldlg.gen.tip_title"), t("tooldlg.gen.tip_no_req"))
            return

        # Stop any running worker
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(1000)

        self._full_text = ""
        self._raw_edit.setPlainText("")
        self._manifest_edit.setPlainText("")
        self._script_edit.setPlainText("")
        self._name_edit.clear()
        self._save_btn.setEnabled(False)
        self._regen_btn.setEnabled(False)
        self._gen_btn.setEnabled(False)
        self._status_label.setText(t("tooldlg.gen.status_generating"))
        self._tabs.setCurrentIndex(2)  # show raw output while streaming

        idx = self._model_combo.currentIndex()
        model_override = self._model_options[idx] if self._model_options else None

        self._worker = _GenerateWorker(requirement, model_override)
        self._worker.chunk.connect(self._on_chunk)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_chunk(self, delta: str):
        self._full_text += delta
        self._raw_edit.insertPlainText(delta)
        # Auto-scroll
        sb = self._raw_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_finished(self, full_text: str):
        self._gen_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)

        manifest_str, script_str, err = parse_result(full_text)

        if err:
            self._status_label.setText(f"⚠ {err}")
            self._status_label.setStyleSheet("font-size: 11px; color: #F87171;")
            return

        self._manifest_str = manifest_str
        self._script_str = script_str

        self._manifest_edit.setPlainText(manifest_str)
        self._script_edit.setPlainText(script_str)

        # Auto-fill tool name from manifest
        try:
            name = json.loads(manifest_str).get("name", "")
            self._name_edit.setText(name)
        except Exception:
            pass

        self._save_btn.setEnabled(True)
        self._status_label.setText(t("tooldlg.gen.status_done"))
        self._status_label.setStyleSheet("font-size: 11px; color: #34D399;")
        self._tabs.setCurrentIndex(0)  # switch to manifest tab

    def _on_error(self, message: str):
        self._gen_btn.setEnabled(True)
        self._regen_btn.setEnabled(True)
        self._status_label.setText(f"✗ {message}")
        self._status_label.setStyleSheet("font-size: 11px; color: #F87171;")

    # ------------------------------------------------------------------ save
    def _on_save(self):
        # Use edited content from tabs (user may have modified)
        manifest_str = self._manifest_edit.toPlainText().strip()
        script_str = self._script_edit.toPlainText().strip()
        name = self._name_edit.text().strip()

        if not name:
            QMessageBox.warning(self, t("tooldlg.gen.err_title"), t("tooldlg.gen.err_no_name"))
            return

        import re
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            QMessageBox.warning(self, t("tooldlg.gen.err_title"), t("tooldlg.gen.err_bad_name"))
            return

        # Validate manifest JSON
        try:
            manifest = json.loads(manifest_str)
        except json.JSONDecodeError as e:
            QMessageBox.warning(self, t("tooldlg.gen.err_title"), t("tooldlg.gen.err_bad_manifest", err=e))
            return

        # Force name to match the input field
        manifest["name"] = name

        # Check duplicate
        if self._registry.get(name):
            reply = QMessageBox.question(
                self,
                t("tooldlg.gen.exists_title"),
                t("tooldlg.gen.exists_body", name=name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Write files
        tool_dir = USER_TOOLS_DIR / name
        tool_dir.mkdir(parents=True, exist_ok=True)

        with open(tool_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        with open(tool_dir / "tool.py", "w", encoding="utf-8") as f:
            f.write(script_str)

        self.tool_saved.emit(name)
        self.accept()

    # ------------------------------------------------------------------ cleanup
    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        super().closeEvent(event)
