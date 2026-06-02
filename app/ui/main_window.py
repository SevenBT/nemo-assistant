"""
Main floating window.

Layout:
  ┌─ TitleBar ───────────────────────────────────────────────────┐
  │ [≡] AI Agent ── [聊天] [笔记] [工坊] ── [截图] [─] [□] [✕]  │
  ├──────────────────────────────────────────────────────────────┤
  │ FluentWindow stackedWidget                                   │
  │  page 0: SessionPanel | ChatWidget + InputWidget             │
  │  page 1: NotesPanel                                          │
  │  page 2: ToolboxPanel                                        │
  └──────────────────────────────────────────────────────────────┘
"""
import json
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

from app.core.ai_client import AIClient
from app.core.config import cfg, USER_TOOLS_DIR
from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager
from app.core.session_manager import SessionManager
from app.tools.context import ToolContext, ToolEvents
from app.tools.loader import load_builtin_tools, load_user_script_tools
from app.tools.registry import ToolRegistry
from app.models.message import Message, MessageRole, ToolCall
from app.ui.chat_widget import ChatWidget, MessageBubble
from app.core.agent_loop import AgentLoop
from app.ui.edge_snap import EdgeSnapManager
from app.ui.input_widget import InputWidget
from app.ui.manual_params_dialog import ManualParamsDialog
from app.ui.notes_dialog import NotesPanel
from app.core.hotkey_manager import HotkeyManager
from app.ui.resize_filter import ResizeFilter
from app.ui.screenshot_controller import ScreenshotController
from app.ui.toolbox_panel import ToolboxPanel
from app.ui.session_panel import SessionPanel
from app.ui.settings_window import SettingsWindow
from app.ui.sticky_note_controller import StickyNoteController
from app.ui.style import THEMES, apply_theme
from app.ui.title_bar import TitleBar
from app.ui.toast import show_toast
from app.ui.tray_manager import TrayManager
from app.core.constants import DEFAULT_USER_PROMPT, BUILTIN_TOOLS_INSTRUCTION, get_current_datetime_info
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
        self._ai = AIClient()
        self._current_session_id: str | None = None
        self._workers: dict[str, AgentLoop] = {}
        self._session_live: dict[str, dict] = {}  # sid -> {ai_msg, ai_text}
        self._current_ai_bubble: MessageBubble | None = None
        self._current_ai_msg: Message | None = None
        self._current_ai_text = ""
        self._pending_attachments: list = []  # 暂存拖放的附件
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
            ai_client=self._ai,
            events=ToolEvents(
                note_created=self._note_created_signal.emit,
            ),
            confirm_action=self._confirm_action,
            extra={"memory_mgr": self._memory_mgr},
        )
        load_builtin_tools(ctx, self._registry)
        load_user_script_tools(USER_TOOLS_DIR, self._registry)

    def _init_memory(self):
        """初始化记忆系统：Consolidator + Dream 定时器。"""
        from app.core.consolidator import Consolidator
        from app.core.dream import Dream

        self._consolidator = Consolidator(
            ai_client=self._ai,
            memory_mgr=self._memory_mgr,
        )
        self._dream = Dream(
            ai_client=self._ai,
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
        w = cfg.get(cfg.windowWidth)
        h = cfg.get(cfg.windowHeight)
        self.resize(w, h)
        # 默认居中屏幕
        sg = QApplication.primaryScreen().availableGeometry()
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

        # ── page 0: chat view ─────────────────────────────────────────
        chat_page = QWidget()
        chat_page.setObjectName("chatInterface")
        page_layout = QVBoxLayout(chat_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        self._chat_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._chat_splitter.setHandleWidth(6)
        self._chat_splitter.setChildrenCollapsible(True)

        self._session_panel = SessionPanel()
        self._session_panel.session_selected.connect(self._on_session_select)
        self._session_panel.session_create_requested.connect(self._new_session)
        self._session_panel.session_delete_requested.connect(self._delete_session)
        self._session_panel.session_rename_requested.connect(self._rename_session)
        self._session_panel.session_settings_requested.connect(self._on_session_settings)
        self._session_panel.session_pin_requested.connect(self._on_session_pin)
        self._session_panel.session_reorder_requested.connect(self._on_session_reorder)
        self._chat_splitter.addWidget(self._session_panel)

        chat_col = QVBoxLayout()
        chat_col.setContentsMargins(0, 0, 0, 0)
        chat_col.setSpacing(0)
        self._chat = ChatWidget()
        chat_col.addWidget(self._chat)
        self._tool_status = QLabel()
        self._tool_status.setObjectName("toolStatus")
        self._tool_status.hide()
        chat_col.addWidget(self._tool_status)
        self._input = InputWidget()
        self._input.submitted.connect(self._on_submit)
        chat_col.addWidget(self._input)

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
        self.addSubInterface(chat_page, FluentIcon.CHAT, "聊天")
        self.addSubInterface(self._notes_panel, FluentIcon.EDIT, "笔记")
        self.addSubInterface(self._toolbox_panel, FluentIcon.DEVELOPER_TOOLS, "工坊")

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
        self._hotkey_mgr.start()

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
        sessions = self._sessions.get_sessions()
        if not sessions:
            s = self._sessions.create()
            sessions = [s]
        self._session_panel.load(sessions, sessions[0].id)
        self._switch_session(sessions[0].id)

    def _new_session(self):
        """新建会话，直接创建默认无角色会话"""
        s = self._sessions.create()
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, s.id)
        self._switch_session(s.id)

    def _delete_session(self, sid: str):
        self._sessions.delete(sid)
        sessions = self._sessions.get_sessions()
        if not sessions:
            s = self._sessions.create()
            sessions = [s]
        self._session_panel.load(sessions, sessions[0].id)
        self._switch_session(sessions[0].id)

    def _rename_session(self, sid: str, title: str):
        self._sessions.rename(sid, title)
        self._session_panel.update_title(sid, title)

    def _on_session_settings(self, sid: str):
        """打开会话设置对话框"""
        from app.ui.session_settings_dialog import SessionSettingsDialog

        session = self._sessions.get(sid)
        if not session:
            return

        dialog = SessionSettingsDialog(session, self)
        if dialog.exec():
            # 保存会话设置
            self._sessions.update_system_prompt(sid, session.system_prompt)
            # 刷新会话列表
            sessions = self._sessions.get_sessions()
            self._session_panel.load(sessions, sid)

    def _on_session_pin(self, sid: str, pinned: bool):
        """置顶/取消置顶会话。"""
        self._sessions.pin_session(sid, pinned)
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, sid)

    def _on_session_reorder(self, ordered_ids: list):
        """拖拽排序后更新置顶会话顺序。"""
        self._sessions.reorder_sessions(ordered_ids)

    def _on_session_select(self, sid: str):
        if sid != self._current_session_id:
            self._switch_session(sid)

    def _cancel_worker(self, sid: str | None = None):
        """停止并丢弃指定会话的 worker（默认为当前会话）。"""
        if sid is None:
            sid = self._current_session_id
        if not sid:
            return
        worker = self._workers.pop(sid, None)
        self._session_live.pop(sid, None)
        if worker is None:
            return
        worker.cancel()
        try:
            worker.disconnect()
        except RuntimeError:
            pass

    def _switch_session(self, sid: str):
        # 不停止正在运行的 worker — 让它在后台继续执行。
        self._current_ai_bubble = None
        self._current_ai_msg = None
        self._current_ai_text = ""
        self._current_session_id = sid
        self._tool_status.hide()
        self._chat.stop_typing()

        session = self._sessions.get(sid)
        if session:
            self._chat.load_session(session.messages)

        live = self._session_live.get(sid)
        if live:
            self._current_ai_msg = live["ai_msg"]
            self._current_ai_text = live["ai_text"]
            last = self._chat.last_bubble()
            if last and not last.is_user:
                self._current_ai_bubble = last
            else:
                self._current_ai_bubble = None
            self._input.set_enabled(False)
            if not live.get("first_chunk_sent"):
                self._chat.start_typing()
        else:
            self._input.set_enabled(True)

        self._input.focus()

    @pyqtSlot(list)
    def _on_files_attached(self, attachments: list):
        """处理拖放到聊天区域的文件。"""
        self._pending_attachments.extend(attachments)
        # TODO: 在输入区域显示附件可视化反馈

    # ──────────────────────────────────────────── 聊天
    @pyqtSlot(str)
    def _on_submit(self, text: str):
        sid = self._current_session_id
        if not sid:
            return
        if sid in self._workers:
            return  # 该会话已有任务运行中

        # 创建带附件的用户消息
        user_msg = Message(
            role=MessageRole.USER,
            content=text,
            attachments=self._pending_attachments.copy()
        )
        self._pending_attachments.clear()  # 使用后清空

        self._sessions.add_message(sid, user_msg)
        self._chat.add_message(user_msg)
        self._session_panel.update_title(sid, self._sessions.get(sid).title)

        ai_msg = Message(role=MessageRole.ASSISTANT, content="")
        self._sessions.add_message(sid, ai_msg)
        self._current_ai_msg = ai_msg
        self._current_ai_bubble = None
        self._current_ai_text = ""
        self._input.set_enabled(False)
        self._tool_status.hide()
        self._chat.start_typing()

        self._session_live[sid] = {"ai_msg": ai_msg, "ai_text": "", "first_chunk_sent": False}

        session = self._sessions.get(sid)

        # Consolidator: 压缩超长对话
        if hasattr(self, "_consolidator"):
            # messages[:-1] 排除刚加的占位 AI 消息
            original_msgs = session.messages[:-1]
            compressed = self._consolidator.maybe_consolidate(original_msgs, sid)
            if len(compressed) < len(original_msgs):
                # 消息被压缩了，更新 session
                session.messages = compressed + [session.messages[-1]]
                self._sessions.save_session(sid)

        api_msgs = self._build_api_messages(session.messages[:-1])  # exclude placeholder

        worker = AgentLoop(
            ai_client=self._ai,
            registry=self._registry,
            api_messages=api_msgs,
            session_id=sid,
        )
        self._workers[sid] = worker
        self._connect_worker(sid, worker)
        worker.start()

    def _build_api_messages(self, messages: list[Message]) -> list[dict]:
        """
        构建 API 消息列表，System Prompt 优先级：
        1. 会话级 system_prompt（最高优先级）
        2. 全局配置 config.system_prompt
        3. 默认值 DEFAULT_USER_PROMPT
        4. 追加 BUILTIN_TOOLS_INSTRUCTION
        5. 追加长期记忆
        6. 追加当前时间信息（动态内容放末尾，提升 prompt cache 命中）
        """
        session = self._sessions.get(self._current_session_id)
        user_prompt = ""

        # 优先级 1: 会话级 system_prompt（非空且非纯空白）
        if session and session.system_prompt and session.system_prompt.strip():
            user_prompt = session.system_prompt.strip()
        # 优先级 2: 全局配置 config.system_prompt
        if not user_prompt:
            user_prompt = cfg.get(cfg.systemPrompt).strip()
        # 优先级 3: 默认值
        if not user_prompt:
            user_prompt = DEFAULT_USER_PROMPT

        # 稳定内容放在前面，动态时间信息放在最后，提升 prompt cache 命中率。
        full_system_prompt = user_prompt + "\n" + BUILTIN_TOOLS_INSTRUCTION

        # 注入长期记忆
        if self._current_session_id and hasattr(self, "_memory_mgr"):
            memory_context = self._memory_mgr.build_memory_context(
                self._current_session_id
            )
            if memory_context:
                full_system_prompt += "\n\n" + memory_context

        full_system_prompt += "\n\n" + get_current_datetime_info()

        result = [{"role": "system", "content": full_system_prompt}]

        # 使用 AIClient.merge_attachments_to_content 处理附件
        merged_messages = self._ai.merge_attachments_to_content(messages)

        for i, m in enumerate(messages):
            result.append(merged_messages[i])
            # 每条带 tool_calls 的 assistant 消息后必须紧跟对应的 tool result，
            # 否则 API 会返回 400 错误。
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                all_done = all(tc.result is not None for tc in m.tool_calls)
                if all_done:
                    for tc in m.tool_calls:
                        result.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(tc.result, ensure_ascii=False),
                        })
                else:
                    result.pop()
        return result

    # ── Worker 信号连接 ───────────────────────────────────────────────────
    def _connect_worker(self, sid: str, worker: AgentLoop):
        worker.text_chunk.connect(lambda d, s=sid: self._on_bg_text_chunk(s, d))
        worker.tool_event.connect(lambda cid, phase, payload, s=sid: self._on_bg_tool_event(s, cid, phase, payload))
        worker.need_input.connect(lambda cid, tn, ps, s=sid: self._on_bg_need_input(s, cid, tn, ps))
        worker.new_turn.connect(lambda tc, s=sid: self._on_bg_new_turn(s, tc))
        worker.done.connect(lambda info, s=sid: self._on_bg_done(s, info))

    # ── 会话感知的信号处理 ───────────────────────────────────────────────
    def _on_bg_text_chunk(self, sid: str, delta: str):
        live = self._session_live.get(sid)
        if live is None:
            return
        live["ai_text"] += delta
        if live["ai_msg"]:
            live["ai_msg"].content = live["ai_text"]
        if sid != self._current_session_id:
            return
        if not live.get("first_chunk_sent"):
            self._chat.stop_typing()
            live["first_chunk_sent"] = True
        self._current_ai_text = live["ai_text"]
        if self._current_ai_bubble is None and self._current_ai_msg:
            self._current_ai_bubble = self._chat.add_message(self._current_ai_msg)
        try:
            if self._current_ai_bubble:
                self._current_ai_bubble.set_content(self._current_ai_text)
        except RuntimeError:
            self._current_ai_bubble = None
        self._chat.scroll_bottom()

    def _on_bg_tool_event(self, sid: str, call_id: str, phase: str, payload: dict):
        """统一处理工具事件（start / done / error）。"""
        session = self._sessions.get(sid)
        if phase == "start":
            tool_name = payload["name"]
            params = payload["params"]
            if session and session.messages:
                tc = ToolCall(id=call_id, name=tool_name, arguments=params, status="running")
                session.messages[-1].tool_calls.append(tc)
            if sid != self._current_session_id:
                return
            self._chat.stop_typing()
            if self._current_ai_bubble is None and self._current_ai_msg:
                self._current_ai_bubble = self._chat.add_message(self._current_ai_msg)
            if self._current_ai_bubble:
                self._current_ai_bubble.clear_text()
                self._current_ai_bubble.add_tool_card(call_id, tool_name, params)
            self._chat.scroll_bottom()
        elif phase == "done":
            result = payload["result"]
            if session:
                for msg in reversed(session.messages):
                    for tc in msg.tool_calls:
                        if tc.id == call_id:
                            tc.result = result
                            tc.status = result.get("status", "success")
                            break
            if sid != self._current_session_id:
                return
            if self._current_ai_bubble:
                self._current_ai_bubble.update_tool_card(call_id, result)

    def _on_bg_need_input(self, sid: str, call_id: str, tool_name: str, param_names: list):
        worker = self._workers.get(sid)
        if worker is None:
            return
        if sid == self._current_session_id:
            dlg = ManualParamsDialog(tool_name, param_names, self)
            params = dlg.get_values() if dlg.exec() else {}
        else:
            params = {}
        worker.supply_input(params)

    def _on_bg_new_turn(self, sid: str, turn_count: int):
        ai_msg = Message(role=MessageRole.ASSISTANT, content="")
        self._sessions.add_message(sid, ai_msg)
        live = self._session_live.get(sid)
        if live:
            live["ai_msg"] = ai_msg
            live["ai_text"] = ""
            live["first_chunk_sent"] = False
        if sid != self._current_session_id:
            return
        self._current_ai_msg = ai_msg
        self._current_ai_text = ""
        if self._current_ai_bubble:
            self._current_ai_bubble.clear_text()
        self._chat.start_typing()

    def _on_bg_done(self, sid: str, info: dict):
        """统一处理完成和错误。"""
        live = self._session_live.get(sid)
        ok = info.get("ok", True)
        error_msg = info.get("error")

        if ok:
            # 正常完成
            if live and live["ai_msg"] and not live["ai_msg"].content:
                live["ai_msg"].content = live["ai_text"]
                if live["ai_text"] and sid == self._current_session_id and self._current_ai_bubble is None:
                    self._current_ai_bubble = self._chat.add_message(live["ai_msg"])
            session = self._sessions.get(sid)
            if session:
                session.messages = [
                    m for m in session.messages
                    if not (m.role == "assistant" and not m.content and not m.tool_calls)
                ]
        else:
            # 错误
            hint = ""
            if error_msg and "404" in error_msg:
                hint = f"\n\n提示：请在设置中检查 API 地址（当前: {cfg.get(cfg.apiBaseUrl)}）和模型名称（当前: {cfg.get(cfg.model)}）"
            elif error_msg and ("401" in error_msg or "Unauthorized" in error_msg):
                hint = "\n\n提示：API Key 无效，请在设置中重新填写"
            error_text = f"❌ 请求失败：{error_msg}{hint}"
            if live and live["ai_msg"]:
                live["ai_msg"].content = error_text
            if sid == self._current_session_id:
                if self._current_ai_bubble is None and self._current_ai_msg:
                    self._current_ai_bubble = self._chat.add_message(self._current_ai_msg)
                if self._current_ai_bubble:
                    try:
                        self._current_ai_bubble.set_content(error_text)
                    except RuntimeError:
                        pass

        self._sessions.save_session(sid)
        self._workers.pop(sid, None)
        self._session_live.pop(sid, None)
        if sid != self._current_session_id:
            return
        self._chat.stop_typing()
        self._tool_status.hide()
        self._input.set_enabled(True)
        self._input.focus()
        self._current_ai_msg = None
        self._current_ai_bubble = None

    # ──────────────────────────────────────────── 调度器回调
    def _on_scheduler_result(self, job_id: str, job_name: str, result: dict):
        data = result.get("data", {})
        if result.get("status") == "success":
            body = data.get("message") or "执行成功"
        else:
            body = data.get("message") or "执行失败"
        self._notify_signal.emit(job_name, body)

    @pyqtSlot(str, str)
    def _on_notify(self, title: str, body: str):
        theme = THEMES.get(cfg.get(cfg.theme), THEMES["morning"])
        show_toast(title, body, accent=theme["accent"])

    # ──────────────────────────────────────────── 对话框 / 窗口操作
    def _open_settings(self):
        old_theme = cfg.get(cfg.theme)
        dlg = SettingsWindow(
            hotkey_mgr=self._hotkey_mgr,
            registry=self._registry,
            parent=self,
        )
        if dlg.exec():
            if self._snap_mgr is not None:
                self._snap_mgr.set_enabled(cfg.get(cfg.edgeSnap))
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
        """切换窗口最大化/还原状态"""
        if self.isMaximized():
            # 当前是最大化，还原到之前的大小
            self.showNormal()
        else:
            # 最大化前先取消边缘吸附
            if self._snap_mgr is not None and self._snap_mgr.is_snapped:
                self._snap_mgr.unsnap_full()
            # 当前是正常窗口，最大化
            self.showMaximized()

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
            self._chat_splitter.setSizes([0, total])
        else:
            width = getattr(self, '_saved_session_width', None) or cfg.get(cfg.sessionPanelWidth)
            self._chat_splitter.setSizes([width, total - width])

    # ──────────────────────────────────────────── 拦截关闭 → 隐藏到托盘
    def closeEvent(self, event):
        sizes = self._chat_splitter.sizes()
        session_width = sizes[0] if sizes[0] > 0 else getattr(self, '_saved_session_width', 180)
        cfg.set(cfg.windowWidth, self.width())
        cfg.set(cfg.windowHeight, self.height())
        cfg.set(cfg.sessionPanelWidth, max(session_width, 120))
        cfg.save()
        event.ignore()
        self.hide()

    def cleanup(self):
        """停止所有后台 worker，在应用退出前调用。"""
        self._hotkey_mgr.stop()
        for sid in list(self._workers):
            self._cancel_worker(sid)

    def _on_quit(self):
        # 仅当窗口可见时保存布局（否则 closeEvent 已保存）
        if self.isVisible():
            sizes = self._chat_splitter.sizes()
            session_width = sizes[0] if sizes[0] > 0 else getattr(self, '_saved_session_width', 180)
            cfg.set(cfg.windowWidth, self.width())
            cfg.set(cfg.windowHeight, self.height())
            cfg.set(cfg.sessionPanelWidth, max(session_width, 120))
        cfg.save()
        self.cleanup()
        QApplication.instance().quit()
