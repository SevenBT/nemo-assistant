"""Chat session and AgentLoop UI controller."""

from PyQt6.QtCore import QObject

from app.core.agent_loop import AgentLoop
from app.core.config import cfg
from app.models.message import Message, MessageRole, ToolCall
from app.ui.manual_params_dialog import ManualParamsDialog
from app.ui.session_settings_dialog import SessionSettingsDialog

_CANCELLED_MARKER = "（已取消）"


class ChatSessionController(QObject):
    """Coordinates session list state, chat widgets, and background agent workers."""

    def __init__(
        self,
        *,
        parent,
        session_mgr,
        llm_gateway,
        registry,
        prompt_builder,
        chat,
        input_widget,
        session_panel,
        tool_status,
        consolidator=None,
    ):
        super().__init__(parent)
        self._parent = parent
        self._sessions = session_mgr
        self._llm = llm_gateway
        self._registry = registry
        self._prompt_builder = prompt_builder
        self._chat = chat
        self._input = input_widget
        self._session_panel = session_panel
        self._tool_status = tool_status
        self._consolidator = consolidator

        self._current_session_id: str | None = None
        self._workers: dict[str, AgentLoop] = {}
        self._cancelled_workers: list[AgentLoop] = []
        self._session_live: dict[str, dict] = {}
        self._current_ai_bubble = None
        self._current_ai_msg: Message | None = None
        self._current_ai_text = ""
        self._pending_attachments: list = []

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def init_sessions(self):
        sessions = self._sessions.get_sessions()
        if not sessions:
            session = self._sessions.create()
            sessions = [session]
        self._session_panel.load(sessions, sessions[0].id)
        self.switch_session(sessions[0].id)

    def new_session(self):
        session = self._sessions.create()
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, session.id)
        self.switch_session(session.id)

    def delete_session(self, sid: str):
        self._sessions.delete(sid)
        sessions = self._sessions.get_sessions()
        if not sessions:
            session = self._sessions.create()
            sessions = [session]
        self._session_panel.load(sessions, sessions[0].id)
        self.switch_session(sessions[0].id)

    def rename_session(self, sid: str, title: str):
        self._sessions.rename(sid, title)
        self._session_panel.update_title(sid, title)

    def open_session_settings(self, sid: str):
        session = self._sessions.get(sid)
        if not session:
            return

        dialog = SessionSettingsDialog(session, self._parent)
        if dialog.exec():
            self._sessions.update_system_prompt(sid, session.system_prompt)
            sessions = self._sessions.get_sessions()
            self._session_panel.load(sessions, sid)

    def pin_session(self, sid: str, pinned: bool):
        self._sessions.pin_session(sid, pinned)
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, sid)

    def reorder_sessions(self, ordered_ids: list):
        self._sessions.reorder_sessions(ordered_ids)

    def select_session(self, sid: str):
        if sid != self._current_session_id:
            self.switch_session(sid)

    def cancel_worker(self, sid: str | None = None, *, mark_cancelled: bool = True):
        if sid is None:
            sid = self._current_session_id
        if not sid:
            return
        worker = self._workers.pop(sid, None)
        live = self._session_live.pop(sid, None)
        if worker is None:
            return

        if mark_cancelled and live:
            self._mark_live_message_cancelled(sid, live)

        try:
            worker.disconnect()
        except RuntimeError:
            pass
        self._cancelled_workers.append(worker)
        try:
            worker.finished.connect(
                lambda _=None, w=worker: self._release_cancelled_worker(w)
            )
        except (AttributeError, RuntimeError):
            pass
        worker.cancel()

        if sid == self._current_session_id:
            self._chat.stop_typing()
            self._tool_status.hide()
            self._input.set_running(False)
            self._input.focus()
            self._current_ai_msg = None
            self._current_ai_bubble = None

    def switch_session(self, sid: str):
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
            self._input.set_running(True)
            if not live.get("first_chunk_sent"):
                self._chat.start_typing()
        else:
            self._input.set_running(False)

        self._input.focus()

    def on_files_attached(self, attachments: list):
        self._pending_attachments.extend(attachments)

    def submit(self, text: str):
        sid = self._current_session_id
        if not sid:
            return
        if sid in self._workers:
            return

        user_msg = Message(
            role=MessageRole.USER,
            content=text,
            attachments=self._pending_attachments.copy(),
        )
        self._pending_attachments.clear()

        self._sessions.add_message(sid, user_msg)
        self._chat.add_message(user_msg)
        self._session_panel.update_title(sid, self._sessions.get(sid).title)

        ai_msg = Message(role=MessageRole.ASSISTANT, content="")
        self._sessions.add_message(sid, ai_msg)
        self._current_ai_msg = ai_msg
        self._current_ai_bubble = None
        self._current_ai_text = ""
        self._input.set_running(True)
        self._tool_status.hide()
        self._chat.start_typing()

        self._session_live[sid] = {
            "ai_msg": ai_msg,
            "ai_text": "",
            "first_chunk_sent": False,
        }

        session = self._sessions.get(sid)
        if self._consolidator is not None:
            original_msgs = session.messages[:-1]
            compressed = self._consolidator.maybe_consolidate(original_msgs, sid)
            if len(compressed) < len(original_msgs):
                session.messages = compressed + [session.messages[-1]]
                self._sessions.save_session(sid)

        api_msgs = self._prompt_builder.build(session.messages[:-1], sid)

        worker = AgentLoop(
            llm_gateway=self._llm,
            registry=self._registry,
            api_messages=api_msgs,
            session_id=sid,
        )
        self._workers[sid] = worker
        self._connect_worker(sid, worker)
        worker.start()

    def cleanup(self):
        for sid in list(self._workers):
            self.cancel_worker(sid, mark_cancelled=False)

    def _connect_worker(self, sid: str, worker: AgentLoop):
        worker.text_chunk.connect(lambda delta, s=sid: self._on_text_chunk(s, delta))
        worker.tool_event.connect(
            lambda call_id, phase, payload, s=sid: self._on_tool_event(
                s, call_id, phase, payload
            )
        )
        worker.need_input.connect(
            lambda call_id, tool_name, params, s=sid: self._on_need_input(
                s, call_id, tool_name, params
            )
        )
        worker.new_turn.connect(lambda turn_count, s=sid: self._on_new_turn(s, turn_count))
        worker.done.connect(lambda info, s=sid: self._on_done(s, info))

    def _on_text_chunk(self, sid: str, delta: str):
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

    def _on_tool_event(self, sid: str, call_id: str, phase: str, payload: dict):
        session = self._sessions.get(sid)
        if phase == "start":
            tool_name = payload["name"]
            params = payload["params"]
            if session and session.messages:
                tool_call = ToolCall(
                    id=call_id,
                    name=tool_name,
                    arguments=params,
                    status="running",
                )
                session.messages[-1].tool_calls.append(tool_call)
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
                for message in reversed(session.messages):
                    for tool_call in message.tool_calls:
                        if tool_call.id == call_id:
                            tool_call.result = result
                            tool_call.status = result.get("status", "success")
                            break
            if sid != self._current_session_id:
                return
            if self._current_ai_bubble:
                self._current_ai_bubble.update_tool_card(call_id, result)

    def _on_need_input(
        self,
        sid: str,
        call_id: str,
        tool_name: str,
        param_names: list,
    ):
        worker = self._workers.get(sid)
        if worker is None:
            return
        if sid == self._current_session_id:
            dialog = ManualParamsDialog(tool_name, param_names, self._parent)
            params = dialog.get_values() if dialog.exec() else {}
        else:
            params = {}
        worker.supply_input(params)

    def _on_new_turn(self, sid: str, turn_count: int):
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

    def _on_done(self, sid: str, info: dict):
        live = self._session_live.get(sid)
        ok = info.get("ok", True)
        error_msg = info.get("error")

        if ok:
            if live and live["ai_msg"] and not live["ai_msg"].content:
                live["ai_msg"].content = live["ai_text"]
                if (
                    live["ai_text"]
                    and sid == self._current_session_id
                    and self._current_ai_bubble is None
                ):
                    self._current_ai_bubble = self._chat.add_message(live["ai_msg"])
            session = self._sessions.get(sid)
            if session:
                session.messages = [
                    message
                    for message in session.messages
                    if not (
                        message.role == MessageRole.ASSISTANT
                        and not message.content
                        and not message.tool_calls
                    )
                ]
        else:
            error_text = self._format_error(error_msg)
            if live and live["ai_msg"]:
                live["ai_msg"].content = error_text
            if sid == self._current_session_id:
                if self._current_ai_bubble is None and self._current_ai_msg:
                    self._current_ai_bubble = self._chat.add_message(
                        self._current_ai_msg
                    )
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
        self._input.set_running(False)
        self._input.focus()
        self._current_ai_msg = None
        self._current_ai_bubble = None

    def _mark_live_message_cancelled(self, sid: str, live: dict):
        ai_msg = live.get("ai_msg")
        if ai_msg is None:
            return
        text = live.get("ai_text") or ai_msg.content or ""
        ai_msg.content = self._cancelled_content(text)
        self._sessions.save_session(sid)
        if sid != self._current_session_id:
            return
        if self._current_ai_bubble is None:
            self._current_ai_msg = ai_msg
            self._current_ai_bubble = self._chat.add_message(ai_msg)
        if self._current_ai_bubble:
            try:
                self._current_ai_bubble.set_content(ai_msg.content)
            except RuntimeError:
                self._current_ai_bubble = None
        self._chat.scroll_bottom()

    def _cancelled_content(self, text: str) -> str:
        text = text.rstrip()
        if text.endswith(_CANCELLED_MARKER):
            return text
        if text:
            return f"{text}\n\n{_CANCELLED_MARKER}"
        return _CANCELLED_MARKER

    def _release_cancelled_worker(self, worker: AgentLoop):
        try:
            self._cancelled_workers.remove(worker)
        except ValueError:
            pass

    def _format_error(self, error_msg: str | None) -> str:
        hint = ""
        if error_msg and "404" in error_msg:
            hint = (
                "\n\n提示：请在设置中检查 API 地址"
                f"（当前: {cfg.get(cfg.apiBaseUrl)}）和模型名称"
                f"（当前: {cfg.get(cfg.model)}）"
            )
        elif error_msg and ("401" in error_msg or "Unauthorized" in error_msg):
            hint = "\n\n提示：API Key 无效，请在设置中重新填写"
        return f"❌ 请求失败：{error_msg}{hint}"
