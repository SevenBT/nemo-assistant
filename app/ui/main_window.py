"""
Main floating window.

Layout:
  ┌─ TitleBar ───────────────────────────────────────────────────┐
  │ [≡] AI Agent ── [聊天] [笔记] [定时] ── [□] [─] [✕]        │
  ├──────────────────────────────────────────────────────────────┤
  │ QStackedWidget                                               │
  │  page 0: SessionPanel | ChatWidget + InputWidget             │
  │  page 1: NotesPanel                                          │
  │  page 2: SchedulerPanel                                      │
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.ai_client import AIClient
from app.core.builtin_tools import BUILTIN_TOOLS, BuiltinToolHandler
from app.core.config import ConfigManager
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
from app.ui.resize_filter import ResizeFilter
from app.ui.scheduler_dialog import SchedulerPanel
from app.ui.screenshot_overlay import ScreenshotOverlay
from app.ui.session_panel import SessionPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.style import THEMES, generate_stylesheet
from app.ui.title_bar import TitleBar
from app.ui.toast import show_toast
from app.ui.tray_manager import TrayManager

SYSTEM_PROMPT = """你是一个智能AI助手。你可以调用工具来帮助用户完成任务。

【定时任务】
如果用户想创建定时任务，使用 create_scheduled_task 工具。触发器配置示例：
- 每天9点: {"trigger_type": "cron", "trigger_config": {"hour": 9, "minute": 0}}
- 每小时: {"trigger_type": "interval", "trigger_config": {"hours": 1}}
- 一次性: {"trigger_type": "date", "trigger_config": {"run_date": "2025-12-31 09:00:00"}}

【列出定时任务】使用 list_scheduled_tasks 工具。
【删除定时任务】使用 delete_scheduled_task 工具，提供 job_id 参数。

【笔记】
- 使用 read_notes 查看用户的笔记列表和内容预览。
- 使用 create_note 为用户保存一条新笔记（title + content）。
- 使用 summarize_session_as_note 将当前对话总结后保存为笔记。

请用中文回复。"""


# ─────────────────────────────────────────────────────────────────────
class MainWindow(QWidget):
    # Used to marshal scheduler callbacks from background threads to the main thread
    _notify_signal = pyqtSignal(str, str)  # title, body

    def __init__(
        self,
        config: ConfigManager,
        session_mgr: SessionManager,
        tool_mgr: ToolManager,
        scheduler: SchedulerManager,
        note_mgr: NoteManager,
    ):
        super().__init__()
        self._config = config
        self._sessions = session_mgr
        self._tools = tool_mgr
        self._scheduler = scheduler
        self._notes = note_mgr
        self._ai = AIClient(config)
        self._current_session_id: str | None = None
        self._workers: dict[str, ChatWorker] = {}
        self._session_live: dict[str, dict] = {}  # sid -> {ai_msg, ai_text}
        self._current_ai_bubble: MessageBubble | None = None
        self._current_ai_msg: Message | None = None
        self._current_ai_text = ""
        self._snap_mgr: EdgeSnapManager | None = None
        self._build_window()
        self._build_ui()
        self._builtin_handler = BuiltinToolHandler(
            scheduler=scheduler,
            note_mgr=note_mgr,
            on_note_created=lambda: self._notes_panel.refresh(),
        )
        self._setup_tray()
        self._init_sessions()
        self._resize_filter = ResizeFilter(self)
        self._resize_filter.install()
        self._snap_mgr = EdgeSnapManager(self)
        self._snap_mgr.set_enabled(self._config.window_config.get("edge_snap", True))
        self._notify_signal.connect(self._on_notify)

    # ──────────────────────────────────────────── window setup
    def _build_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        wcfg = self._config.window_config
        self.resize(wcfg.get("width", 420), wcfg.get("height", 700))
        self.move(wcfg.get("x", 100), wcfg.get("y", 80))
        self.setWindowOpacity(wcfg.get("opacity", 0.97))
        if wcfg.get("always_on_top", True):
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._container = QFrame()
        self._container.setObjectName("mainWindow")
        outer.addWidget(self._container)

        root = QVBoxLayout(self._container)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # title bar
        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        # stacked body: page 0=chat, page 1=notes, page 2=scheduler
        self._stack = QStackedWidget()

        # ── page 0: chat view ─────────────────────────────────────────
        chat_page = QWidget()
        page_layout = QVBoxLayout(chat_page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Use QSplitter for resizable session panel
        self._chat_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._chat_splitter.setHandleWidth(6)
        self._chat_splitter.setChildrenCollapsible(True)

        self._session_panel = SessionPanel()
        self._session_panel.session_selected.connect(self._on_session_select)
        self._session_panel.session_create_requested.connect(self._new_session)
        self._session_panel.session_delete_requested.connect(self._delete_session)
        self._session_panel.session_rename_requested.connect(self._rename_session)
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
        chat_area = QFrame()
        chat_area.setObjectName("chatArea")
        chat_area.setLayout(chat_col)
        self._chat_splitter.addWidget(chat_area)

        # Set initial sizes from config (session panel width)
        wcfg = self._config.window_config
        session_width = wcfg.get("session_panel_width", 180)
        chat_width = wcfg.get("width", 420) - session_width
        self._chat_splitter.setSizes([session_width, chat_width])

        # Collapse session panel if config says it should be hidden
        if not wcfg.get("session_panel_visible", True):
            self._chat_splitter.setSizes([0, session_width + chat_width])

        page_layout.addWidget(self._chat_splitter)
        self._stack.addWidget(chat_page)          # index 0

        # ── page 1: notes panel ───────────────────────────────────────
        self._notes_panel = NotesPanel(self._notes)
        self._stack.addWidget(self._notes_panel)  # index 1

        # ── page 2: scheduler panel ───────────────────────────────────
        self._scheduler_panel = SchedulerPanel(self._scheduler)
        self._stack.addWidget(self._scheduler_panel)  # index 2

        root.addWidget(self._stack, 1)
        self.setMinimumSize(320, 420)
        self.setMouseTracking(True)

    def _setup_tray(self):
        self._tray = TrayManager(self)
        self._tray.show_requested.connect(self._show_window)
        self._tray.settings_requested.connect(self._open_settings)
        self._tray.screenshot_requested.connect(self._start_screenshot)
        self._tray.quit_requested.connect(self._on_quit)
        self._scheduler.set_result_callback(self._on_scheduler_result)

    # ──────────────────────────────────────────── sessions
    def _init_sessions(self):
        sessions = self._sessions.get_sessions()
        if not sessions:
            s = self._sessions.create()
            sessions = [s]
        self._session_panel.load(sessions, sessions[0].id)
        self._switch_session(sessions[0].id)

    def _new_session(self):
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

    # ──────────────────────────────────────────── chat
    @pyqtSlot(str)
    def _on_submit(self, text: str):
        sid = self._current_session_id
        if not sid:
            return
        if sid in self._workers:
            return  # already running for this session

        user_msg = Message(role=MessageRole.USER, content=text)
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
        result = [{"role": "system", "content": SYSTEM_PROMPT}]
        for m in messages:
            result.append(m.to_api_dict())
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
            hint = f"\n\n提示：请在设置中检查 API 地址（当前: {self._config.api_base_url}）和模型名称（当前: {self._config.model}）"
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
        colors = THEMES.get(self._config.theme, THEMES["classic"])
        show_toast(title, body, accent=colors["accent"])

    # ──────────────────────────────────────────── dialogs / window actions
    def _open_settings(self):
        old_theme = self._config.theme
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            wcfg = self._config.window_config
            self.setWindowOpacity(wcfg.get("opacity", 0.97))
            flag = Qt.WindowType.WindowStaysOnTopHint
            self.setWindowFlag(flag, wcfg.get("always_on_top", True))
            if self._snap_mgr is not None:
                self._snap_mgr.set_enabled(wcfg.get("edge_snap", True))
            new_theme = self._config.theme
            if new_theme != old_theme:
                QApplication.instance().setStyleSheet(generate_stylesheet(new_theme))
            self.show()

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        self._title_bar.set_active_view(index)

    def _minimize(self):
        self.hide()

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
            self.show()
            self.raise_()
            self.activateWindow()

    # ──────────────────────────────────────────── window events
    def moveEvent(self, event):
        super().moveEvent(event)
        if self._snap_mgr is not None:
            self._snap_mgr.check_position()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._snap_mgr is not None:
            self._snap_mgr.on_enter()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._snap_mgr is not None:
            self._snap_mgr.on_leave()

    def _toggle_session_panel(self):
        sizes = self._chat_splitter.sizes()
        total = sum(sizes)
        session_width = sizes[0]

        if session_width > 0:
            self._saved_session_width = session_width
            self._chat_splitter.setSizes([0, total])
        else:
            width = getattr(self, '_saved_session_width', None) or self._config.window_config.get("session_panel_width", 180)
            self._chat_splitter.setSizes([width, total - width])

    # ──────────────────────────────────────────── intercept close → tray
    def closeEvent(self, event):
        sizes = self._chat_splitter.sizes()
        session_width = sizes[0] if sizes[0] > 0 else getattr(self, '_saved_session_width', 180)
        session_visible = sizes[0] > 0
        self._config.update_window_config(
            x=self.x(), y=self.y(),
            width=self.width(), height=self.height(),
            session_panel_width=max(session_width, 120),
            session_panel_visible=session_visible,
        )
        event.ignore()
        self.hide()

    def cleanup(self):
        """Stop all background workers. Call before app quit."""
        for sid in list(self._workers):
            self._cancel_worker(sid)

    def _on_quit(self):
        self.cleanup()
        QApplication.instance().quit()
