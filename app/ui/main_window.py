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
import time

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.ai_client import AIClient
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
from app.ui.scheduler_dialog import SchedulerPanel
from app.ui.screenshot_overlay import ScreenshotOverlay
from app.ui.session_panel import SessionPanel
from app.ui.settings_dialog import SettingsDialog
from app.ui.style import THEMES, generate_stylesheet
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

BUILTIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_scheduled_task",
            "description": "创建一个定时任务，定期执行某个工具脚本或提醒用户",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "任务名称"},
                    "tool_name": {"type": "string", "description": "要执行的工具名称"},
                    "params": {"type": "object", "description": "工具参数，JSON对象"},
                    "trigger_type": {
                        "type": "string",
                        "enum": ["cron", "interval", "date"],
                        "description": "触发器类型",
                    },
                    "trigger_config": {
                        "type": "object",
                        "description": "触发器配置，如 {hour:9, minute:0} 或 {hours:1}",
                    },
                    "description": {"type": "string", "description": "任务描述"},
                },
                "required": ["name", "tool_name", "trigger_type", "trigger_config"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_scheduled_tasks",
            "description": "列出所有当前定时任务",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_scheduled_task",
            "description": "删除一个定时任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "任务ID"}
                },
                "required": ["job_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_notes",
            "description": "读取用户所有笔记的列表，包含标题、内容预览和更新时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_note",
            "description": "创建一条新笔记，保存标题和正文内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题，简明扼要"},
                    "content": {"type": "string", "description": "笔记正文内容"},
                },
                "required": ["title", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "summarize_session_as_note",
            "description": "将当前会话的对话内容总结，并作为笔记保存",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "笔记标题（简要概括本次对话主题）"},
                    "summary": {"type": "string", "description": "对话内容的总结文本"},
                },
                "required": ["title", "summary"],
            },
        },
    },
]


# ─────────────────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self._win = window
        self.setObjectName("titleBar")
        self.setFixedHeight(42)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 6, 0)
        layout.setSpacing(4)

        self._toggle_btn = QPushButton("≡")
        self._toggle_btn.setObjectName("iconBtn")
        self._toggle_btn.setFixedSize(32, 28)
        self._toggle_btn.setToolTip("显示/隐藏会话列表")
        self._toggle_btn.clicked.connect(self._win._toggle_session_panel)
        layout.addWidget(self._toggle_btn)

        title = QLabel("AI Agent")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        # View-switcher buttons (exclusive, checkable)
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        for i, (text, tip) in enumerate([
            ("聊天", "AI 对话"),
            ("笔记", "笔记管理"),
            ("定时", "定时任务"),
        ]):
            btn = QPushButton(text)
            btn.setObjectName("viewBtn")
            btn.setFixedSize(56, 30)
            btn.setToolTip(tip)
            btn.setCheckable(True)
            self._btn_group.addButton(btn, i)
            layout.addWidget(btn)
        self._btn_group.button(0).setChecked(True)
        self._btn_group.idClicked.connect(self._win._switch_view)

        snap_btn = QPushButton("✂")
        snap_btn.setObjectName("iconBtn")
        snap_btn.setFixedSize(32, 28)
        snap_btn.setToolTip("截图")
        f = snap_btn.font()
        f.setPointSize(16)
        snap_btn.setFont(f)
        snap_btn.clicked.connect(self._win._start_screenshot)
        layout.addWidget(snap_btn)

        min_btn = QPushButton("─")
        min_btn.setObjectName("iconBtn")
        min_btn.setFixedSize(32, 28)
        min_btn.setToolTip("最小化到托盘")
        min_btn.clicked.connect(self._win._minimize)
        layout.addWidget(min_btn)

        # × hides to tray; real quit is in the tray menu
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(32, 28)
        close_btn.setToolTip("最小化到托盘 (从托盘右键退出)")
        close_btn.clicked.connect(self._win._minimize)
        layout.addWidget(close_btn)

    def set_active_view(self, index: int):
        self._btn_group.button(index).setChecked(True)
        # Session panel toggle only makes sense on chat view
        self._toggle_btn.setVisible(index == 0)

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._win._snap_mgr is not None:
                self._win._snap_mgr.cancel_animation()
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()


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
        self._resize_active = False
        self._resize_edges_active = None
        self._resize_start_geo = None
        self._resize_start_pos = None
        self._snap_mgr: EdgeSnapManager | None = None
        self._build_window()
        self._build_ui()
        self._setup_tray()
        self._init_sessions()
        self._install_resize_filter()
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
        body = QHBoxLayout(chat_page)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._session_panel = SessionPanel()
        self._session_panel.session_selected.connect(self._on_session_select)
        self._session_panel.session_create_requested.connect(self._new_session)
        self._session_panel.session_delete_requested.connect(self._delete_session)
        self._session_panel.session_rename_requested.connect(self._rename_session)
        self._session_panel.hide()
        body.addWidget(self._session_panel)

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
        body.addWidget(chat_area, 1)

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
        # Null out the foreground bubble/msg refs (they belong to the old session's UI).
        self._current_ai_bubble = None
        self._current_ai_msg = None
        self._current_ai_text = ""
        self._current_session_id = sid
        self._tool_status.hide()  # prevent old session's tool status leaking into new session
        self._chat.stop_typing()

        # Reload chat history (background worker has been updating session.messages live)
        session = self._sessions.get(sid)
        if session:
            self._chat.load_session(session.messages)

        # If the new session has a running worker, re-attach foreground references
        live = self._session_live.get(sid)
        if live:
            self._current_ai_msg = live["ai_msg"]
            self._current_ai_text = live["ai_text"]
            # Only set bubble if we've received text (bubble exists in chat)
            if live.get("first_chunk_sent") and live["ai_text"]:
                self._current_ai_bubble = self._chat.last_bubble()
            else:
                self._current_ai_bubble = None
            self._input.set_enabled(False)
            # Resume typing animation if still waiting for first chunk
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

        # Add user message
        user_msg = Message(role=MessageRole.USER, content=text)
        self._sessions.add_message(sid, user_msg)
        self._chat.add_message(user_msg)
        self._session_panel.update_title(sid, self._sessions.get(sid).title)

        # Placeholder AI message (don't add bubble yet - wait for actual content)
        ai_msg = Message(role=MessageRole.ASSISTANT, content="")
        self._sessions.add_message(sid, ai_msg)
        self._current_ai_msg = ai_msg
        self._current_ai_bubble = None  # Will be created when text arrives
        self._current_ai_text = ""
        self._input.set_enabled(False)
        self._tool_status.hide()
        self._chat.start_typing()  # show typing animation

        # Per-session live state (used when this session goes to background)
        self._session_live[sid] = {"ai_msg": ai_msg, "ai_text": "", "first_chunk_sent": False}

        # Build API message list
        session = self._sessions.get(sid)
        api_msgs = self._build_api_messages(session.messages[:-1])  # exclude placeholder
        all_tools = self._tools.get_openai_functions() + BUILTIN_TOOLS

        worker = ChatWorker(
            ai_client=self._ai,
            tool_manager=self._tools,
            api_messages=api_msgs,
            tools=all_tools,
            builtin_handlers={
                "create_scheduled_task": self._handle_create_task,
                "list_scheduled_tasks": self._handle_list_tasks,
                "delete_scheduled_task": self._handle_delete_task,
                "read_notes": self._handle_read_notes,
                "create_note": self._handle_create_note,
                "summarize_session_as_note": self._handle_summarize_as_note,
            },
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
            # Tool results are stored in ToolCall.result (not as separate Message objects).
            if m.role == MessageRole.ASSISTANT and m.tool_calls:
                # Only inject tool results when ALL calls in this turn have a result.
                # If any result is missing (incomplete turn), drop this whole turn from
                # history to avoid sending a tool_calls message without matching tool messages.
                all_done = all(tc.result is not None for tc in m.tool_calls)
                if all_done:
                    for tc in m.tool_calls:
                        result.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(tc.result, ensure_ascii=False),
                        })
                else:
                    # Remove the incomplete assistant message we just appended
                    result.pop()
        return result

    # ── worker wiring ───────────────────────────────────────────────────
    def _connect_worker(self, sid: str, worker: ChatWorker):
        """Wire all worker signals with the session id captured in closures."""
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
        # Stop typing animation on first chunk
        if not live.get("first_chunk_sent"):
            self._chat.stop_typing()
            live["first_chunk_sent"] = True
        self._current_ai_text = live["ai_text"]
        # Create bubble on first text if not exists
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
        self._tool_status.setText(f"⏳ 正在使用工具: {tool_name}...")
        self._tool_status.show()

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

    def _on_bg_need_manual(self, sid: str, call_id: str, tool_name: str, param_names: list):
        worker = self._workers.get(sid)
        if worker is None:
            return
        if sid == self._current_session_id:
            dlg = ManualParamsDialog(tool_name, param_names, self)
            params = dlg.get_values() if dlg.exec() else {}
        else:
            params = {}  # auto-skip for background sessions
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
        self._current_ai_bubble = None  # Will be created when text arrives
        self._current_ai_text = ""
        self._chat.start_typing()

    def _on_bg_finished(self, sid: str):
        live = self._session_live.get(sid)
        if live and live["ai_msg"] and not live["ai_msg"].content:
            live["ai_msg"].content = live["ai_text"]
            # Create bubble for final text if we have content but no bubble yet
            if live["ai_text"] and sid == self._current_session_id and self._current_ai_bubble is None:
                self._current_ai_bubble = self._chat.add_message(live["ai_msg"])
        # Remove empty AI messages (no content, no tool calls) from session
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
        # Create bubble for error if not exists
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

    # ──────────────────────────────────────────── built-in tool handlers
    def _handle_create_task(self, args: dict) -> dict:
        try:
            job_id = self._scheduler.add_job(
                name=args.get("name", "未命名任务"),
                tool_name=args.get("tool_name", ""),
                params=args.get("params", {}),
                trigger_type=args["trigger_type"],
                trigger_config=args["trigger_config"],
                description=args.get("description", ""),
            )
            return {"status": "success", "data": {"job_id": job_id, "name": args.get("name")}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    def _handle_list_tasks(self, _args: dict) -> dict:
        jobs = self._scheduler.get_jobs()
        return {
            "status": "success",
            "data": {
                "jobs": [
                    {"id": j["id"], "name": j["name"], "trigger_type": j["trigger_type"]}
                    for j in jobs
                ]
            },
        }

    def _handle_delete_task(self, args: dict) -> dict:
        job_id = args.get("job_id", "")
        self._scheduler.remove_job(job_id)
        return {"status": "success", "data": {"deleted": job_id}}

    # ── note tool handlers ──────────────────────────────────────────────────
    def _handle_read_notes(self, _args: dict) -> dict:
        previews = self._notes.get_preview_list()
        return {"status": "success", "data": {"notes": previews, "count": len(previews)}}

    def _handle_create_note(self, args: dict) -> dict:
        try:
            note = self._notes.create(
                title=args.get("title", "新笔记"),
                content=args.get("content", ""),
            )
            self._notes_panel.refresh()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    def _handle_summarize_as_note(self, args: dict) -> dict:
        try:
            note = self._notes.create(
                title=args.get("title", "会话总结"),
                content=args.get("summary", ""),
            )
            self._notes_panel.refresh()
            return {"status": "success", "data": {"id": note.id, "title": note.title}}
        except Exception as e:
            return {"status": "error", "data": {"message": str(e)}}

    # ──────────────────────────────────────────── scheduler callback
    def _on_scheduler_result(self, job_id: str, job_name: str, result: dict):
        # Called from APScheduler's background thread — use signal to reach main thread.
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
            # Re-apply stylesheet if theme changed
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
            return  # already capturing
        self.hide()
        # Delay to let the window disappear before capturing
        QTimer.singleShot(200, self._do_screenshot)

    def _do_screenshot(self):
        self._overlay = ScreenshotOverlay()
        self._overlay.captured.connect(self._on_screenshot_done)
        self._overlay.show()
        self._overlay.activateWindow()  # ensure keyboard focus for Esc

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
            # Keep reference so it isn't garbage-collected
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
        if self._session_panel.isVisible():
            self._session_panel.hide()
        else:
            self._session_panel.show()

    # ──────────────────────────────────────────── edge resize
    _RESIZE_BORDER = 8
    _resize_cursor_shape = None   # tracks active override cursor shape

    def _resize_edges(self, win_pos):
        """Return Qt.Edge flags for window-local position, or None if not on any edge."""
        x, y, w, h = win_pos.x(), win_pos.y(), self.width(), self.height()
        B = self._RESIZE_BORDER
        on_l = x < B
        on_r = x > w - B
        on_t = y < B
        on_b = y > h - B
        if not (on_l or on_r or on_t or on_b):
            return None
        edges = Qt.Edge(0)
        if on_l: edges |= Qt.Edge.LeftEdge
        if on_r: edges |= Qt.Edge.RightEdge
        if on_t: edges |= Qt.Edge.TopEdge
        if on_b: edges |= Qt.Edge.BottomEdge
        return edges

    def _cursor_for_edges(self, edges):
        L, R, T, B = Qt.Edge.LeftEdge, Qt.Edge.RightEdge, Qt.Edge.TopEdge, Qt.Edge.BottomEdge
        has = lambda e: bool(edges & e)
        if (has(T) and has(L)) or (has(B) and has(R)): return Qt.CursorShape.SizeFDiagCursor
        if (has(T) and has(R)) or (has(B) and has(L)): return Qt.CursorShape.SizeBDiagCursor
        if has(L) or has(R): return Qt.CursorShape.SizeHorCursor
        return Qt.CursorShape.SizeVerCursor

    def _apply_resize_cursor(self, edges):
        shape = self._cursor_for_edges(edges)
        if self._resize_cursor_shape is None:
            QApplication.setOverrideCursor(shape)
        elif shape != self._resize_cursor_shape:
            QApplication.changeOverrideCursor(shape)
        else:
            return
        self._resize_cursor_shape = shape

    def _clear_resize_cursor(self):
        if self._resize_cursor_shape is not None:
            QApplication.restoreOverrideCursor()
            self._resize_cursor_shape = None

    def _do_manual_resize(self, global_pos):
        geo = self._resize_start_geo
        dx = global_pos.x() - self._resize_start_pos.x()
        dy = global_pos.y() - self._resize_start_pos.y()
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        min_w, min_h = self.minimumWidth(), self.minimumHeight()
        e = self._resize_edges_active
        nx, ny, nw, nh = x, y, w, h
        if bool(e & Qt.Edge.RightEdge):  nw = max(min_w, w + dx)
        if bool(e & Qt.Edge.BottomEdge): nh = max(min_h, h + dy)
        if bool(e & Qt.Edge.LeftEdge):   nw = max(min_w, w - dx); nx = x + w - nw
        if bool(e & Qt.Edge.TopEdge):    nh = max(min_h, h - dy); ny = y + h - nh
        self.setGeometry(nx, ny, nw, nh)

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        etype = event.type()

        # Suppress resize while snapped or animating to avoid interfering with snap
        if self._snap_mgr is not None and (self._snap_mgr.is_snapped or self._snap_mgr.is_animating):
            return False

        if etype == QEvent.Type.MouseMove:
            gpos = event.globalPosition().toPoint()
            if self._resize_active:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._do_manual_resize(gpos)
                else:
                    self._resize_active = False   # 按键在窗口外释放
                return True
            local = self.mapFromGlobal(gpos)
            edges = self._resize_edges(local) if self.rect().contains(local) else None
            if edges is not None:
                self._apply_resize_cursor(edges)
            else:
                self._clear_resize_cursor()

        elif etype == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                gpos = event.globalPosition().toPoint()
                local = self.mapFromGlobal(gpos)
                edges = self._resize_edges(local) if self.rect().contains(local) else None
                if edges is not None:
                    self._resize_active = True
                    self._resize_edges_active = edges
                    self._resize_start_geo = self.geometry()
                    self._resize_start_pos = gpos
                    self._clear_resize_cursor()
                    return True

        elif etype == QEvent.Type.MouseButtonRelease:
            if self._resize_active:
                self._resize_active = False
                return True

        return super().eventFilter(obj, event)

    def _install_resize_filter(self):
        QApplication.instance().installEventFilter(self)

    # ──────────────────────────────────────────── intercept close → tray
    def closeEvent(self, event):
        # Save position, then hide to tray instead of quitting
        self._config.update_window_config(
            x=self.x(), y=self.y(),
            width=self.width(), height=self.height(),
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
