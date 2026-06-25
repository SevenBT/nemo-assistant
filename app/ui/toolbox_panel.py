"""能力管理器 — 浏览助手的全部能力,管理工具。

- 内置工具:展示助手开箱即用的能力(只读);仅高风险工具(执行命令、
  运行 Python、写文件)提供开关,用于安全控制。
- 我的工具:用户脚本工具,可开关 + 编辑/测试/删除。
"""
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
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    IconWidget,
    ListWidget,
    MessageBox,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TransparentToolButton,
)

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry

from app.tools.registry import HIGH_RISK_TOOLS
from app.tools.script_adapter import ScriptToolAdapter

# 工具名 → FluentIcon 成员名。找不到的工具用 DEVELOPER_TOOLS 兜底。
_TOOL_ICON_NAMES: dict[str, str] = {
    "web_search": "SEARCH",
    "fetch_url": "GLOBE",
    "clipboard": "COPY",
    "read_file": "DOCUMENT",
    "save_file": "SAVE",
    "find_files": "FOLDER",
    "grep": "SEARCH",
    "list_dir": "FOLDER",
    "note": "QUICK_NOTE",
    "memory": "LIBRARY",
    "reminder": "RINGER",
    "create_scheduled_task": "DATE_TIME",
    "list_scheduled_tasks": "DATE_TIME",
    "delete_scheduled_task": "DATE_TIME",
    "exec": "COMMAND_PROMPT",
    "run_python": "CODE",
    "multi_model_consult": "ROBOT",
}


def _icon_for(name: str) -> FluentIcon:
    """按工具名取图标,缺失则兜底,避免引用不存在的 FluentIcon 成员崩溃。"""
    icon_name = _TOOL_ICON_NAMES.get(name, "DEVELOPER_TOOLS")
    return getattr(FluentIcon, icon_name, FluentIcon.DEVELOPER_TOOLS)


# PLACEHOLDER_CARD


class _ToolCard(QWidget):
    """工具列表项卡片:图标 + 名字 + 描述,可选开关。

    通过 setItemWidget 渲染进 QListWidget。内置只读工具不显示开关;
    高风险内置工具和用户脚本工具显示开关。
    """

    toggled = pyqtSignal(str, bool)

    def __init__(self, tool, switchable: bool, parent=None):
        super().__init__(parent)
        self._name = tool.name
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)

        icon = IconWidget(_icon_for(tool.name))
        icon.setFixedSize(20, 20)
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.setContentsMargins(0, 0, 0, 0)
        self._name_lbl = StrongBodyLabel(tool.name)
        text.addWidget(self._name_lbl)
        desc = tool.description[:100] + ("…" if len(tool.description) > 100 else "")
        self._desc_lbl = CaptionLabel(desc)
        self._desc_lbl.setWordWrap(True)
        self._desc_lbl.setMaximumHeight(36)
        text.addWidget(self._desc_lbl)
        layout.addLayout(text, 1)

        if switchable:
            self._toggle = SwitchButton()
            self._toggle.setChecked(tool.enabled)
            self._toggle.checkedChanged.connect(
                lambda checked: self.toggled.emit(self._name, checked)
            )
            layout.addWidget(self._toggle)
        else:
            self._toggle = None


# PLACEHOLDER_DETAIL


class _DetailPane(QWidget):
    """右侧详情面板。内置工具只展示信息;脚本工具额外提供编辑/测试/删除。"""

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

        header = QHBoxLayout()
        header.setSpacing(10)
        self._icon = IconWidget(FluentIcon.DEVELOPER_TOOLS)
        self._icon.setFixedSize(28, 28)
        header.addWidget(self._icon)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._name_lbl = SubtitleLabel()
        title_col.addWidget(self._name_lbl)
        self._meta_lbl = CaptionLabel()
        title_col.addWidget(self._meta_lbl)
        header.addLayout(title_col, 1)
        root.addLayout(header)
        root.addSpacing(10)

        self._desc_lbl = BodyLabel()
        self._desc_lbl.setWordWrap(True)
        root.addWidget(self._desc_lbl)
        root.addSpacing(14)
        root.addWidget(self._divider())

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

        # 仅脚本工具显示的操作区
        self._actions = QWidget()
        act_root = QVBoxLayout(self._actions)
        act_root.setContentsMargins(0, 0, 0, 0)
        act_root.setSpacing(0)
        act_root.addWidget(self._divider())
        act_root.addSpacing(10)
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
        act_root.addLayout(btn_row)
        root.addWidget(self._actions)

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

    # PLACEHOLDER_DETAIL_LOAD
    def load(self, tool):
        is_script = isinstance(tool, ScriptToolAdapter)
        self._icon.setIcon(_icon_for(tool.name))
        self._name_lbl.setText(tool.name)

        if is_script:
            meta = []
            if tool.version:
                meta.append(f"v{tool.version}")
            if tool.author:
                meta.append(f"by {tool.author}")
            self._meta_lbl.setText("  ·  ".join(meta) if meta else "我的工具")
        elif tool.name in HIGH_RISK_TOOLS:
            self._meta_lbl.setText("内置工具  ·  高风险,可关闭")
        else:
            self._meta_lbl.setText("内置工具")

        self._desc_lbl.setText(tool.description)

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

        # 依赖区仅对脚本工具有意义
        deps_lbl = self._deps_section.findChildren(BodyLabel)[0]
        if is_script:
            self._deps_section.show()
            if tool.dependencies:
                deps_lbl.setText("  ".join(
                    f"<span style='background:#F3F4F6;border-radius:4px;padding:2px 6px'>{d}</span>"
                    for d in tool.dependencies
                ))
                deps_lbl.setTextFormat(Qt.TextFormat.RichText)
            else:
                deps_lbl.setText("无外部依赖")
        else:
            self._deps_section.hide()

        # 操作区仅脚本工具可见
        self._actions.setVisible(is_script)


# PLACEHOLDER_PANEL


class ToolboxPanel(QWidget):
    """能力管理器,嵌入主窗口 StackedWidget。"""

    tool_toggled = pyqtSignal(str, bool)

    def __init__(self, registry: "ToolRegistry", parent=None):
        super().__init__(parent)
        self._registry = registry
        self._current_tool = None
        self._saved_list_width: int | None = None
        self._build()

        from app.core.config import cfg
        from app.ui.components.font_delegate import FontAwareListDelegate
        self._list.setItemDelegate(FontAwareListDelegate(self._list))
        self._apply_font_size()
        cfg.navigationFontSize.valueChanged.connect(self._apply_font_size)

    def _apply_font_size(self, _value=None):
        from app.core.config import cfg
        from PyQt6.QtGui import QFont  # noqa: F401
        size = cfg.get(cfg.navigationFontSize)
        font = self._list.font()
        font.setPixelSize(size)
        self._list.setFont(font)

    def _build(self):
        from PyQt6.QtWidgets import QSplitter
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(6)
        self._splitter.setChildrenCollapsible(True)

        # 左侧列表
        left = QWidget()
        left.setObjectName("toolListPanel")
        left.setMinimumWidth(180)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 10, 8, 8)
        left_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = CaptionLabel("能力")
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

        # 右侧详情
        self._right = QWidget()
        right_layout = QVBoxLayout(self._right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self._detail_pane = _DetailPane()
        self._detail_pane.edit_requested.connect(self._on_edit)
        self._detail_pane.test_requested.connect(self._on_test)
        self._detail_pane.folder_requested.connect(self._on_open_folder)
        self._detail_pane.delete_requested.connect(self._on_delete)
        self._detail_pane.hide()
        right_layout.addWidget(self._detail_pane)
        self._splitter.addWidget(self._right)
        self._splitter.setStretchFactor(0, 0)  # 工具列表：固定宽度
        self._splitter.setStretchFactor(1, 1)  # 详情区域：占据剩余空间
        self._splitter.setSizes([220, 400])
        root.addWidget(self._splitter, 1)

    # PLACEHOLDER_PANEL_DATA
    def refresh(self):
        self._reload_user_tools()
        self._load_list()

    def _reload_user_tools(self):
        """重新加载用户脚本工具(保留内置工具),并重新应用开关状态。"""
        from app.core.config import cfg, USER_TOOLS_DIR
        from app.tools.loader import load_user_script_tools
        for tool in list(self._registry.get_all()):
            if isinstance(tool, ScriptToolAdapter):
                self._registry.unregister(tool.name)
        load_user_script_tools(USER_TOOLS_DIR, self._registry)
        self._registry.apply_saved_states(cfg.get(cfg.toolStates))

    def _add_group_header(self, text: str):
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选中
        item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(item)

    def _add_tool_item(self, tool, switchable: bool):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, tool.name)
        card = _ToolCard(tool, switchable=switchable)
        if switchable:
            card.toggled.connect(self._on_tool_toggled)
        item.setSizeHint(card.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def _load_list(self):
        self._list.clear()
        all_tools = self._registry.get_all()
        builtin = sorted(
            [t for t in all_tools if not isinstance(t, ScriptToolAdapter)],
            key=lambda t: t.name,
        )
        scripts = sorted(
            [t for t in all_tools if isinstance(t, ScriptToolAdapter)],
            key=lambda t: t.name,
        )

        if builtin:
            self._add_group_header("内置能力")
            for tool in builtin:
                # 仅高风险内置工具可开关,其余只读展示
                self._add_tool_item(tool, switchable=tool.name in HIGH_RISK_TOOLS)

        self._add_group_header("我的工具")
        if scripts:
            for tool in scripts:
                self._add_tool_item(tool, switchable=True)
        else:
            hint = QListWidgetItem("还没有自定义工具 — 点上方 + 或 🤖 添加")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(hint)

        # 默认选中第一个真实工具
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole):
                self._list.setCurrentRow(i)
                break

    def _on_select(self, row: int):
        if row < 0:
            self._detail_pane.hide()
            return
        item = self._list.item(row)
        if not item:
            return
        name = item.data(Qt.ItemDataRole.UserRole)
        if not name:  # 分组标题或提示行
            self._detail_pane.hide()
            return
        tool = self._registry.get(name)
        if not tool:
            return
        self._current_tool = tool
        self._detail_pane.load(tool)
        self._detail_pane.show()

    def _on_tool_toggled(self, name: str, enabled: bool):
        from app.core.config import cfg
        tool = self._registry.get(name)
        if tool is not None:
            tool.enabled = enabled
        states = dict(cfg.get(cfg.toolStates))
        states[name] = enabled
        cfg.set(cfg.toolStates, states)
        self.tool_toggled.emit(name, enabled)

    # PLACEHOLDER_PANEL_ACTIONS
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
        if not isinstance(self._current_tool, ScriptToolAdapter):
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
        if not isinstance(self._current_tool, ScriptToolAdapter):
            return
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_tool.tool_dir))

    def _on_delete(self):
        if not isinstance(self._current_tool, ScriptToolAdapter):
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
        """切换工具列表显示(由 TitleBar 调用)。"""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        list_width = sizes[0]
        if list_width > 0:
            self._saved_list_width = list_width
            self._splitter.setSizes([0, total])
        else:
            width = self._saved_list_width or 220
            self._splitter.setSizes([width, total - width])

    def apply_search(self, keyword: str):
        """按关键字过滤工具列表(由 TitleBar 调用)。"""
        kw = keyword.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            if not name:  # 分组标题:有过滤词时隐藏,否则保留
                item.setHidden(bool(kw))
                continue
            item.setHidden(bool(kw) and kw not in name.lower())
