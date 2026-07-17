"""
Main floating window.

Layout:
  ┌─ TitleBar ───────────────────────────────────────────────────┐
  │ [≡] Nemo Assistant ── [聊天] [笔记] [工坊] ── [截图] [─] [□] [✕]  │
  ├──────────────────────────────────────────────────────────────┤
  │ FluentWindow stackedWidget                                   │
  │  page 0: SessionPanel | ChatWidget + InputWidget             │
  │  page 1: NotesPanel                                          │
  │  page 2: ToolboxPanel                                        │
  └──────────────────────────────────────────────────────────────┘

主浮窗。无边框透明窗口，三页（聊天 / 笔记 / 工坊）通过 stackedWidget 切换。
"""
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QLabel,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.config import cfg, USER_TOOLS_DIR
from app.i18n import t
from app.core.conversation_prompt_builder import ConversationPromptBuilder
from app.core.llm_gateway import LLMGateway
from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager
from app.core.session_manager import SessionManager
from app.core.trace_store import TraceStore
from app.models.session import SOURCE_MANUAL
from app.tools.context import ToolContext, ToolEvents
from app.tools.loader import load_builtin_tools, load_user_script_tools
from app.tools.registry import DEFAULT_OFF_TOOLS, ToolRegistry
from app.ui.chat_session_controller import ChatSessionController
from app.ui.chat_widget import ChatWidget
from app.ui.edge_snap import EdgeSnapManager
from app.ui.input_widget import InputWidget
from app.ui.notes_dialog import NotesPanel
from app.core.hotkey_manager import HotkeyManager
from app.ui.resize_filter import ResizeFilter
from app.ui.screenshot_controller import ScreenshotController
from app.ui.selection_controller import SelectionController
from app.core.selection_monitor import SelectionMonitor
from app.ui.toolbox_panel import ToolboxPanel
from app.ui.session_panel import SessionPanel
from app.ui.settings_window import SettingsWindow
from app.ui.sticky_note_controller import StickyNoteController
from app.ui.style import DEFAULT_THEME, THEMES, apply_theme
from app.ui.title_bar import TitleBar
from app.ui.toast import show_toast
from app.ui.tray_manager import TrayManager
from qfluentwidgets import FluentWindow, FluentIcon


# ─────────────────────────────────────────────────────────────────────
class MainWindow(FluentWindow):
    # 将调度器后台回调 marshal 到主线程
    _notify_signal = pyqtSignal(str, str)  # 标题, 正文
    # 笔记内容更新信号 (note_id, title, content)
    note_updated = pyqtSignal(int, str, str)
    # 将 worker 线程的笔记创建回调 marshal 到主线程
    _note_created_signal = pyqtSignal()
    # 工具确认请求信号 (title, message, result_holder)
    _confirm_request = pyqtSignal(str, str, object)

    def __init__(
        self,
        session_mgr: SessionManager,
        scheduler: SchedulerManager,
        note_mgr: NoteManager,
    ):
        super().__init__()
        # 替换 FluentWindow 默认的 FluentTitleBar。
        # 先断开旧标题栏的显示信号，再强制隐藏残留子控件。
        old_title_bar = self.titleBar
        self.navigationInterface.displayModeChanged.disconnect()
        self._title_bar = TitleBar(self)
        self.setTitleBar(self._title_bar)
        # setTitleBar 内部调用 deleteLater（异步），立即隐藏防止闪烁
        old_title_bar.hide()
        for child in old_title_bar.findChildren(QWidget):
            child.hide()
        # 清除 qframelesswindow 残留的 TitleBarButton（如红色关闭按钮）
        from qframelesswindow import TitleBarButton
        for btn in self.findChildren(TitleBarButton):
            btn.setFixedSize(0, 0)
            btn.hide()
            btn.deleteLater()

        self._sessions = session_mgr
        self._scheduler = scheduler
        self._notes = note_mgr
        self._registry = ToolRegistry()
        # 统一 trace 存储：贯穿 LLM 调用与工具调用，落独立 traces.db。
        self._trace_store = TraceStore()
        # 启动时清理一次历史 trace，防止 traces.db 无限增长耗尽磁盘。
        self._trace_store.prune()
        self._llm_gateway = LLMGateway(trace_sink=self._trace_store)
        self._snap_mgr: EdgeSnapManager | None = None

        self._build_window()
        self._build_ui()
        self._screenshot_controller = ScreenshotController(self)
        self._sticky_note_controller = StickyNoteController(
            note_mgr=self._notes,
            notes_panel=self._notes_panel,
            parent=self,
        )
        self._sticky_note_controller.note_updated.connect(self._on_note_updated)
        self._init_tools()
        self._init_memory()
        self._prompt_builder = ConversationPromptBuilder(
            session_mgr=self._sessions,
            memory_mgr=self._memory_mgr,
            enabled_tools_provider=lambda: [tool.name for tool in self._registry.get_enabled()],
        )
        self._chat_session_controller = ChatSessionController(
            parent=self,
            session_mgr=self._sessions,
            llm_gateway=self._llm_gateway,
            registry=self._registry,
            prompt_builder=self._prompt_builder,
            chat=self._chat,
            input_widget=self._input,
            session_panel=self._session_panel,
            tool_status=self._tool_status,
            consolidator=self._consolidator,
            trace_store=self._trace_store,
        )
        # 消息级操作（复制/重新生成/编辑）：气泡信号 → 会话控制器。
        # 必须在控制器创建之后连接（_build_ui 阶段控制器尚不存在）。
        self._chat.copy_message.connect(self._chat_session_controller.copy_reply)
        self._chat.regenerate_message.connect(
            self._chat_session_controller.regenerate_last
        )
        self._chat.edit_message.connect(self._chat_session_controller.edit_last)
        # 识图：每次截图动作新建一个会话，附上图片并按动作处理（自动发送或等输入）
        self._screenshot_controller.set_chat_callbacks(
            vision_callback=self._chat_session_controller.start_vision_session,
        )
        # 划词即行动：取词 → 弹动作条 → 分发到气泡/主窗/笔记库
        self._selection_controller = SelectionController(
            self,
            note_mgr=self._notes,
            compose_callback=self._chat_session_controller.compose_in_reading,
            notify=self._notify_signal.emit,
            on_note_saved=self._note_created_signal.emit,
        )
        self._scheduler.set_tool_manager(self._registry)
        self._note_created_signal.connect(self._notes_panel.refresh)
        self._setup_tray()
        self._init_sessions()
        self._resize_filter = ResizeFilter(self)
        self._resize_filter.install()
        self._snap_mgr = EdgeSnapManager(self)
        self._snap_mgr.set_enabled(cfg.get(cfg.edgeSnap))
        self._notify_signal.connect(self._on_notify)
        self._confirm_request.connect(self._on_confirm_request)
        self._setup_hotkeys()
        self._restore_pinned_notes()

        # 实时字体大小：内容/编辑器字号变化时重新应用主题 QSS
        cfg.contentFontSize.valueChanged.connect(self._on_font_size_changed)
        cfg.editorFontSize.valueChanged.connect(self._on_font_size_changed)

        # 启动时应用主题（palette + QSS + DWM 标题栏）
        self._reapply_theme()

    # ──────────────────────────────────────────── window setup
    # ──────────────────────────────────────────── window setup
    def _init_tools(self):
        """初始化工具系统：自动发现内置工具 + 加载用户脚本工具。"""
        # workspace：用户配置 > 默认 ~/Documents
        ws_str = cfg.get(cfg.toolWorkspace)
        workspace = Path(ws_str) if ws_str else Path.home() / "Documents"

        # 记忆管理器（与 NoteManager 共用同一个 DatabaseManager）
        from app.core.memory_manager import MemoryManager
        self._memory_mgr = MemoryManager(self._notes.db)

        ctx = ToolContext(
            config=cfg,
            workspace=workspace,
            note_mgr=self._notes,
            scheduler=self._scheduler,
            llm_gateway=self._llm_gateway,
            events=ToolEvents(
                note_created=self._note_created_signal.emit,
            ),
            confirm_action=self._confirm_action,
            extra={"memory_mgr": self._memory_mgr},
        )
        load_builtin_tools(ctx, self._registry)
        load_user_script_tools(USER_TOOLS_DIR, self._registry)
        # 全新用户首次启动：把高风险/有成本工具播种为默认关闭（只播一次，
        # 之后尊重用户在能力面板的选择）。必须在 apply_saved_states 之前，
        # 让播种的默认值一并生效。
        states = cfg.get(cfg.toolStates)
        if not cfg.get(cfg.toolDefaultsSeeded):
            states = self._registry.seed_default_off(DEFAULT_OFF_TOOLS, states)
            cfg.set(cfg.toolStates, states)
            cfg.set(cfg.toolDefaultsSeeded, True)
        # 应用持久化的工具开关状态（启动即生效，不必等打开能力面板）
        self._registry.apply_saved_states(states)

    def _init_memory(self):
        """初始化记忆系统：Consolidator + Dream 定时器。"""
        from app.core.consolidator import Consolidator
        from app.core.dream import Dream

        self._consolidator = Consolidator(
            llm_gateway=self._llm_gateway,
            memory_mgr=self._memory_mgr,
        )
        self._dream = Dream(
            llm_gateway=self._llm_gateway,
            memory_mgr=self._memory_mgr,
        )

        # Dream 定时器：每小时执行一次
        self._dream_timer = QTimer(self)
        self._dream_timer.timeout.connect(self._run_dream)
        self._dream_timer.start(3600_000)

    def _run_dream(self):
        """在后台线程执行 Dream，避免阻塞 UI。"""
        import threading
        threading.Thread(target=self._dream.run, daemon=True).start()

    def _confirm_action(self, title: str, message: str) -> bool:
        """
        危险操作确认弹窗，供 exec 等工具在工作线程中调用。

        通过信号将弹窗请求发回主线程，用 threading.Event 阻塞等待结果。
        信号携带一个 list 作为结果容器，主线程槽函数写入结果后 set event。
        """
        if threading.current_thread() is threading.main_thread():
            return self._show_confirm_dialog(title, message)

        # 工作线程：通过信号发回主线程
        result_holder = []  # 用 list 作为可变容器传递结果
        event = threading.Event()
        result_holder.append(event)  # [event] → 槽函数会 append True/False 再 set

        self._confirm_request.emit(title, message, result_holder)
        event.wait(timeout=120)  # 最多等 2 分钟
        return result_holder[1] if len(result_holder) > 1 else False

    @pyqtSlot(str, str, object)
    def _on_confirm_request(self, title: str, message: str, result_holder: list):
        """主线程槽：弹出确认对话框，将结果写回 result_holder。"""
        answer = self._show_confirm_dialog(title, message)
        result_holder.append(answer)
        # result_holder[0] 是 event
        result_holder[0].set()

    def _show_confirm_dialog(self, title: str, message: str) -> bool:
        """在主线程中显示确认对话框。"""
        reply = QMessageBox.question(
            self, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _build_window(self):
        sg = QApplication.primaryScreen().availableGeometry()

        from app.core.config import CONFIG_DIR
        if not (CONFIG_DIR / "app_config.json").exists():
            # 初次启动：按屏幕比例设定初始尺寸（宽 1/2，高 2/3）
            w = sg.width() // 2
            h = sg.height() * 2 // 3
        else:
            w = cfg.get(cfg.windowWidth)
            h = cfg.get(cfg.windowHeight)

        self.resize(w, h)
        # 默认居中屏幕
        default_x = sg.x() + (sg.width() - w) // 2
        default_y = sg.y() + (sg.height() - h) // 2
        self.move(default_x, default_y)
        # Qt >= 6.10: qframelesswindow 使用 NoTitleBarBackgroundHint 仍会渲染系统关闭按钮，
        # 强制设置 FramelessWindowHint 来抑制它。
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # 禁用 qframelesswindow 原生调整大小（WM_NCHITTEST），
        # 由 ResizeFilter 通过 setGeometry 处理，避免幽灵边框。
        self.setResizeEnabled(False)
        # 任务栏模式下不设置 Tool 标志，让窗口出现在任务栏中
        if cfg.get(cfg.minimizeTo) == "tray":
            self.setWindowFlag(Qt.WindowType.Tool, True)
        else:
            # taskbar 模式：设置窗口图标，不置顶
            from app.ui.tray_manager import _ICON_PATH
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(_ICON_PATH))
            # 恢复任务栏最小化/还原的原生动画（genie 吸入/弹出效果）。
            # 详见 _restore_taskbar_animation 的说明。
            self._restore_taskbar_animation()

    def _restore_taskbar_animation(self):
        """恢复任务栏最小化/还原的 Windows 原生动画（genie 效果）。

        genie 动画依赖窗口保留 WS_CAPTION 样式。qframelesswindow 的
        addWindowAnimation() 本会把 WS_CAPTION 加回，但本类在其之后调用
        setWindowFlag(FramelessWindowHint, True) 抑制 Qt 6.10+ 的系统关闭按钮，
        这会让 Qt 把窗口重建为 WS_POPUP 并再次剥掉 WS_CAPTION，导致动画消失
        （实测：MIN/MAX 样式在，但 CAPTION=False、POPUP=True，无动画）。

        修复：重新加回 WS_CAPTION。可视边框由 qframelesswindow 的
        WM_NCCALCSIZE 处理器裁成 0，所以外观仍是无边框（实测加回后窗口尺寸
        不变）。只加 WS_CAPTION，不加 WS_THICKFRAME——后者会重新引入原生
        调整大小与幽灵边框（本项目已禁用原生 resize，改用 ResizeFilter）。
        """
        import sys
        if sys.platform != "win32":
            return
        try:
            import win32con
            import win32gui
        except ImportError:
            return
        hwnd = int(self.winId())
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        if style & win32con.WS_CAPTION:
            return
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style | win32con.WS_CAPTION)
        # SWP_FRAMECHANGED 让样式变更立即生效并重算非客户区。
        win32gui.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
            | win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED,
        )


    def _build_ui(self):
        # 隐藏左侧导航栏 — 导航已集成到标题栏中
        self.navigationInterface.hide()
        self.navigationInterface.setFixedWidth(0)
        # 重新连接 raise_ 到我们的标题栏（在 __init__ 中已断开）
        self.navigationInterface.displayModeChanged.connect(self._title_bar.raise_)
        # 调整内容区顶部边距以匹配自定义标题栏高度（默认为 48）
        self.widgetLayout.setContentsMargins(0, self._title_bar.height(), 0, 0)
        # 移除 FluentStyleSheet 添加的 stackedWidget 边框/背景
        self.stackedWidget.setStyleSheet("border: none; background: transparent;")
        # 把默认的"从下往上滑入"动画换成淡入淡出：滑入动画归位时会 relayout
        # 导致页面"一跳"，纯透明度渐变无位移则无跳动。须在 addSubInterface 前安装。
        from app.ui.fade_stacked_widget import install_fade_transition
        install_fade_transition(self)

        # ── page 0: chat view ─────────────────────────────────────────
        chat_page = QWidget()
        chat_page.setObjectName("chatInterface")
        page_layout = QVBoxLayout(chat_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self._chat_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._chat_splitter.setHandleWidth(6)
        # setChildrenCollapsible(False) + session_panel 的 minimumWidth 防止用户拖动
        # 分割条把会话面板误折叠到 0 宽；程序化折叠在 _toggle_session_panel 内临时放开。
        self._chat_splitter.setChildrenCollapsible(False)

        self._session_panel = SessionPanel()
        self._session_panel.session_selected.connect(self._on_session_select)
        self._session_panel.session_create_requested.connect(self._new_session)
        self._session_panel.session_delete_requested.connect(self._delete_session)
        self._session_panel.session_rename_requested.connect(self._rename_session)
        self._session_panel.session_settings_requested.connect(self._on_session_settings)
        self._session_panel.session_pin_requested.connect(self._on_session_pin)
        self._session_panel.session_reorder_requested.connect(self._on_session_reorder)
        self._session_panel.session_activate_reading_requested.connect(
            self._on_activate_reading
        )
        self._chat_splitter.addWidget(self._session_panel)

        self._chat_col = QVBoxLayout()
        self._chat_col.setContentsMargins(0, 0, 0, 0)
        self._chat_col.setSpacing(0)
        self._chat = ChatWidget()
        self._chat_col.addWidget(self._chat)
        self._tool_status = QLabel()
        self._tool_status.setObjectName("toolStatus")
        self._tool_status.hide()
        self._chat_col.addWidget(self._tool_status)
        self._input = InputWidget()
        self._input.submitted.connect(self._on_submit)
        self._input.edit_submitted.connect(self._on_edit_submit)
        self._input.edit_cancel_requested.connect(self._cancel_edit)
        self._input.cancel_requested.connect(self._cancel_worker)
        self._chat_col.addWidget(self._input)
        chat_col = self._chat_col

        self._chat.file_attached.connect(self._on_files_attached)
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")
        chat_area.setLayout(chat_col)
        self._chat_splitter.addWidget(chat_area)
        self._chat_splitter.setStretchFactor(0, 0)  # 会话面板：固定宽度
        self._chat_splitter.setStretchFactor(1, 1)  # 聊天区域：占据剩余空间

        self._chat_splitter.splitterMoved.connect(self._on_splitter_moved)

        page_layout.addWidget(self._chat_splitter)

        # ── page 1: notes panel ───────────────────────────────────────
        self._notes_panel = NotesPanel(self._notes)
        self._notes_panel.setObjectName("notesInterface")
        self._notes_panel.note_updated.connect(self._on_note_updated)

        # ── page 2: toolbox panel ─────────────────────────────────────
        self._toolbox_panel = ToolboxPanel(self._registry)
        self._toolbox_panel.setObjectName("toolboxInterface")

        # 注册页面到 FluentWindow（switchTo 需要）
        self.addSubInterface(chat_page, FluentIcon.CHAT, t("nav.chat"))
        self.addSubInterface(self._notes_panel, FluentIcon.EDIT, t("nav.notes"))
        self.addSubInterface(self._toolbox_panel, FluentIcon.DEVELOPER_TOOLS, t("nav.workshop"))

        # 保存页面引用供 _switch_view 使用
        self._pages = [chat_page, self._notes_panel, self._toolbox_panel]

        # 连接标题栏搜索框到各面板的过滤器
        self._title_bar.session_search_changed.connect(self._session_panel.apply_search)
        self._title_bar.notes_search_changed.connect(self._notes_panel.apply_search)
        self._title_bar.workshop_search_changed.connect(self._toolbox_panel.apply_search)

        self.setMinimumSize(320, 420)
        self.setMouseTracking(True)

    def _setup_tray(self):
        self._tray = TrayManager(self)
        self._tray.show_requested.connect(self._show_window)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.screenshot_requested.connect(self._start_screenshot)
        self._tray.quit_requested.connect(self._on_quit)
        self._scheduler.set_result_callback(self._on_scheduler_result)

    # ──────────────────────────────────────────── 快捷键
    def _setup_hotkeys(self):
        self._hotkey_mgr = HotkeyManager(self)
        self._hotkey_mgr.screenshot_triggered.connect(self._start_screenshot)
        self._hotkey_mgr.new_note_triggered.connect(self._new_note_via_hotkey)
        self._hotkey_mgr.toggle_window_triggered.connect(self._toggle_window_visibility)
        self._hotkey_mgr.quick_ask_triggered.connect(self._quick_ask)
        self._hotkey_mgr.selection_triggered.connect(
            self._selection_controller.trigger_at_cursor
        )
        self._hotkey_mgr.start()

        # 划词浮标：鼠标拖选后在光标附近弹出动作条（可在设置中开关）
        self._selection_monitor = SelectionMonitor(self)
        self._selection_monitor.selection_gesture.connect(
            self._selection_controller.trigger_at
        )
        self._selection_monitor.set_enabled(cfg.get(cfg.selectionFloatEnabled))

    def _new_note_via_hotkey(self):
        self._sticky_note_controller.create_from_hotkey()

    def _toggle_window_visibility(self):
        if self.isVisible() and not self.isMinimized():
            if self._snap_mgr is not None and self._snap_mgr.is_snapped:
                self._snap_mgr.unsnap_full()
            else:
                self.hide()
        else:
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()

    def _quick_ask(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self._input.focus()

    def _restore_pinned_notes(self):
        self._sticky_note_controller.restore_pinned()

    def _on_note_updated(self, note_id: int, title: str, content: str):
        """笔记内容更新时，通知所有相关浮窗和面板。"""
        self._sticky_note_controller.sync_note_update(note_id, title, content)
        # 如果笔记在其他地方被编辑，更新笔记面板
        self._notes_panel.refresh_note(note_id)
        # 广播到主信号
        self.note_updated.emit(note_id, title, content)

    # ──────────────────────────────────────────── 会话管理
    def _init_sessions(self):
        self._chat_session_controller.init_sessions()

    def _new_session(self, source: str = SOURCE_MANUAL):
        self._chat_session_controller.new_session(source)

    def _delete_session(self, sid: str):
        self._chat_session_controller.delete_session(sid)

    def _rename_session(self, sid: str, title: str):
        self._chat_session_controller.rename_session(sid, title)

    def _on_session_settings(self, sid: str):
        self._chat_session_controller.open_session_settings(sid)

    def _on_session_pin(self, sid: str, pinned: bool):
        self._chat_session_controller.pin_session(sid, pinned)

    def _on_session_reorder(self, ordered_ids: list):
        self._chat_session_controller.reorder_sessions(ordered_ids)

    def _on_activate_reading(self, sid: str):
        self._chat_session_controller.set_active_reading(sid)

    def _on_session_select(self, sid: str):
        self._chat_session_controller.select_session(sid)

    def _cancel_worker(self, sid: str | None = None):
        self._chat_session_controller.cancel_worker(sid)

    def _switch_session(self, sid: str):
        self._chat_session_controller.switch_session(sid)

    @pyqtSlot(list)
    def _on_files_attached(self, attachments: list):
        self._chat_session_controller.on_files_attached(attachments)

    # ──────────────────────────────────────────── 聊天
    @pyqtSlot(str)
    def _on_submit(self, text: str):
        self._chat_session_controller.submit(text)

    @pyqtSlot(str)
    def _on_edit_submit(self, text: str):
        self._chat_session_controller.submit_edit(text)

    def _cancel_edit(self):
        self._chat_session_controller.cancel_edit()

    # ──────────────────────────────────────────── 调度器回调
    def _on_scheduler_result(self, job_id: str, job_name: str, result: dict):
        data = result.get("data", {})
        if result.get("status") == "success":
            body = data.get("message") or t("scheduler.execSuccess")
        else:
            body = data.get("message") or t("scheduler.execFailed")
        self._notify_signal.emit(job_name, body)

    @pyqtSlot(str, str)
    def _on_notify(self, title: str, body: str):
        theme = THEMES.get(cfg.get(cfg.theme), THEMES[DEFAULT_THEME])
        show_toast(title, body, accent=theme["accent"])

    # ──────────────────────────────────────────── 对话框 / 窗口操作
    def _open_settings(self):
        old_theme = cfg.get(cfg.theme)
        dlg = SettingsWindow(
            hotkey_mgr=self._hotkey_mgr,
            registry=self._registry,
            session_mgr=self._sessions,
            on_sessions_changed=self._chat_session_controller.refresh_panel,
            note_mgr=self._notes,
            on_notes_changed=self._notes_panel.refresh,
            trace_store=self._trace_store,
            llm_gateway=self._llm_gateway,
            prompt_builder=self._prompt_builder,
            parent=self,
        )
        if dlg.exec():
            if self._snap_mgr is not None:
                self._snap_mgr.set_enabled(cfg.get(cfg.edgeSnap))
            if self._selection_monitor is not None:
                self._selection_monitor.set_enabled(
                    cfg.get(cfg.selectionFloatEnabled)
                )
            self._reapply_theme()
            if not self.isVisible():
                self.show()

    def _on_font_size_changed(self, _value=None):
        self._reapply_theme()

    def _reapply_theme(self):
        theme_name = cfg.get(cfg.theme)
        custom_qss = apply_theme(
            theme_name,
            content_font_size=cfg.get(cfg.contentFontSize),
            editor_font_size=cfg.get(cfg.editorFontSize),
        )
        self.setStyleSheet(custom_qss)
        # 笔记列表 delegate 缓存了主题色，需显式刷新，否则切换深浅后
        # 列表/便签文字色不变，必须点一下文件夹才更新。
        self._notes_panel.refresh_theme()
        # 发送按钮图标色按 accent 亮度重算（浅色强调色下白箭头看不清）。
        self._input.refresh_theme()

    def _switch_view(self, index: int):
        if 0 <= index < len(self._pages):
            self.switchTo(self._pages[index])
        self._title_bar.set_active_view(index)

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, '_splitter_restored', False):
            self._splitter_restored = True
            session_width = cfg.get(cfg.sessionPanelWidth)
            total = self._chat_splitter.width()
            if total > session_width:
                self._chat_splitter.setSizes([session_width, total - session_width])

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # FluentWindow 会偏移 titleBar 为导航面板展开按钮留空间，
        # 但由于侧栏已隐藏，需要保持标题栏全宽。
        if hasattr(self, '_title_bar'):
            self._title_bar.move(0, 0)
            self._title_bar.resize(self.width(), self._title_bar.height())

    @property
    def is_maximized(self) -> bool:
        """自定义最大化状态。不用 Qt 原生 isMaximized()——无边框 +
        setResizeEnabled(False) 下原生 showMaximized/showNormal 不可靠。"""
        return getattr(self, '_is_maximized', False)

    def _minimize(self):
        """最小化窗口：根据配置选择隐藏到托盘或任务栏。"""
        if cfg.get(cfg.minimizeTo) == "taskbar":
            self.showMinimized()
        else:
            self.hide()

    def _hide_to_tray(self):
        """始终隐藏到托盘（关闭按钮专用）"""
        self.hide()

    def _toggle_maximize(self):
        """切换窗口最大化/还原状态。

        全程用 setGeometry 手动实现，不用原生 showMaximized/showNormal——
        无边框窗口 + setResizeEnabled(False) 下原生窗口状态会被 WM 反复
        钳制回全屏（见 CLAUDE.md：尺寸一律走 setGeometry）。
        """
        if self.is_maximized:
            geo = getattr(self, '_pre_max_geo', None)
            self._is_maximized = False
            if geo is not None and geo.isValid():
                self.setGeometry(geo)
            self._title_bar.update_max_btn(False)
        else:
            # 最大化前先取消边缘吸附
            if self._snap_mgr is not None and self._snap_mgr.is_snapped:
                self._snap_mgr.unsnap_full()

            # 记下还原目标：用户手动调整过就存当前几何，否则存半屏，
            # 这样首次最大化后还原回到舒适的半屏尺寸。
            if getattr(self, '_user_has_resized', False):
                self._pre_max_geo = self.geometry()
            else:
                sg = QApplication.primaryScreen().availableGeometry()
                w = sg.width() // 2
                h = sg.height() * 2 // 3
                x = sg.x() + (sg.width() - w) // 2
                y = sg.y() + (sg.height() - h) // 2
                from PyQt6.QtCore import QRect
                self._pre_max_geo = QRect(x, y, w, h)

            sg = QApplication.primaryScreen().availableGeometry()
            self._is_maximized = True
            self.setGeometry(sg)
            self._title_bar.update_max_btn(True)

    # ──────────────────────────────────────────── 截图
    def _start_screenshot(self):
        self._screenshot_controller.start()

    def _show_window(self):
        if self._snap_mgr is not None and self._snap_mgr.is_snapped:
            self._snap_mgr.unsnap_full()
        else:
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()

    # ──────────────────────────────────────────── 窗口事件
    def nativeEvent(self, eventType, message):
        # 抑制标题栏右键的系统上下文菜单。
        # FluentWindow 对标题栏区域返回 HTCAPTION，导致 Windows 弹出系统菜单与自定义菜单重叠。
        if eventType == b"windows_generic_MSG":
            import ctypes.wintypes
            msg = ctypes.wintypes.MSG.from_address(int(message))
            WM_NCRBUTTONUP = 0x00A5
            if msg.message == WM_NCRBUTTONUP:
                return True, 0
        return super().nativeEvent(eventType, message)

    def moveEvent(self, event):
        super().moveEvent(event)
        if getattr(self, '_snap_mgr', None) is not None:
            self._snap_mgr.check_position()

    def enterEvent(self, event):
        super().enterEvent(event)
        if getattr(self, '_snap_mgr', None) is not None:
            self._snap_mgr.on_enter()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if getattr(self, '_snap_mgr', None) is not None:
            self._snap_mgr.on_leave()

    def _on_splitter_moved(self, pos, index):
        sizes = self._chat_splitter.sizes()
        if sizes[0] > 0:
            cfg.set(cfg.sessionPanelWidth, max(sizes[0], 120))
            cfg.save()

    def _toggle_session_panel(self):
        sizes = self._chat_splitter.sizes()
        total = sum(sizes)
        session_width = sizes[0]

        if session_width > 0:
            self._saved_session_width = session_width
            # setChildrenCollapsible(False) + minimumWidth 会把 setSizes([0,…]) 夹回
            # 最小宽，程序化折叠时临时放开约束，展开后恢复。
            self._session_panel.setMinimumWidth(0)
            self._chat_splitter.setChildrenCollapsible(True)
            self._chat_splitter.setSizes([0, total])
        else:
            self._session_panel.setMinimumWidth(120)
            self._chat_splitter.setChildrenCollapsible(False)
            width = getattr(self, '_saved_session_width', None) or cfg.get(cfg.sessionPanelWidth)
            self._chat_splitter.setSizes([width, total - width])

    def _persist_layout(self):
        """保存窗口尺寸与分栏宽度。

        窗口最大化或边缘吸附时 self.width()/height() 是全屏尺寸，不能持久化，
        否则下次启动会以全屏高度还原。这两种状态下保存还原后的"正常"尺寸。
        """
        sizes = self._chat_splitter.sizes()
        session_width = sizes[0] if sizes[0] > 0 else getattr(self, '_saved_session_width', 180)

        normal_geo = self._normal_geometry()
        cfg.set(cfg.windowWidth, normal_geo.width())
        cfg.set(cfg.windowHeight, normal_geo.height())
        cfg.set(cfg.sessionPanelWidth, max(session_width, 120))

    def _normal_geometry(self):
        """当前的"正常"几何：剔除最大化 / 边缘吸附带来的非常规尺寸。"""
        if self.is_maximized:
            # 最大化时还原目标存在 _pre_max_geo
            geo = getattr(self, '_pre_max_geo', None)
            if geo is not None and geo.isValid():
                return geo
        if self._snap_mgr is not None and self._snap_mgr.unsnapped_geo is not None:
            return self._snap_mgr.unsnapped_geo
        return self.geometry()

    # ──────────────────────────────────────────── 拦截关闭 → 隐藏到托盘
    def closeEvent(self, event):
        self._persist_layout()
        cfg.save()
        event.ignore()
        self.hide()

    def cleanup(self):
        """停止所有后台 worker，在应用退出前调用。"""
        self._hotkey_mgr.stop()
        if hasattr(self, "_selection_monitor"):
            self._selection_monitor.stop()
        self._chat_session_controller.cleanup()

    def _on_quit(self):
        # 仅当窗口可见时保存布局（否则 closeEvent 已保存）
        if self.isVisible():
            self._persist_layout()
        cfg.save()
        self.cleanup()
        QApplication.instance().quit()
