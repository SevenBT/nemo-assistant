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
)

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry

from app.tools.script_adapter import ScriptToolAdapter


class _ToolCard(QWidget):
    """Card widget rendered inside QListWidget via setItemWidget."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, tool: ScriptToolAdapter, parent=None):
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
    def load(self, tool: ScriptToolAdapter):
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
        properties = tool.parameters.get("properties", {})
        required_list = tool.parameters.get("required", [])
        if properties:
            lines = []
            for pname, pdata in properties.items():
                req = " *" if pname in required_list else ""
                ptype = pdata.get("type", "string")
                pdesc = pdata.get("description", "")
                lines.append(
                    f"<b>{pname}</b>{req}  <span style='color:#9CA3AF'>({ptype})</span><br>"
                    f"<span style='color:#6B7280;font-size:11px'>{pdesc}</span>"
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

    def __init__(self, registry: "ToolRegistry", parent=None):
        super().__init__(parent)
        self._registry = registry
        self._current_tool: ScriptToolAdapter | None = None
        self._saved_list_width: int | None = None
        self._build()

        from app.core.config import cfg
        from app.ui.components.font_delegate import FontAwareListDelegate
        self._list.setItemDelegate(FontAwareListDelegate(self._list))
        self._apply_font_size()
        cfg.navigationFontSize.valueChanged.connect(self._apply_font_size)

    def _apply_font_size(self, _value=None):
        from app.core.config import cfg
        from PyQt6.QtGui import QFont
        size = cfg.get(cfg.navigationFontSize)
        font = self._list.font()
        font.setPixelSize(size)
        self._list.setFont(font)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Body: splitter
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)

        # Left panel — styled to match session/notes panel
        left = QWidget()
        left.setObjectName("toolListPanel")
        left.setMinimumWidth(160)
        left.setMaximumWidth(260)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 10, 8, 8)
        left_layout.setSpacing(8)

        # Header row — matches session panel pattern
        header = QHBoxLayout()
        header.setSpacing(6)
        title = CaptionLabel("工具")
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch()

        new_btn = TransparentToolButton(FluentIcon.ADD)
        new_btn.setFixedSize(30, 30)
        new_btn.setToolTip("新建工具")
        new_btn.clicked.connect(self._on_new_tool)
        header.addWidget(new_btn)

        gen_btn = TransparentToolButton(FluentIcon.ROBOT)
        gen_btn.setFixedSize(30, 30)
        gen_btn.setToolTip("AI 生成工具")
        gen_btn.clicked.connect(self._on_generate_tool)
        header.addWidget(gen_btn)

        refresh_btn = TransparentToolButton(FluentIcon.SYNC)
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setToolTip("刷新")
        refresh_btn.clicked.connect(self.refresh)
        header.addWidget(refresh_btn)

        left_layout.addLayout(header)

        self._list = ListWidget()
        self._list.setObjectName("toolList")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
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
        self._reload_user_tools()
        self._load_list()

    def _reload_user_tools(self):
        """重新加载用户脚本工具（保留内置工具）。"""
        from app.core.config import USER_TOOLS_DIR
        from app.tools.loader import load_user_script_tools
        # 移除已有的 ScriptToolAdapter
        for tool in list(self._registry.get_all()):
            if isinstance(tool, ScriptToolAdapter):
                self._registry.unregister(tool.name)
        load_user_script_tools(USER_TOOLS_DIR, self._registry)

    def _load_list(self):
        self._list.clear()
        user_tools = sorted(
            [t for t in self._registry.get_all() if isinstance(t, ScriptToolAdapter)],
            key=lambda t: t.name,
        )

        if not user_tools:
            self._empty_state.show()
            self._detail_pane.hide()
            return

        self._empty_state.hide()

        for tool in user_tools:
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
        tool = self._registry.get(name)
        if not tool or not isinstance(tool, ScriptToolAdapter):
            return
        self._current_tool = tool
        self._detail_pane.load(tool)
        self._detail_pane.show()
        self._empty_state.hide()

    def _on_tool_toggled(self, name: str, enabled: bool):
        from app.core.config import cfg
        tool = self._registry.get(name)
        if tool and isinstance(tool, ScriptToolAdapter):
            tool.enabled = enabled
        states = dict(cfg.get(cfg.toolStates))
        states[name] = enabled
        cfg.set(cfg.toolStates, states)
        self.tool_toggled.emit(name, enabled)

    # ------------------------------------------------------------------ actions
    def _on_new_tool(self):
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._registry, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_generate_tool(self):
        from app.ui.tool_generate_dialog import ToolGenerateDialog
        dlg = ToolGenerateDialog(self._registry, parent=self)
        dlg.tool_saved.connect(lambda _: self.refresh())
        dlg.exec()

    def _on_edit(self):
        if not self._current_tool:
            return
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._registry, tool=self._current_tool, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_test(self):
        if not self._current_tool:
            return
        from app.ui.tool_test_dialog import ToolTestDialog
        dlg = ToolTestDialog(self._current_tool, self._registry, parent=self)
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

    def toggle_list(self):
        """Public: toggle tool list visibility (called from TitleBar)."""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        list_width = sizes[0]
        if list_width > 0:
            self._saved_list_width = list_width
            self._splitter.setSizes([0, total])
        else:
            width = self._saved_list_width or 200
            self._splitter.setSizes([width, total - width])

    def apply_search(self, keyword: str):
        """Public: filter tool list by keyword (called from TitleBar)."""
        kw = keyword.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole) or ""
            item.setHidden(bool(kw) and kw not in name.lower())
