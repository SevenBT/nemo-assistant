"""Dialog for creating and editing user tools.

Handles manifest.json + tool.py generation.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.config import USER_TOOLS_DIR
from app.core.tool_manager import ToolManager
from app.models.tool_def import ToolDefinition

_SCRIPT_TEMPLATE = '''\
import json
import sys


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    # 在这里编写你的工具逻辑
    result = {"status": "success", "data": {"message": "Hello from tool!"}}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''


class ToolEditorDialog(QDialog):
    """Create or edit a user tool."""

    def __init__(
        self,
        tool_mgr: ToolManager,
        tool: ToolDefinition | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._tool_mgr = tool_mgr
        self._editing = tool  # None = create mode
        self.setWindowTitle("编辑工具" if tool else "新建工具")
        self.setMinimumSize(600, 700)
        self._build()
        if tool:
            self._populate(tool)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Basic info ───────────────────────────────────────────────
        info_section = QLabel("基本信息")
        info_section.setStyleSheet("font-size: 13px; font-weight: 700;")
        layout.addWidget(info_section)

        row = QHBoxLayout()
        row.addWidget(QLabel("名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("tool_name (英文、下划线)")
        if self._editing:
            self._name_edit.setText(self._editing.name)
            self._name_edit.setReadOnly(True)
        row.addWidget(self._name_edit)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("描述:"))
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("简要描述工具功能")
        row.addWidget(self._desc_edit)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("版本:"))
        self._ver_edit = QLineEdit()
        self._ver_edit.setPlaceholderText("1.0.0")
        self._ver_edit.setMaximumWidth(100)
        row.addWidget(self._ver_edit)
        row.addWidget(QLabel("作者:"))
        self._author_edit = QLineEdit()
        self._author_edit.setPlaceholderText("可选")
        row.addWidget(self._author_edit)
        layout.addLayout(row)

        # ── Dependencies ─────────────────────────────────────────────
        dep_section = QLabel("依赖 (每行一个 pip 包名)")
        dep_section.setStyleSheet("font-size: 13px; font-weight: 700; margin-top: 8px;")
        layout.addWidget(dep_section)

        self._deps_edit = QTextEdit()
        self._deps_edit.setPlaceholderText("requests>=2.28\nbeautifulsoup4")
        self._deps_edit.setMaximumHeight(70)
        layout.addWidget(self._deps_edit)

        # ── Parameters ───────────────────────────────────────────────
        param_header = QHBoxLayout()
        param_section = QLabel("参数")
        param_section.setStyleSheet("font-size: 13px; font-weight: 700; margin-top: 8px;")
        param_header.addWidget(param_section)
        param_header.addStretch()
        add_param_btn = QPushButton("+ 添加参数")
        add_param_btn.setObjectName("noteToolBtn")
        add_param_btn.clicked.connect(self._add_param_row)
        param_header.addWidget(add_param_btn)
        remove_param_btn = QPushButton("- 删除选中")
        remove_param_btn.setObjectName("noteToolBtn")
        remove_param_btn.clicked.connect(self._remove_param_row)
        param_header.addWidget(remove_param_btn)
        layout.addLayout(param_header)

        self._param_table = QTableWidget(0, 6)
        self._param_table.setHorizontalHeaderLabels(
            ["名称", "类型", "描述", "来源", "必填", "默认值"]
        )
        hh = self._param_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self._param_table.setColumnWidth(1, 80)
        self._param_table.setColumnWidth(3, 70)
        self._param_table.setColumnWidth(4, 50)
        self._param_table.setMaximumHeight(160)
        layout.addWidget(self._param_table)

        # ── Script editor ────────────────────────────────────────────
        script_section = QLabel("脚本 (tool.py)")
        script_section.setStyleSheet("font-size: 13px; font-weight: 700; margin-top: 8px;")
        layout.addWidget(script_section)

        self._script_edit = QPlainTextEdit()
        self._script_edit.setPlaceholderText("# Python 脚本...")
        self._script_edit.setStyleSheet(
            "font-family: 'Cascadia Code', 'Consolas', monospace; font-size: 12px;"
        )
        if not self._editing:
            self._script_edit.setPlainText(_SCRIPT_TEMPLATE)
        layout.addWidget(self._script_edit, 1)

        # ── Buttons ──────────────────────────────────────────────────
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self._on_save)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    # ------------------------------------------------------------------ param table helpers
    def _add_param_row(self):
        row = self._param_table.rowCount()
        self._param_table.insertRow(row)
        self._param_table.setItem(row, 0, QTableWidgetItem(""))
        # Type combo
        type_combo = QComboBox()
        type_combo.addItems(["string", "number", "boolean", "array", "object"])
        self._param_table.setCellWidget(row, 1, type_combo)
        self._param_table.setItem(row, 2, QTableWidgetItem(""))
        # Source combo
        src_combo = QComboBox()
        src_combo.addItems(["ai", "config", "manual"])
        self._param_table.setCellWidget(row, 3, src_combo)
        # Required combo
        req_combo = QComboBox()
        req_combo.addItems(["是", "否"])
        self._param_table.setCellWidget(row, 4, req_combo)
        self._param_table.setItem(row, 5, QTableWidgetItem(""))

    def _remove_param_row(self):
        row = self._param_table.currentRow()
        if row >= 0:
            self._param_table.removeRow(row)

    # ------------------------------------------------------------------ populate (edit mode)
    def _populate(self, tool: ToolDefinition):
        self._desc_edit.setText(tool.description)
        self._ver_edit.setText(tool.version)
        self._author_edit.setText(tool.author)
        self._deps_edit.setPlainText("\n".join(tool.dependencies))

        # Load script
        script_path = Path(tool.script_path)
        if script_path.exists():
            self._script_edit.setPlainText(script_path.read_text(encoding="utf-8"))

        # Load parameters
        for pname, pdef in tool.parameters.items():
            self._add_param_row()
            row = self._param_table.rowCount() - 1
            self._param_table.item(row, 0).setText(pname)
            type_combo: QComboBox = self._param_table.cellWidget(row, 1)
            idx = type_combo.findText(pdef.type)
            if idx >= 0:
                type_combo.setCurrentIndex(idx)
            self._param_table.item(row, 2).setText(pdef.description)
            src_combo: QComboBox = self._param_table.cellWidget(row, 3)
            idx = src_combo.findText(pdef.source)
            if idx >= 0:
                src_combo.setCurrentIndex(idx)
            req_combo: QComboBox = self._param_table.cellWidget(row, 4)
            req_combo.setCurrentIndex(0 if pdef.required else 1)
            self._param_table.item(row, 5).setText(pdef.default or "")

    # ------------------------------------------------------------------ save
    def _on_save(self):
        name = self._name_edit.text().strip()
        desc = self._desc_edit.text().strip()

        # Validate name
        if not name:
            QMessageBox.warning(self, "错误", "请输入工具名称")
            return
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name):
            QMessageBox.warning(self, "错误", "工具名称只能包含英文字母、数字和下划线，且不能以数字开头")
            return
        if not desc:
            QMessageBox.warning(self, "错误", "请输入工具描述")
            return

        # Check duplicate name (create mode only)
        if not self._editing and self._tool_mgr.get(name):
            QMessageBox.warning(self, "错误", f"工具「{name}」已存在")
            return

        # Collect parameters
        parameters = {}
        for row in range(self._param_table.rowCount()):
            pname = (self._param_table.item(row, 0).text() or "").strip()
            if not pname:
                continue
            type_combo: QComboBox = self._param_table.cellWidget(row, 1)
            src_combo: QComboBox = self._param_table.cellWidget(row, 3)
            req_combo: QComboBox = self._param_table.cellWidget(row, 4)
            default_val = (self._param_table.item(row, 5).text() or "").strip()
            p = {
                "type": type_combo.currentText(),
                "description": (self._param_table.item(row, 2).text() or "").strip(),
                "source": src_combo.currentText(),
                "required": req_combo.currentText() == "是",
            }
            if default_val:
                p["default"] = default_val
            parameters[pname] = p

        # Collect dependencies
        deps_text = self._deps_edit.toPlainText().strip()
        dependencies = [d.strip() for d in deps_text.splitlines() if d.strip()]

        # Build manifest
        manifest = {
            "name": name,
            "description": desc,
            "script": "tool.py",
            "parameters": parameters,
            "dependencies": dependencies,
            "version": self._ver_edit.text().strip(),
            "author": self._author_edit.text().strip(),
        }

        # Write files
        tool_dir = USER_TOOLS_DIR / name
        tool_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = tool_dir / "manifest.json"
        script_path = tool_dir / "tool.py"

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        script_content = self._script_edit.toPlainText()
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script_content)

        self._tool_mgr.reload()
        self.accept()
