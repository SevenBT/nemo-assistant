"""
Main floating window.

Layout:
  ┌─ TitleBar ───────────────────────────────────────────────────┐
  │ [≡] AI Agent ── [聊天] [笔记] [工坊] ── [截图] [─] [□] [✕]  │
  ├──────────────────────────────────────────────────────────────┤
  │ FluentWindow stackedWidget                                   │
  │  page 0: SessionPanel | ChatWidget + InputWidget             │
  │  page 1: NotesPanel                                          │
  │  page 2: ToolboxPanel                                         │
  └──────────────────────────────────────────────────────────────┘
"""
import json

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.ai_client import AIClient
from app.core.builtin_tools import BUILTIN_TOOLS, BuiltinToolHandler
from app.core.config import cfg, get_api_key
from app.core.note_manager import NoteManager
from app.core.scheduler import SchedulerManager
from app.core.session_manager import SessionManager
from app.core.tool_manager import ToolManager
from app.models.message import Message, MessageRole, ToolCall
from app.ui.chat_widget import ChatWidget, MessageBubble
from app.ui.chat_worker import ChatWorker
from app.ui.edge_snap import EdgeSnapManager
from app.ui.input_widget import InputWidget
from app.ui.manual_params_dialog import ManualParamsDialog
from app.ui.notes_dialog import NotesPanel
from app.ui.pin_window import PinWindow
from app.core.hotkey_manager import HotkeyManager
from app.ui.resize_filter import ResizeFilter
from app.ui.toolbox_panel import ToolboxPanel
from app.ui.screenshot_overlay import ScreenshotOverlay
from app.ui.session_panel import SessionPanel
from app.ui.settings_window import SettingsWindow
from app.ui.style import THEMES, apply_theme, set_dark_titlebar
from app.ui.title_bar import TitleBar
from app.ui.toast import show_toast
from app.ui.tray_manager import TrayManager
from app.core.constants import DEFAULT_USER_PROMPT, BUILTIN_TOOLS_INSTRUCTION, get_current_datetime_info
from qfluentwidgets import FluentWindow, FluentIcon


# ─────────────────────────────────────────────────────────────────────
class MainWindow(FluentWindow):
    # Used to marshal scheduler callbacks from background threads to the main thread
    _notify_signal = pyqtSignal(str, str)  # title, body
    # Signal for note content updates (note_id, title, content)
    note_updated = pyqtSignal(int, str, str)
    # Marshals note-created callback from worker thread to main thread
    _note_created_signal = pyqtSignal()

    def __init__(
        self,
        session_mgr: SessionManager,
        tool_mgr: ToolManager,
        scheduler: SchedulerManager,
        note_mgr: NoteManager,
    ):
        super().__init__()
        # Replace FluentWindow's default FluentTitleBar immediately.
        # Disconnect the signal that would re-raise the old titleBar, then
        # forcibly hide any lingering children before our titleBar takes over.
        old_title_bar = self.titleBar
        self.navigationInterface.displayModeChanged.disconnect()
        self._title_bar = TitleBar(self)
        self.setTitleBar(self._title_bar)
        # setTitleBar calls deleteLater (async) — force-hide now so it never shows
        old_title_bar.hide()
        for child in old_title_bar.findChildren(QWidget):
            child.hide()
        # Kill any lingering TitleBarButton from qframelesswindow (e.g. red CloseButton)
        from qframelesswindow import TitleBarButton
        for btn in self.findChildren(TitleBarButton):
            btn.setFixedSize(0, 0)
            btn.hide()
            btn.deleteLater()

        self._sessions = session_mgr
        self._tools = tool_mgr
        self._scheduler = scheduler
        self._notes = note_mgr
        self._ai = AIClient()
        self._current_session_id: str | None = None
        self._workers: dict[str, ChatWorker] = {}
        self._session_live: dict[str, dict] = {}  # sid -> {ai_msg, ai_text}
        self._current_ai_bubble: MessageBubble | None = None
        self._current_ai_msg: Message | None = None
        self._current_ai_text = ""
        self._pending_attachments: list = []  # Temporary storage for dropped files
        self._snap_mgr: EdgeSnapManager | None = None
        self._sticky_windows: list = []

        # 初始化 PresetManager
        from app.core.preset_manager import PresetManager
        self._preset_mgr = PresetManager()

        self._build_window()
        self._build_ui()
        self._builtin_handler = BuiltinToolHandler(
            scheduler=scheduler,
            note_mgr=note_mgr,
            on_note_created=self._note_created_signal.emit,
        )
        self._note_created_signal.connect(self._notes_panel.refresh)
        self._setup_tray()
        self._init_sessions()
        self._resize_filter = ResizeFilter(self)
        self._resize_filter.install()
        self._snap_mgr = EdgeSnapManager(self)
        self._snap_mgr.set_enabled(cfg.get(cfg.edgeSnap))
        self._notify_signal.connect(self._on_notify)
        self._setup_hotkeys()
        self._restore_pinned_notes()

        # Live font size: re-apply theme QSS when content/editor fontSize changes
        cfg.contentFontSize.valueChanged.connect(self._on_font_size_changed)
        cfg.editorFontSize.valueChanged.connect(self._on_font_size_changed)

    # ──────────────────────────────────────────── window setup
    # ──────────────────────────────────────────── window setup
    def _build_window(self):
        w = cfg.get(cfg.windowWidth)
        h = cfg.get(cfg.windowHeight)
        self.resize(w, h)
        # 默认居中屏幕
        sg = QApplication.primaryScreen().availableGeometry()
        default_x = sg.x() + (sg.width() - w) // 2
        default_y = sg.y() + (sg.height() - h) // 2
        self.move(default_x, default_y)
        # Qt >= 6.10: qframelesswindow uses NoTitleBarBackgroundHint which still
        # renders system close button.  Force FramelessWindowHint to suppress it.
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        # Disable qframelesswindow's native resize (WM_NCHITTEST) — our ResizeFilter
        # handles resize via setGeometry to avoid ghost border artifacts.
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
        # Hide the left sidebar — navigation lives in the title bar
        self.navigationInterface.hide()
        self.navigationInterface.setFixedWidth(0)
        # Reconnect raise_ to our titleBar (was disconnected during __init__)
        self.navigationInterface.displayModeChanged.connect(self._title_bar.raise_)
        # Adjust content top margin to match our taller title bar (default is 48)
        self.widgetLayout.setContentsMargins(0, self._title_bar.height(), 0, 0)
        # Remove any border/background from stacked widget that FluentStyleSheet adds
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
        self._chat_splitter.setStretchFactor(0, 0)  # session panel: fixed width
        self._chat_splitter.setStretchFactor(1, 1)  # chat area: take all extra space

        self._chat_splitter.splitterMoved.connect(self._on_splitter_moved)

        page_layout.addWidget(self._chat_splitter)

        # ── page 1: notes panel ───────────────────────────────────────
        self._notes_panel = NotesPanel(self._notes)
        self._notes_panel.setObjectName("notesInterface")
        self._notes_panel.note_updated.connect(self._on_note_updated)

        # ── page 2: toolbox panel ─────────────────────────────────────
        self._toolbox_panel = ToolboxPanel(self._tools)
        self._toolbox_panel.setObjectName("toolboxInterface")

        # Register pages with FluentWindow (required for switchTo to work)
        self.addSubInterface(chat_page, FluentIcon.CHAT, "聊天")
        self.addSubInterface(self._notes_panel, FluentIcon.EDIT, "笔记")
        self.addSubInterface(self._toolbox_panel, FluentIcon.DEVELOPER_TOOLS, "工坊")

        # Keep page references for _switch_view
        self._pages = [chat_page, self._notes_panel, self._toolbox_panel]

        # Wire title bar search → panel filters
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

    # ──────────────────────────────────────────── hotkeys
    def _setup_hotkeys(self):
        self._hotkey_mgr = HotkeyManager(self)
        self._hotkey_mgr.screenshot_triggered.connect(self._start_screenshot)
        self._hotkey_mgr.new_note_triggered.connect(self._new_note_via_hotkey)
        self._hotkey_mgr.toggle_window_triggered.connect(self._toggle_window_visibility)
        self._hotkey_mgr.quick_ask_triggered.connect(self._quick_ask)
        self._hotkey_mgr.start()

    def _new_note_via_hotkey(self):
        from app.ui.sticky_note_window import StickyNoteWindow
        note = self._notes.create()
        # Get screen center position
        sg = QApplication.primaryScreen().availableGeometry()
        x = (sg.width() - 240) // 2 + sg.x()
        y = (sg.height() - 200) // 2 + sg.y()
        # Pin note to desktop at center position
        self._notes.pin_note(note.id, x, y)
        win = StickyNoteWindow(
            note_id=note.id,
            title=note.title,
            content=note.content,
            note_mgr=self._notes,
        )
        win.move(x, y)
        win.show()
        self._sticky_windows.append(win)
        win.closed.connect(
            lambda w=win: self._on_sticky_closed(w)
        )
        # Connect content change signal
        win.content_changed.connect(self._on_note_updated)
        win.delete_requested.connect(lambda _: self._notes_panel.refresh())

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
        """启动时恢复所有固定笔记浮窗。"""
        from app.ui.sticky_note_window import StickyNoteWindow
        pinned = self._notes.get_pinned_notes()
        for note in pinned:
            try:
                win = StickyNoteWindow(
                    note_id=note.id,
                    title=note.title,
                    content=note.content,
                    note_mgr=self._notes,
                )
                # Restore position with boundary check
                x = note.pin_position_x or 100
                y = note.pin_position_y or 100
                sg = QApplication.primaryScreen().availableGeometry()
                x = max(sg.x(), min(x, sg.x() + sg.width() - 180))
                y = max(sg.y(), min(y, sg.y() + sg.height() - 120))
                win.move(x, y)
                win.show()
                self._sticky_windows.append(win)
                win.closed.connect(lambda w=win: self._on_sticky_closed(w))
                # Connect content change signal
                win.content_changed.connect(self._on_note_updated)
                win.delete_requested.connect(lambda _: self._notes_panel.refresh())
            except Exception as e:
                print(f"Failed to restore pinned note {note.id}: {e}")

    def _on_sticky_closed(self, win):
        """浮窗关闭时取消固定并从列表移除。"""
        if win in self._sticky_windows:
            self._sticky_windows.remove(win)
        # Unpin note if it has note_id
        if hasattr(win, '_note_id') and win._note_id:
            try:
                self._notes.unpin_note(win._note_id)
            except Exception as e:
                print(f"Failed to unpin note: {e}")

    def _on_note_updated(self, note_id: int, title: str, content: str):
        """笔记内容更新时，通知所有相关浮窗和面板。"""
        # Update all sticky windows with this note_id
        for win in self._sticky_windows:
            if hasattr(win, '_note_id') and win._note_id == note_id:
                win.update_content(title, content)
        # Update notes panel if the note is being edited elsewhere
        self._notes_panel.refresh_note(note_id)
        # Broadcast to main signal
        self.note_updated.emit(note_id, title, content)

    # ──────────────────────────────────────────── sessions
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

        dialog = SessionSettingsDialog(session, self._preset_mgr, self)
        if dialog.exec():
            # 保存会话设置
            self._sessions.update_system_prompt(
                sid,
                session.system_prompt,
                session.preset_id
            )
            # 刷新会话列表（更新 ⚙️ 图标）
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
        """Stop and discard the worker for the given session (default: current)."""
        if sid is None:
            sid = self._current_session_id
        if not sid:
            return
        worker = self._workers.pop(sid, None)
        self._session_live.pop(sid, None)
        if worker is None:
            return
        worker.stop()
        try:
            worker.disconnect()
        except RuntimeError:
            pass

    def _switch_session(self, sid: str):
        # Don't stop any running worker — let it continue in the background.
        self._current_ai_bubble = None
        self._current_ai_msg = None
        self._current_ai_text = ""
        self._current_session_id = sid
        self._tool_status.hide()
        self._chat.stop_typing()

        session = self._sessions.get(sid)
        if session:
            self._chat.load_session(session.messages)

        # Show role greeting when session has a preset/role but no messages yet
        if session and not session.messages:
            greeting = self._get_role_greeting(session)
            if greeting:
                greeting_msg = Message(role=MessageRole.ASSISTANT, content=greeting)
                self._chat.add_message(greeting_msg)

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

    def _get_role_greeting(self, session) -> str:
        """返回会话角色的打招呼语句，无角色时返回空字符串。"""
        preset = None
        if session.preset_id:
            preset = self._preset_mgr.get(session.preset_id)
        if preset:
            return f"你好！我是{preset.icon} {preset.name}，{self._greeting_for_preset(preset.id)}有什么可以帮你的？"
        if session.system_prompt and session.system_prompt.strip():
            return "你好！我已按照自定义角色设置就绪，有什么可以帮你的？"
        return ""

    def _greeting_for_preset(self, preset_id: str) -> str:
        greetings = {
            "translator": "擅长中英互译，",
            "coder": "擅长代码生成与调试，",
            "writer": "擅长文案创作与润色，",
            "summarizer": "擅长提炼内容摘要，",
        }
        return greetings.get(preset_id, "")

    @pyqtSlot(list)
    def _on_files_attached(self, attachments: list):
        """Handle files dropped into chat area."""
        self._pending_attachments.extend(attachments)
        # TODO: Show visual feedback of attached files in input area

    # ──────────────────────────────────────────── chat
    @pyqtSlot(str)
    def _on_submit(self, text: str):
        sid = self._current_session_id
        if not sid:
            return
        if sid in self._workers:
            return  # already running for this session

        # Create user message with attachments
        user_msg = Message(
            role=MessageRole.USER,
            content=text,
            attachments=self._pending_attachments.copy()
        )
        self._pending_attachments.clear()  # Clear after use

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
        api_msgs = self._build_api_messages(session.messages[:-1])  # exclude placeholder
        all_tools = self._tools.get_openai_functions() + BUILTIN_TOOLS

        worker = ChatWorker(
            ai_client=self._ai,
            tool_manager=self._tools,
            api_messages=api_msgs,
            tools=all_tools,
            builtin_handlers=self._builtin_handler.get_handlers(),
        )
        self._workers[sid] = worker
        self._connect_worker(sid, worker)
        worker.start()

    def _build_api_messages(self, messages: list[Message]) -> list[dict]:
        """
        构建 API 消息列表，System Prompt 优先级：
        1. 会话级 system_prompt（最高优先级）
        2. 预设角色 preset_id
        3. 全局配置 config.system_prompt
        4. 默认值 DEFAULT_USER_PROMPT
        5. 追加 BUILTIN_TOOLS_INSTRUCTION
        """
        session = self._sessions.get(self._current_session_id)
        user_prompt = ""

        # 优先级 1: 会话级 system_prompt（非空且非纯空白）
        if session and session.system_prompt and session.system_prompt.strip():
            user_prompt = session.system_prompt.strip()
        # 优先级 2: 预设角色 preset_id
        elif session and session.preset_id:
            preset = self._preset_mgr.get(session.preset_id)
            if preset:
                user_prompt = preset.system_prompt.strip()
        # 优先级 3: 全局配置 config.system_prompt
        if not user_prompt:
            user_prompt = cfg.get(cfg.systemPrompt).strip()
        # 优先级 4: 默认值
        if not user_prompt:
            user_prompt = DEFAULT_USER_PROMPT

        # 优先级 5: 追加当前时间信息和内置工具说明
        full_system_prompt = user_prompt + "\n" + get_current_datetime_info() + "\n" + BUILTIN_TOOLS_INSTRUCTION

        result = [{"role": "system", "content": full_system_prompt}]

        # Use AIClient.merge_attachments_to_content to handle attachments
        merged_messages = self._ai.merge_attachments_to_content(messages)

        for i, m in enumerate(messages):
            result.append(merged_messages[i])
            # Every assistant message with tool_calls MUST be immediately followed
            # by a tool result message for each call_id, otherwise the API returns 400.
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

    # ── worker wiring ───────────────────────────────────────────────────
    def _connect_worker(self, sid: str, worker: ChatWorker):
        worker.text_chunk.connect(lambda d, s=sid: self._on_bg_text_chunk(s, d))
        worker.tool_started.connect(lambda cid, tn, p, s=sid: self._on_bg_tool_started(s, cid, tn, p))
        worker.tool_done.connect(lambda cid, r, s=sid: self._on_bg_tool_done(s, cid, r))
        worker.need_manual_params.connect(lambda cid, tn, ps, s=sid: self._on_bg_need_manual(s, cid, tn, ps))
        worker.new_ai_turn.connect(lambda s=sid: self._on_bg_new_ai_turn(s))
        worker.finished.connect(lambda s=sid: self._on_bg_finished(s))
        worker.error.connect(lambda msg, s=sid: self._on_bg_error(s, msg))

    # ── session-aware signal handlers ───────────────────────────────────
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

    def _on_bg_tool_started(self, sid: str, call_id: str, tool_name: str, params: dict):
        session = self._sessions.get(sid)
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

    def _on_bg_tool_done(self, sid: str, call_id: str, result: dict):
        session = self._sessions.get(sid)
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

    def _on_bg_need_manual(self, sid: str, call_id: str, tool_name: str, param_names: list):
        worker = self._workers.get(sid)
        if worker is None:
            return
        if sid == self._current_session_id:
            dlg = ManualParamsDialog(tool_name, param_names, self)
            params = dlg.get_values() if dlg.exec() else {}
        else:
            params = {}
        worker.supply_manual_params(params)

    def _on_bg_new_ai_turn(self, sid: str):
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

    def _on_bg_finished(self, sid: str):
        live = self._session_live.get(sid)
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

    def _on_bg_error(self, sid: str, message: str):
        hint = ""
        if "404" in message:
            hint = f"\n\n提示：请在设置中检查 API 地址（当前: {cfg.get(cfg.apiBaseUrl)}）和模型名称（当前: {cfg.get(cfg.model)}）"
        elif "401" in message or "Unauthorized" in message:
            hint = "\n\n提示：API Key 无效，请在设置中重新填写"
        error_text = f"❌ 请求失败：{message}{hint}"
        live = self._session_live.get(sid)
        if live and live["ai_msg"]:
            live["ai_msg"].content = error_text
        self._sessions.save_session(sid)
        self._workers.pop(sid, None)
        self._session_live.pop(sid, None)
        if sid != self._current_session_id:
            return
        self._chat.stop_typing()
        if self._current_ai_bubble is None and self._current_ai_msg:
            self._current_ai_bubble = self._chat.add_message(self._current_ai_msg)
        if self._current_ai_bubble:
            try:
                self._current_ai_bubble.set_content(error_text)
            except RuntimeError:
                pass
        self._input.set_enabled(True)
        self._input.focus()
        self._current_ai_msg = None
        self._current_ai_bubble = None
        self._tool_status.hide()

    # ──────────────────────────────────────────── scheduler callback
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

    # ──────────────────────────────────────────── dialogs / window actions
    def _open_settings(self):
        old_theme = cfg.get(cfg.theme)
        dlg = SettingsWindow(
            hotkey_mgr=self._hotkey_mgr,
            tool_mgr=self._tools,
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
        # FluentWindow offsets titleBar to leave room for the nav panel expand button.
        # Since the sidebar is hidden, keep the title bar full-width.
        if hasattr(self, '_title_bar'):
            self._title_bar.move(0, 0)
            self._title_bar.resize(self.width(), self._title_bar.height())

    def _minimize(self):
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

    # ──────────────────────────────────────────── screenshot
    def _start_screenshot(self):
        if hasattr(self, '_overlay') and self._overlay is not None:
            return
        self.hide()
        QTimer.singleShot(200, self._do_screenshot)

    def _do_screenshot(self):
        self._overlay = ScreenshotOverlay()
        self._overlay.captured.connect(self._on_screenshot_done)
        self._overlay.show()
        self._overlay.activateWindow()

    def _on_screenshot_done(self, pixmap: QPixmap, action: str, ocr_text: str, pos: QPoint):
        self._overlay = None
        self.show()
        self.raise_()
        self.activateWindow()

        if action == "cancel":
            return
        if action == "ocr":
            if ocr_text:
                QApplication.clipboard().setText(ocr_text)
            return
        if pixmap.isNull():
            return

        if action == "pin":
            pw = PinWindow(pixmap, pos=pos)
            pw.show()
            if not hasattr(self, '_pin_windows'):
                self._pin_windows = []
            self._pin_windows.append(pw)
            pw.closed.connect(lambda w=pw: self._pin_windows.remove(w) if w in self._pin_windows else None)
        elif action == "copy":
            QApplication.clipboard().setPixmap(pixmap)
        elif action == "save":
            path, _ = QFileDialog.getSaveFileName(
                self, "保存截图", "screenshot.png", "PNG (*.png)"
            )
            if path:
                pixmap.save(path, "PNG")

    def _show_window(self):
        if self._snap_mgr is not None and self._snap_mgr.is_snapped:
            self._snap_mgr.unsnap_full()
        else:
            if self.isMinimized():
                self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()

    # ──────────────────────────────────────────── window events
    def nativeEvent(self, eventType, message):
        # Suppress Windows system context menu on title bar right-click.
        # FluentWindow returns HTCAPTION for the title bar area, which causes
        # Windows to show its own system menu alongside our custom RoundMenu.
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

    # ──────────────────────────────────────────── intercept close → tray
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
        """Stop all background workers. Call before app quit."""
        self._hotkey_mgr.stop()
        for sid in list(self._workers):
            self._cancel_worker(sid)

    def _on_quit(self):
        # Save layout only if window is visible (otherwise closeEvent already saved)
        if self.isVisible():
            sizes = self._chat_splitter.sizes()
            session_width = sizes[0] if sizes[0] > 0 else getattr(self, '_saved_session_width', 180)
            cfg.set(cfg.windowWidth, self.width())
            cfg.set(cfg.windowHeight, self.height())
            cfg.set(cfg.sessionPanelWidth, max(session_width, 120))
        cfg.save()
        self.cleanup()
        QApplication.instance().quit()
