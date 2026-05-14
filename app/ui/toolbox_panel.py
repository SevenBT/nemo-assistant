"""Toolbox panel — browse, manage, and test user tools. Fluent Design."""
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
    QListWidgetItem,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    ListWidget,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
    ToolTipFilter,
    ToolTipPosition,
)

if TYPE_CHECKING:
    from app.core.tool_manager import ToolManager

from app.core.config import ConfigManager
from app.models.tool_def import ToolDefinition


class _ToolCard(QWidget):
    """Card widget rendered inside QListWidget via setItemWidget."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, tool: ToolDefinition, parent=None):
        super().__init__(parent)
        self._name = tool.name
        self.setMinimumHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)

        # Name + description
        text = QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)

        self._name_lbl = StrongBodyLabel(tool.name)
        text.addWidget(self._name_lbl)

        desc = tool.description[:52] + ("…" if len(tool.description) > 52 else "")
        self._desc_lbl = CaptionLabel(desc)
        text.addWidget(self._desc_lbl)

        layout.addLayout(text, 1)

        # Fluent SwitchButton
        self._toggle = SwitchButton()
        self._toggle.setChecked(tool.enabled)
        self._toggle.checkedChanged.connect(
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

        title = SubtitleLabel("还没有自定义工具")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = CaptionLabel("手动新建，或让 AI 帮你生成一个")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        new_btn = PushButton(FluentIcon.ADD, "新建工具")
        new_btn.setFixedHeight(36)
        new_btn.clicked.connect(self.create_requested)
        btn_row.addWidget(new_btn)

        gen_btn = PrimaryPushButton(FluentIcon.ROBOT, "AI 生成")
        gen_btn.setFixedHeight(36)
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

        # Header
        header = QHBoxLayout()
        header.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._name_lbl = SubtitleLabel()
        title_col.addWidget(self._name_lbl)
        self._meta_lbl = CaptionLabel()
        title_col.addWidget(self._meta_lbl)
        header.addLayout(title_col, 1)

        root.addLayout(header)
        root.addSpacing(10)

        # Description
        self._desc_lbl = BodyLabel()
        self._desc_lbl.setWordWrap(True)
        root.addWidget(self._desc_lbl)
        root.addSpacing(14)

        root.addWidget(self._divider())

        # Scrollable info
        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")

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

        # Action buttons
        root.addWidget(self._divider())
        root.addSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._edit_btn = PushButton(FluentIcon.EDIT, "编辑")
        self._edit_btn.clicked.connect(self.edit_requested)
        btn_row.addWidget(self._edit_btn)

        self._test_btn = PushButton(FluentIcon.PLAY, "测试")
        self._test_btn.clicked.connect(self.test_requested)
        btn_row.addWidget(self._test_btn)

        self._folder_btn = PushButton(FluentIcon.FOLDER, "目录")
        self._folder_btn.clicked.connect(self.folder_requested)
        btn_row.addWidget(self._folder_btn)

        btn_row.addStretch()

        self._delete_btn = PushButton(FluentIcon.DELETE, "删除")
        self._delete_btn.clicked.connect(self.delete_requested)
        btn_row.addWidget(self._delete_btn)

        root.addLayout(btn_row)

    def _divider(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        return line

    def _make_section(self, title: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        lbl = CaptionLabel(title.upper())
        layout.addWidget(lbl)
        content = BodyLabel()
        content.setObjectName(f"_section_{title}")
        content.setWordWrap(True)
        layout.addWidget(content)
        return w

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
        params_lbl = self._params_section.findChildren(BodyLabel)[0]
        if tool.parameters:
            lines = []
            for pname, pdef in tool.parameters.items():
                req = " *" if pdef.required else ""
                lines.append(
                    f"<b>{pname}</b>{req}  <span style='color:#9CA3AF'>({pdef.type})</span><br>"
                    f"<span style='color:#6B7280;font-size:11px'>{pdef.description}</span>"
                )
            params_lbl.setText("<br>".join(lines))
            params_lbl.setTextFormat(Qt.TextFormat.RichText)
        else:
            params_lbl.setText("无参数")

        # Dependencies
        deps_lbl = self._deps_section.findChildren(BodyLabel)[0]
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

        # Toolbar
        toolbar_widget = QWidget()
        toolbar = QHBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(8)

        new_btn = PushButton(FluentIcon.ADD, "新建")
        new_btn.setFixedHeight(32)
        new_btn.clicked.connect(self._on_new_tool)
        toolbar.addWidget(new_btn)

        gen_btn = PrimaryPushButton(FluentIcon.ROBOT, "AI 生成")
        gen_btn.setFixedHeight(32)
        gen_btn.clicked.connect(self._on_generate_tool)
        toolbar.addWidget(gen_btn)

        toolbar.addStretch()

        refresh_btn = TransparentToolButton(FluentIcon.SYNC)
        refresh_btn.setFixedSize(32, 32)
        refresh_btn.setToolTip("刷新")
        refresh_btn.installEventFilter(
            ToolTipFilter(refresh_btn, showDelay=400, position=ToolTipPosition.BOTTOM)
        )
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)

        root.addWidget(toolbar_widget)

        # Body: splitter
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

        self._list = ListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setSpacing(2)
        self._list.currentRowChanged.connect(self._on_select)
        left_layout.addWidget(self._list)

        self._splitter.addWidget(left)

        # Right panel
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
        w = MessageBox(
            "确认删除",
            f"确定要删除工具「{self._current_tool.name}」吗？\n此操作将删除工具目录及所有文件。",
            self.window(),
        )
        if w.exec():
            tool_dir = Path(self._current_tool.tool_dir)
            if tool_dir.exists():
                shutil.rmtree(tool_dir)
            self.refresh()

    def showEvent(self, event):
        self._load_list()
        super().showEvent(event)
