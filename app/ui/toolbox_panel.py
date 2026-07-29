"""能力管理器 — 浏览助手的全部能力,管理工具。

- 内置工具:展示助手开箱即用的能力(只读);仅高风险工具(执行命令、
  运行 Python、写文件)提供开关,用于安全控制。
- 我的工具:用户脚本工具,可开关 + 编辑/测试/删除。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtCore import QEvent, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QKeyEvent
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
    CheckBox,
    FluentIcon,
    IconWidget,
    ListWidget,
    MessageBox,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TransparentToolButton,
)

if TYPE_CHECKING:
    from app.tools.registry import ToolRegistry

from app.i18n import t
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
    "scheduled_task": "DATE_TIME",
    "exec": "COMMAND_PROMPT",
    "run_python": "CODE",
    "multi_model_consult": "ROBOT",
}


def _icon_for(name: str) -> FluentIcon:
    """按工具名取图标,缺失则兜底,避免引用不存在的 FluentIcon 成员崩溃。"""
    icon_name = _TOOL_ICON_NAMES.get(name, "DEVELOPER_TOOLS")
    return getattr(FluentIcon, icon_name, FluentIcon.DEVELOPER_TOOLS)


# PLACEHOLDER_CARD


class _StatusDot(CheckBox):
    """Accessible text-and-checked-state control for a tool's enabled status."""

    def __init__(
        self,
        checked: bool,
        enabled: bool,
        tool_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        self._tool_name = tool_name
        self._interactive = enabled
        self.setEnabled(enabled)
        self.setChecked(checked)
        self.setText(t("workshop.status.enabled" if checked else "workshop.status.disabled"))
        self.stateChanged.connect(self._refresh_accessibility)
        self._refresh_accessibility()
        self.setMinimumSize(24, 24)
        self.setFixedHeight(24)
        self.setStyleSheet("min-height: 24px; max-height: 24px;")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _refresh_accessibility(self) -> None:
        state_key = "workshop.status.enabled" if self.isChecked() else "workshop.status.disabled"
        state = t(state_key)
        self.setText(state)
        self.setToolTip(t("workshop.tip.enabled" if self.isChecked() else "workshop.tip.disabled"))
        self.setAccessibleName(
            t("workshop.a11y.status_toggle", name=self._tool_name, state=state)
        )
        self.setAccessibleDescription(
            t("workshop.a11y.status_toggle_description", state=state)
        )

    def event(self, event: QEvent) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
        ):
            if event.type() == QEvent.Type.ShortcutOverride:
                event.accept()
                return True
            if event.type() == QEvent.Type.KeyPress:
                self.click()
                event.accept()
                return True
        return super().event(event)



class _ToolCard(QWidget):
    """工具列表项卡片:图标 + 名字 + 描述,可选开关。

    通过 setItemWidget 渲染进 QListWidget。所有内置工具与用户脚本工具
    均显示开关;高风险内置工具仅在详情页 meta 标签上额外警示。
    """

    toggled = pyqtSignal(str, bool)

    def __init__(self, tool, switchable: bool, parent=None) -> None:
        super().__init__(parent)
        self._name = tool.name
        self.setMinimumHeight(64)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(10)

        icon = IconWidget(_icon_for(tool.name))
        icon.setFixedSize(20, 20)
        layout.addWidget(icon)

        # 名字前的状态圆点兼开关：绿=启用/灰=禁用，点击切换
        if switchable:
            reason = tool.unavailable_reason
            self._toggle = _StatusDot(
                checked=tool.enabled,
                enabled=not reason,
                tool_name=tool.name,
            )
            if reason:
                # 前置条件缺失（如未配 API Key）：置灰不可点并说明原因，
                # 避免用户"点了没反应"的困惑。
                self._toggle.setToolTip(reason)
            else:
                self._toggle.clicked.connect(self._on_dot_clicked)
            layout.addWidget(self._toggle)
        else:
            self._toggle = None

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

    def _on_dot_clicked(self) -> None:
        self.toggled.emit(self._name, self._toggle.isChecked())


# PLACEHOLDER_DETAIL


class _DetailPane(QWidget):
    """右侧详情面板。内置工具只展示信息;脚本工具额外提供编辑/测试/删除。"""

    edit_requested = pyqtSignal()
    test_requested = pyqtSignal()
    folder_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 14, 14)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(10)
        self._icon = IconWidget(FluentIcon.DEVELOPER_TOOLS)
        self._icon.setFixedSize(28, 28)
        self._icon.setAccessibleName(t("workshop.a11y.detail_icon"))
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

        scroll = ScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setStyleSheet("background: transparent;")
        info_widget = QWidget()
        self._info_layout = QVBoxLayout(info_widget)
        self._info_layout.setContentsMargins(0, 10, 0, 0)
        self._info_layout.setSpacing(14)
        self._params_section = self._make_section(t("workshop.detail.params"))
        self._info_layout.addWidget(self._params_section)
        self._permissions_section = self._make_section(t("workshop.detail.permissions"))
        self._info_layout.addWidget(self._permissions_section)
        self._deps_section = self._make_section(t("workshop.detail.deps"))
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
        self._edit_btn = PushButton(FluentIcon.EDIT, t("workshop.action.edit"))
        self._edit_btn.clicked.connect(self.edit_requested)
        btn_row.addWidget(self._edit_btn)
        self._test_btn = PushButton(FluentIcon.PLAY, t("workshop.action.test"))
        self._test_btn.clicked.connect(self.test_requested)
        btn_row.addWidget(self._test_btn)
        self._folder_btn = PushButton(FluentIcon.FOLDER, t("workshop.action.folder"))
        self._folder_btn.clicked.connect(self.folder_requested)
        btn_row.addWidget(self._folder_btn)
        btn_row.addStretch()
        self._delete_btn = PushButton(FluentIcon.DELETE, t("workshop.action.delete"))
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
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        content.setAccessibleName(title)
        layout.addWidget(content)
        return w

    # PLACEHOLDER_DETAIL_LOAD
    def load(self, tool: object) -> None:
        is_script = isinstance(tool, ScriptToolAdapter)
        self._icon.setIcon(_icon_for(tool.name))
        self._name_lbl.setText(tool.name)

        if is_script:
            meta = []
            if tool.version:
                meta.append(f"v{tool.version}")
            if tool.author:
                meta.append(t("workshop.meta.author", author=tool.author))
            if tool.is_legacy_manifest is True:
                meta.append(t("workshop.meta.legacy_unreviewed"))
            elif tool.is_legacy_manifest is False:
                meta.append(t("workshop.meta.strict_review_unknown"))
            else:
                meta.append(t("workshop.meta.review_unknown"))
            self._meta_lbl.setText("  ·  ".join(meta))
        elif tool.name in HIGH_RISK_TOOLS:
            self._meta_lbl.setText(t("workshop.meta.builtin_highrisk"))
        else:
            self._meta_lbl.setText(t("workshop.meta.builtin"))

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
            params_lbl.setText(t("workshop.detail.no_params"))

        permissions_lbl = self._permissions_section.findChildren(BodyLabel)[0]
        if is_script:
            self._permissions_section.show()
            permissions = sorted(permission.value for permission in tool.permissions)
            permissions_lbl.setText(
                "\n".join(f"• {permission}" for permission in permissions)
                if permissions
                else t("workshop.detail.no_permissions")
            )
        else:
            self._permissions_section.hide()

        # 依赖区仅对脚本工具有意义
        deps_lbl = self._deps_section.findChildren(BodyLabel)[0]
        if is_script:
            self._deps_section.show()
            if tool.dependencies:
                missing = frozenset(tool.missing_dependencies)
                dependency_text = "\n".join(
                    t(
                        "workshop.detail.dependency_row",
                        dependency=dependency,
                        status=t(
                            "workshop.detail.dependency_missing"
                            if dependency in missing
                            else "workshop.detail.dependency_installed"
                        ),
                    )
                    for dependency in tool.dependencies
                )
            else:
                dependency_text = t("workshop.detail.no_deps")
            dependency_notice = t(
                "workshop.detail.legacy_deps_warning"
                if tool.is_legacy_manifest
                else "workshop.detail.strict_deps_notice"
            )
            deps_lbl.setText(f"{dependency_text}\n{dependency_notice}")
            deps_lbl.setTextFormat(Qt.TextFormat.PlainText)
        else:
            self._deps_section.hide()

        # 操作区仅脚本工具可见；严格工具不能进入旧版直接写编辑器。
        self._actions.setVisible(is_script)
        can_legacy_edit = is_script and tool.is_legacy_manifest is True
        self._edit_btn.setEnabled(can_legacy_edit)
        self._edit_btn.setToolTip(
            "" if can_legacy_edit else t("workshop.action.strict_edit_disabled")
        )


# PLACEHOLDER_PANEL


class ToolboxPanel(QWidget):
    """能力管理器,嵌入主窗口 StackedWidget。"""

    tool_toggled = pyqtSignal(str, bool)

    def __init__(self, registry: ToolRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry
        self._current_tool = None
        self._saved_list_width: int | None = None
        self._loaded = False
        self._build()

        from app.core.config import cfg
        from app.ui.components.font_delegate import FontAwareListDelegate
        self._list.setItemDelegate(FontAwareListDelegate(self._list))
        self._apply_font_size()
        cfg.navigationFontSize.valueChanged.connect(self._apply_font_size)

    def _apply_font_size(self, _value: object = None) -> None:
        from app.core.config import cfg
        from PyQt6.QtGui import QFont  # noqa: F401
        size = cfg.get(cfg.navigationFontSize)
        font = self._list.font()
        font.setPixelSize(size)
        self._list.setFont(font)

    def _build(self) -> None:
        from PyQt6.QtWidgets import QSplitter
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(6)
        # setChildrenCollapsible(False) + 左侧 minimumWidth 防止用户拖动分割条把
        # 列表误折叠到 0 宽；程序化折叠时在 toggle_list 内临时放开约束。
        self._splitter.setChildrenCollapsible(False)

        # 左侧列表
        left = QWidget()
        self._left = left
        left.setObjectName("toolListPanel")
        left.setMinimumWidth(180)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 10, 8, 8)
        left_layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        title = CaptionLabel(t("workshop.title"))
        title.setObjectName("panelTitle")
        header.addWidget(title)
        header.addStretch()
        new_btn = TransparentToolButton(FluentIcon.ADD)
        new_btn.setFixedSize(30, 30)
        new_btn.setToolTip(t("workshop.tip.new"))
        new_btn.setAccessibleName(t("workshop.tip.new"))
        new_btn.clicked.connect(self._on_new_tool)
        header.addWidget(new_btn)
        gen_btn = TransparentToolButton(FluentIcon.ROBOT)
        gen_btn.setFixedSize(30, 30)
        gen_btn.setToolTip(t("workshop.tip.generate"))
        gen_btn.setAccessibleName(t("workshop.tip.generate"))
        gen_btn.clicked.connect(self._on_generate_tool)
        header.addWidget(gen_btn)
        refresh_btn = TransparentToolButton(FluentIcon.SYNC)
        refresh_btn.setFixedSize(30, 30)
        refresh_btn.setToolTip(t("workshop.tip.refresh"))
        refresh_btn.setAccessibleName(t("workshop.tip.refresh"))
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
        self._right.setObjectName("toolDetailPanel")
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
    def refresh(self) -> None:
        self._reload_user_tools()
        self._load_list()

    def _reload_user_tools(self) -> None:
        """重新加载用户脚本工具(保留内置工具),并重新应用开关状态。"""
        from app.core.config import cfg, USER_TOOLS_DIR
        from app.tools.loader import load_user_script_tools
        for tool in list(self._registry.get_all()):
            if isinstance(tool, ScriptToolAdapter):
                self._registry.unregister(tool.name)
        load_user_script_tools(USER_TOOLS_DIR, self._registry)
        self._registry.apply_saved_states(cfg.get(cfg.toolStates))

    def _add_group_header(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选中
        item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(item)

    def _add_tool_item(self, tool: object, switchable: bool) -> None:
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, tool.name)
        card = _ToolCard(tool, switchable=switchable)
        if switchable:
            card.toggled.connect(self._on_tool_toggled)
        item.setSizeHint(card.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def _load_list(self) -> None:
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
            self._add_group_header(t("workshop.group.builtin"))
            for tool in builtin:
                # 所有内置工具均可开关;高风险工具仅在详情页 meta 标签上额外警示
                self._add_tool_item(tool, switchable=True)

        self._add_group_header(t("workshop.group.mine"))
        if scripts:
            for tool in scripts:
                self._add_tool_item(tool, switchable=True)
        else:
            hint = QListWidgetItem(t("workshop.empty_hint"))
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            self._list.addItem(hint)

        # 默认选中第一个真实工具
        for i in range(self._list.count()):
            if self._list.item(i).data(Qt.ItemDataRole.UserRole):
                self._list.setCurrentRow(i)
                break

    def _on_select(self, row: int) -> None:
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

    def _on_tool_toggled(self, name: str, enabled: bool) -> None:
        from app.core.config import cfg
        tool = self._registry.get(name)
        if tool is not None:
            tool.enabled = enabled
        states = dict(cfg.get(cfg.toolStates))
        states[name] = enabled
        cfg.set(cfg.toolStates, states)
        self.tool_toggled.emit(name, enabled)

    # PLACEHOLDER_PANEL_ACTIONS
    def _on_new_tool(self) -> None:
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._registry, parent=self)
        if dlg.exec():
            self.refresh()

    @pyqtSlot(str)
    def _on_generated_tool_saved(self, name: str) -> None:
        """Persist a successful generated-tool installation as enabled, then reload."""

        from app.core.config import cfg

        states = {**dict(cfg.get(cfg.toolStates)), name: True}
        cfg.set(cfg.toolStates, states)
        tool = self._registry.get(name)
        if tool is not None:
            tool.enabled = True
        self.refresh()

    def _on_generate_tool(self) -> None:
        from app.ui.tool_generate_dialog import ToolGenerateDialog
        dlg = ToolGenerateDialog(self._registry, parent=self)
        dlg.tool_saved.connect(self._on_generated_tool_saved)
        dlg.exec()

    def _on_edit(self) -> None:
        if not isinstance(self._current_tool, ScriptToolAdapter):
            return
        if self._current_tool.is_legacy_manifest is not True:
            self._detail_pane._edit_btn.setEnabled(False)
            self._detail_pane._edit_btn.setToolTip(
                t("workshop.action.strict_edit_disabled")
            )
            return
        from app.ui.tool_editor_dialog import ToolEditorDialog
        dlg = ToolEditorDialog(self._registry, tool=self._current_tool, parent=self)
        if dlg.exec():
            self.refresh()

    def _on_test(self) -> None:
        if not self._current_tool:
            return
        from app.ui.tool_test_dialog import ToolTestDialog
        dlg = ToolTestDialog(self._current_tool, self._registry, parent=self)
        dlg.exec()

    def _on_open_folder(self) -> None:
        if not isinstance(self._current_tool, ScriptToolAdapter):
            return
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._current_tool.tool_dir))

    def _on_delete(self) -> None:
        if not isinstance(self._current_tool, ScriptToolAdapter):
            return
        w = MessageBox(
            t("workshop.delete.title"),
            t("workshop.delete.body", name=self._current_tool.name),
            self.window(),
        )
        if w.exec():
            tool_dir = Path(self._current_tool.tool_dir)
            if tool_dir.exists():
                shutil.rmtree(tool_dir)
            self.refresh()

    def showEvent(self, event: object) -> None:
        # 仅首次显示时加载；工具增删改由各对话框显式调用 refresh()。
        # 每次 showEvent 都整表重建会让切 tab 时列表与详情区跳动。
        if not self._loaded:
            self._load_list()
            self._loaded = True
        super().showEvent(event)

    def toggle_list(self) -> None:
        """切换工具列表显示(由 TitleBar 调用)。"""
        sizes = self._splitter.sizes()
        total = sum(sizes)
        list_width = sizes[0]
        if list_width > 0:
            self._saved_list_width = list_width
            # setChildrenCollapsible(False) + minimumWidth 会把 setSizes([0,…])
            # 夹回最小宽，程序化折叠时临时放开约束，展开后恢复。
            self._left.setMinimumWidth(0)
            self._splitter.setChildrenCollapsible(True)
            self._splitter.setSizes([0, total])
        else:
            self._left.setMinimumWidth(180)
            self._splitter.setChildrenCollapsible(False)
            width = self._saved_list_width or 220
            self._splitter.setSizes([width, total - width])

    def apply_search(self, keyword: str) -> None:
        """按关键字过滤工具列表(由 TitleBar 调用)。"""
        kw = keyword.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            if not name:  # 分组标题:有过滤词时隐藏,否则保留
                item.setHidden(bool(kw))
                continue
            item.setHidden(bool(kw) and kw not in name.lower())
