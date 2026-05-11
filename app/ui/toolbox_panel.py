"""Toolbox panel — browse, manage, and test user tools."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from app.core.tool_manager import ToolManager

from app.core.config import ConfigManager
from app.models.tool_def import ToolDefinition


class _ToggleSwitch(QPushButton):
    """Pill-shaped ON/OFF toggle that follows the app theme."""

    def __init__(self, checked: bool, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(44, 22)
        self._refresh()
        self.toggled.connect(lambda _: self._refresh())

    def _refresh(self):
        if self.isChecked():
            self.setText("ON")
            self.setStyleSheet(
                "QPushButton { background: #34D399; color: #fff; border: none;"
                " border-radius: 11px; font-size: 9px; font-weight: 700; }"
                "QPushButton:hover { background: #10B981; }"
            )
        else:
            self.setText("OFF")
            self.setStyleSheet(
                "QPushButton { background: #D1D5DB; color: #6B7280; border: none;"
                " border-radius: 11px; font-size: 9px; font-weight: 700; }"
                "QPushButton:hover { background: #9CA3AF; color: #fff; }"
            )


class _ToolCard(QWidget):
    """Card widget rendered inside QListWidget via setItemWidget."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, tool: ToolDefinition, parent=None):
        super().__init__(parent)
        self._name = tool.name
        self.setObjectName("toolListCard")
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)

        # Icon badge
        icon = QLabel("🔧")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background: #EFF6FF; border-radius: 8px; font-size: 15px;"
        )
        layout.addWidget(icon)

        # Name + description
        text = QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = QLabel(tool.name)
        self._name_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        text.addWidget(self._name_lbl)

        desc = tool.description[:52] + ("…" if len(tool.description) > 52 else "")
        self._desc_lbl = QLabel(desc)
        self._desc_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        text.addWidget(self._desc_lbl)

        layout.addLayout(text, 1)

        # Toggle
        self._toggle = _ToggleSwitch(tool.enabled)
        self._toggle.toggled.connect(
            lambda checked: self.toggled.emit(self._name, checked)
        )
        layout.addWidget(self._toggle)


class _EmptyState(QWidget):
    """Shown when no user tools exist."""

    create_requested = pyqtSignal()
    generate_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = QLabel("🔧")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 40px;")
        layout.addWidget(icon)

        title = QLabel("还没有自定义工具")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 14px; font-weight: 600;")
        layout.addWidget(title)

        hint = QLabel("手动新建，或让 AI 帮你生成一个")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("font-size: 12px; color: #9CA3AF;")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        new_btn = QPushButton("+ 新建工具")
        new_btn.setObjectName("noteToolBtn")
        new_btn.setFixedHeight(32)
        new_btn.clicked.connect(self.create_requested)
        btn_row.addWidget(new_btn)

        gen_btn = QPushButton("✨ AI 生成")
        gen_btn.setObjectName("sendBtn")
        gen_btn.setFixedHeight(32)
        gen_btn.clicked.connect(self.generate_requested)
        btn_row.addWidget(gen_btn)

        layout.addLayout(btn_row)


class _DetailPane(QWidget):
    """Right-side detail panel for a selected tool."""

    edit_requested = pyqtSignal()
    test_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 14, 14)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────
        header = QHBoxLayout()
        header.setSpacing(10)

        self._icon_lbl = QLabel("🔧")
        self._icon_lbl.setFixedSize(40, 40)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet(
            "background: #EFF6FF; border-radius: 10px; font-size: 20px;"
        )
        header.addWidget(self._icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._name_lbl = QLabel()
        self._name_lbl.setStyleSheet("font-size: 15px; font-weight: 700;")
        title_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel()
        self._meta_lbl.setStyleSheet("font-size: 11px; color: #9CA3AF;")
        title_col.addWidget(self._meta_lbl)
        header.addLayout(title_col, 1)

        root.addLayout(header)
        root.addSpacing(10)

        # ── Description ──────────────────────────────────────────────
        self._desc_lbl = QLabel()
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setStyleSheet("font-size: 12px; line-height: 1.5;")
        root.addWidget(self._desc_lbl)
        root.addSpacing(14)

        # ── Divider ──────────────────────────────────────────────────
        root.addWidget(self._divider())

        # ── Scrollable info area ─────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        info_widget = QWidget()
        self._info_layout = QVBoxLayout(info_widget)
        self._info_layout.setContentsMargins(0, 10, 0, 0)
        self._info_layout.setSpacing(14)

        self._params_section = self._make_section("参数")
        self._info_layout.addWidget(self._params_section)

        self._deps_section = self._make_section("依赖")
        self._info_layout.addWidget(self._deps_section)

        self._info_layout.addStretch()
        scroll.setWidget(info_widget)
        root.addWidget(scroll, 1)

        # ── Action buttons ───────────────────────────────────────────
        root.addWidget(self._divider())
        root.addSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self._edit_btn = self._action_btn("编辑")
        self._edit_btn.clicked.connect(self.edit_requested)
        btn_row.addWidget(self._edit_btn)

        self._test_btn = self._action_btn("▶ 测试")
        self._test_btn.clicked.connect(self.test_requested)
        btn_row.addWidget(self._test_btn)

        self._folder_btn = self._action_btn("📁 目录")
        self._folder_btn.clicked.connect(self.folder_requested)
        btn_row.addWidget(self._folder_btn)

        btn_row.addStretch()

        self._delete_btn = self._action_btn("删除")
        self._delete_btn.setStyleSheet(
            "QPushButton { color: #F87171; background: transparent; border: 1px solid #FECACA;"
            " border-radius: 6px; padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #FEF2F2; }"
        )
        self._delete_btn.clicked.connect(self.delete_requested)
        btn_row.addWidget(self._delete_btn)

        root.addLayout(btn_row)

    # ------------------------------------------------------------------ helpers
    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #E5E7EB;")
        return line

    def _action_btn(self, text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #E5E7EB;"
            " border-radius: 6px; padding: 4px 12px; font-size: 12px; }"
            "QPushButton:hover { background: #F3F4F6; }"
            "QPushButton:pressed { background: #E5E7EB; }"
        )
        return btn

    def _make_section(self, title: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        lbl = QLabel(title)
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: 700; color: #9CA3AF;"
            " text-transform: uppercase; letter-spacing: 1px;"
        )
        layout.addWidget(lbl)
        content = QLabel()
        content.setObjectName(f"_section_{title}")
        content.setWordWrap(True)
        content.setStyleSheet("font-size: 12px; color: #374151; line-height: 1.6;")
        layout.addWidget(content)
        return w

    def _section_content(self, section: QWidget) -> QLabel:
        return section.findChild(QLabel, f"_section_{section.layout().itemAt(0).widget().text()}")

    # ------------------------------------------------------------------ update
    def load(self, tool: ToolDefinition):
        self._name_lbl.setText(tool.name)

        meta = []
        if tool.version:
            meta.append(f"v{tool.version}")
        if tool.author:
            meta.append(f"by {tool.author}")
        self._meta_lbl.setText("  ·  ".join(meta) if meta else "用户工具")

        self._desc_lbl.setText(tool.description)

        # Parameters
        params_lbl = self._params_section.findChildren(QLabel)[1]
        if tool.parameters:
            lines = []
            for pname, pdef in tool.parameters.items():
                req = " *" if pdef.required else ""
                lines.append(f"<b>{pname}</b>{req}  <span style='color:#9CA3AF'>({pdef.type})</span><br>"
                             f"<span style='color:#6B7280;font-size:11px'>{pdef.description}</span>")
            params_lbl.setText("<br>".join(lines))
            params_lbl.setTextFormat(Qt.TextFormat.RichText)
        else:
            params_lbl.setText("无参数")

        # Dependencies
        deps_lbl = self._deps_section.findChildren(QLabel)[1]
        if tool.dependencies:
            deps_lbl.setText("  ".join(
                f"<span style='background:#F3F4F6;border-radius:4px;padding:2px 6px'>{d}</span>"
                for d in tool.dependencies
            ))
            deps_lbl.setTextFormat(Qt.TextFormat.RichText)
        else:
            deps_lbl.setText("无外部依赖")


class ToolboxPanel(QWidget):
    """Main toolbox panel embedded in QStackedWidget."""

    tool_toggled = pyqtSignal(str, bool)

    def __init__(self, tool_mgr: ToolManager, config: ConfigManager, parent=None):
        super().__init__(parent)
        self._tools = tool_mgr
        self._config = config
        self._current_tool: ToolDefinition | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Toolbar ──────────────────────────────────────────────────
        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("toolboxToolbar")
        toolbar_widget.setStyleSheet(
            "#toolboxToolbar { border-bottom: 1px solid #E5E7EB; }"
        )
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(6)

        new_btn = QPushButton("+ 新建")
        new_btn.setObjectName("noteToolBtn")
        new_btn.setFixedHeight(30)
        new_btn.clicked.connect(self._on_new_tool)
        toolbar.addWidget(new_btn)

        gen_btn = QPushButton("✨ AI 生成")
        gen_btn.setObjectName("sendBtn")
        gen_btn.setFixedHeight(30)
        gen_btn.clicked.connect(self._on_generate_tool)
        toolbar.addWidget(gen_btn)

        toolbar.addStretch()

        refresh_btn = QPushButton("↻")
        refresh_btn.setObjectName("iconBtn")
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setToolTip("刷新")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        root.addWidget(toolbar_widget)

        # ── Body: splitter ───────────────────────────────────────────
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)

        # Left panel
        left = QWidget()
        left.setMinimumWidth(160)
        left.setMaximumWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setObjectName("toolboxList")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setSpacing(2)
        self._list.setContentsMargins(6, 6, 6, 6)
        self._list.setStyleSheet(
            "QListWidget { background: transparent; padding: 6px; }"
            "QListWidget::item { border-radius: 8px; }"
            "QListWidget::item:selected { background: transparent; }"
        )
        self._list.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self._list)

        self._splitter.addWidget(left)

        # Right panel: stacked between empty state and detail
        self._right = QWidget()
        right_layout = QVBoxLayout(self._right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self._empty_state = _EmptyState()
        self._empty_state.create_requested.connect(self._on_new_tool)
        self._empty_state.generate_requested.connect(self._on_generate_tool)
        right_layout.addWidget(self._empty_state)

        self._detail_pane = _DetailPane()
        self._detail_pane.edit_requested.connect(self._on_edit)
        self._detail_pane.test_requested.connect(self._on_test)
        self._detail_pane.folder_requested.connect(self._on_open_folder)
        self._detail_pane.delete_requested.connect(self._on_delete)
        self._detail_pane.hide()
        right_layout.addWidget(self._detail_pane)

        self._splitter.addWidget(self._right)
        self._splitter.setSizes([200, 400])

        root.addWidget(self._splitter, 1)

    # ------------------------------------------------------------------ data
    def refresh(self):
        self._tools.reload()
        self._load_list()

    def _load_list(self):
        self._list.clear()
        all_tools = self._tools.get_tools()
        user = sorted([t for t in all_tools if not t.is_builtin], key=lambda t: t.name)

        if not user:
            self._empty_state.show()
            self._detail_pane.hide()
            return

        self._empty_state.hide()

        for tool in user:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, tool.name)
            card = _ToolCard(tool)
            card.toggled.connect(self._on_tool_toggled)
            item.setSizeHint(card.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

        self._list.setCurrentRow(0)

    def _on_select(self, row: int):
        if row < 0:
            self._detail_pane.hide()
            return
        item = self._list.item(row)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        tool = self._tools.get(name)
        if not tool:
            return
        self._current_tool = tool
        self._detail_pane.load(tool)
        self._detail_pane.show()
        self._empty_state.hide()

    def _on_tool_toggled(self, name: str, enabled: bool):
        self._tools.set_tool_enabled(name, enabled)
        self.tool_toggled.emit(name, enabled)

    # ------------------------------------------------------------------ actions
    def _on_new_tool(self):
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._tools, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_generate_tool(self):
        from app.ui.tool_generate_dialog import ToolGenerateDialog
        dlg = ToolGenerateDialog(self._tools, self._config, parent=self)
        dlg.tool_saved.connect(lambda _: self.refresh())
        dlg.exec()

    def _on_edit(self):
        if not self._current_tool:
            return
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._tools, tool=self._current_tool, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_test(self):
        if not self._current_tool:
            return
        from app.ui.tool_test_dialog import ToolTestDialog
        dlg = ToolTestDialog(self._current_tool, self._tools, parent=self)
        dlg.exec()

    def _on_open_folder(self):
        if not self._current_tool:
            return
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_tool.tool_dir))

    def _on_delete(self):
        if not self._current_tool:
            return
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定要删除工具「{self._current_tool.name}」吗？\n此操作将删除工具目录及所有文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            tool_dir = Path(self._current_tool.tool_dir)
            if tool_dir.exists():
                shutil.rmtree(tool_dir)
            self.refresh()

    def showEvent(self, event):
        self._load_list()
        super().showEvent(event)
