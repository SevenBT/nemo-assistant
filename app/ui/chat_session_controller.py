"""Chat session and AgentLoop UI controller."""

from PyQt6.QtCore import QObject

from app.core.agent_loop import AgentLoop
from app.core.audit_hooks import EvalHook, SecurityAuditHook
from app.core.config import cfg
from app.i18n import t, all_translations
from app.models.message import Message, MessageRole, ToolCall
from app.models.session import (
    default_session_title,
    is_default_session_title,
    SOURCE_MANUAL,
    SOURCE_READING,
)
from app.ui.manual_params_dialog import ManualParamsDialog
from app.ui.session_settings_dialog import SessionSettingsDialog


def _cancelled_marker() -> str:
    """「已取消」标记（按当前语言）。"""
    return t("chat.cancelled")


def reading_session_title() -> str:
    """划词「连续解释」快速会话的默认标题（按当前语言）。"""
    return t("session.reading.defaultTitle")


def is_reading_session_title(title: str) -> bool:
    """是否仍是快速会话默认标题——兼容任何语言写入的旧数据。"""
    return title in all_translations("session.reading.defaultTitle")


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
        trace_store=None,
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
        self._trace_store = trace_store

        self._current_session_id: str | None = None
        self._workers: dict[str, AgentLoop] = {}
        self._cancelled_workers: list[AgentLoop] = []
        self._session_live: dict[str, dict] = {}
        self._current_ai_bubble = None
        self._current_ai_msg: Message | None = None
        self._current_ai_text = ""

    @property
    def current_session_id(self) -> str | None:
        return self._current_session_id

    def bind_targets(self, *, chat, input_widget, tool_status):
        """Swap the render targets (chat view / input / tool status).

        Used when toggling between normal and mini display modes: the same
        controller (and its live workers) keeps driving whichever widget set
        is currently visible. Call switch_session() afterwards to rebuild the
        newly-bound chat view and restore any in-flight streaming state.
        """
        self._chat = chat
        self._input = input_widget
        self._tool_status = tool_status

    def init_sessions(self):
        sessions = self._sessions.get_sessions()
        if not sessions:
            session = self._sessions.create()
            sessions = [session]
        self._session_panel.load(sessions, sessions[0].id)
        self.switch_session(sessions[0].id)
        # 恢复激活的阅读会话标记（●）；指向的会话已不存在则清空。
        active_id = cfg.get(cfg.activeReadingSessionId) or ""
        if active_id and self._sessions.get(active_id) is None:
            active_id = ""
            cfg.set(cfg.activeReadingSessionId, "")
        self._session_panel.set_active_reading(active_id)

    def new_session(self, source: str = SOURCE_MANUAL):
        """新建会话并切过去。

        source=SOURCE_READING（在「快速会话」tab 点 +）时建为快速会话并
        自动激活（●），让随后的划词连续解释接续到这个带主题铺垫的会话。

        若当前 tab 下已存在一个空白会话（无消息、默认标题），则直接切过去，
        不再重复新建——避免点 + 攒出一堆空会话。
        """
        existing = self._find_blank_session(source)
        if existing is not None:
            sessions = self._sessions.get_sessions()
            self._session_panel.load(sessions, existing.id)
            self.switch_session(existing.id)
            if source == SOURCE_READING:
                self.set_active_reading(existing.id)
            return

        if source == SOURCE_READING:
            session = self._sessions.create(
                title=reading_session_title(), source=SOURCE_READING
            )
        else:
            session = self._sessions.create()
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, session.id)
        self.switch_session(session.id)
        if source == SOURCE_READING:
            self.set_active_reading(session.id)

    def _find_blank_session(self, source: str):
        """返回该来源下首个空白会话（无消息且仍是默认标题），没有则 None。

        reading 来源用快速会话默认标题，manual 用普通默认标题；标题被改过
        或已有消息都视为非空白，不复用。默认标题判断兼容任何语言写入的旧数据。
        """
        is_default = (
            is_reading_session_title if source == SOURCE_READING
            else is_default_session_title
        )
        for s in self._sessions.get_sessions():
            if s.source != source:
                continue
            if not s.messages and is_default(s.title):
                return s
        return None

    def start_vision_session(self, attachments: list, vision_action):
        """识图：为每次截图动作新建一个会话并切过去，附上图片。

        有预设提示词的动作（解释/翻译/解题/转表格）直接连图带词发出去；
        通用「问AI」预设为空，只把图挂上、光标停在输入框等用户输入。
        """
        session = self._sessions.create(title=vision_action.session_title)
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, session.id)
        self.switch_session(session.id)

        self._input.add_pending_attachments(attachments)

        if vision_action.auto_send:
            self.submit(vision_action.prompt)
        else:
            self._input.set_text(vision_action.prompt)
            self._input.focus()

    def start_text_session(self, text: str, text_action, *, prefill_reply: str = ""):
        """划词：为一段选中文字新建会话并切过去，按动作处理。

        与识图（start_vision_session）平行：那边挂图片附件，这边把选中文字
        填入 prompt。解释/翻译等动作直接发出去，结果显示在浮窗聊天区。
        「存便签」等无 prompt 的本地动作不应走到这里，由调用方按 key 分发。

        - prefill_reply 为空：直接发出查询，等 LLM 回复。
        - prefill_reply 非空：注入气泡里已得到的问答，不重复请求 LLM。
        """
        session = self._sessions.create(title=text_action.session_title)
        sessions = self._sessions.get_sessions()
        self._session_panel.load(sessions, session.id)
        self.switch_session(session.id)

        if prefill_reply:
            self.inject_exchange(text_action.render(text), prefill_reply)
        else:
            self.submit(text_action.render(text))

    def inject_exchange(self, user_text: str, assistant_text: str):
        """注入一对已完成的问答到当前会话（不触发 LLM）。

        用于气泡「在小窗继续」：把气泡里已经得到的问答原样搬进小窗会话，
        用户可直接追问，无需重复请求 LLM。
        """
        sid = self._current_session_id
        if not sid:
            return

        user_msg = Message(role=MessageRole.USER, content=user_text)
        self._sessions.add_message(sid, user_msg)
        self._chat.add_message(user_msg)

        ai_msg = Message(role=MessageRole.ASSISTANT, content=assistant_text)
        self._sessions.add_message(sid, ai_msg)
        self._chat.add_message(ai_msg)

        session = self._sessions.get(sid)
        if session is not None:
            self._session_panel.update_title(sid, session.title)
        self._input.focus()

    def delete_session(self, sid: str):
        """删除会话 = 归档（软删除）：移出列表但保留数据，可在设置中恢复。"""
        deleted = self._sessions.get(sid)
        deleted_source = deleted.source if deleted is not None else None

        # 删掉的若是激活中的阅读会话，清空激活指针。
        if cfg.get(cfg.activeReadingSessionId) == sid:
            self.set_active_reading("")

        self._sessions.archive(sid)
        sessions = self._sessions.get_sessions()
        if not sessions:
            session = self._sessions.create()
            sessions = [session]

        # 优先选与被删会话同来源的会话，避免删除后跳到另一个 Tab
        target = next(
            (s for s in sessions if s.source == deleted_source),
            sessions[0],
        )
        self._session_panel.load(sessions, target.id)
        self.switch_session(target.id)

    def refresh_panel(self):
        """重载会话列表，保持当前选中。

        归档管理（恢复 / 彻底删除）在设置页操作后调用，让主窗列表同步。
        若当前会话恰好被彻底删除，则切到列表首个会话。
        """
        sessions = self._sessions.get_sessions()
        if not sessions:
            sessions = [self._sessions.create()]
        ids = {s.id for s in sessions}
        target = self._current_session_id if self._current_session_id in ids \
            else sessions[0].id
        self._session_panel.load(sessions, target)
        if target != self._current_session_id:
            self.switch_session(target)

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
        # 附件统一交给输入框的待发预览条管理（单一来源）。
        self._input.add_pending_attachments(attachments)

    def submit(self, text: str):
        sid = self._current_session_id
        if not sid:
            return
        if sid in self._workers:
            return

        attachments = self._input.take_pending_attachments()
        user_msg = Message(
            role=MessageRole.USER,
            content=text,
            attachments=attachments,
        )

        self._sessions.add_message(sid, user_msg)
        self._chat.add_message(user_msg)
        self._session_panel.update_title(sid, self._sessions.get(sid).title)

        ai_msg = Message(role=MessageRole.ASSISTANT, content="")
        self._sessions.add_message(sid, ai_msg)

        self._session_live[sid] = {
            "ai_msg": ai_msg,
            "ai_text": "",
            "first_chunk_sent": False,
        }
        self._current_ai_msg = ai_msg
        self._current_ai_bubble = None
        self._current_ai_text = ""
        self._input.set_running(True)
        self._tool_status.hide()
        self._chat.start_typing()

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
            trace_store=self._trace_store,
            hooks=self._build_hooks(),
        )
        self._workers[sid] = worker
        self._connect_worker(sid, worker)
        worker.start()

    def _build_hooks(self) -> list:
        """构建本次 turn 的生命周期 hook（安全审计 + 评测埋点）。

        trace_store 为 None（遥测禁用）时不挂任何 hook，省去无意义开销。
        安全 hook 默认只审计不拦截；后续若要按工具开关拦截，传 blocked_tools。
        """
        if self._trace_store is None:
            return []
        return [
            SecurityAuditHook(self._trace_store),
            EvalHook(self._trace_store),
        ]

    # ── 划词「续入/新建会话」：填入快速会话输入框，等用户手动发 ──────────────
    def compose_in_reading(self, text: str, *, force_new: bool) -> str:
        """续入/新建：切到（激活或新建的）快速会话，把选中文填进输入框。

        不预设提示词、不自动发送——用户在输入框补充指令后自己点发送，走正常
        submit。force_new=True 或无激活会话时新建并激活快速会话，否则接续激活会话。

        返回归入的快速会话 id。
        """
        sid = self._resolve_reading_session(force_new)
        self._session_panel.load(self._sessions.get_sessions(), sid)
        self.switch_session(sid)
        # 把选中文原样填进输入框，光标置末尾、聚焦，等用户补指令。
        self._input.set_text(text)
        return sid

    def _resolve_reading_session(self, force_new: bool) -> str:
        """返回续入/新建要写入的快速会话 id：接续激活会话或新建并激活。"""
        if not force_new:
            active_id = cfg.get(cfg.activeReadingSessionId) or ""
            if active_id and self._sessions.get(active_id) is not None:
                return active_id
        session = self._sessions.create(
            title=reading_session_title(), source=SOURCE_READING
        )
        self.set_active_reading(session.id)
        return session.id

    def set_active_reading(self, sid: str):
        """设为当前激活的快速会话（至多一个）；刷新列表的激活标记。"""
        cfg.set(cfg.activeReadingSessionId, sid)
        self._session_panel.set_active_reading(sid)

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
            # 工具执行期间保持亮条转动——执行本身就是「任务进行中」，
            # 不要 stop_typing，否则长耗时工具（如 websearch）期间界面没有
            # 任何动画反馈，看起来像卡死/失败。
            self._chat.start_typing()
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
        marker = _cancelled_marker()
        if text.endswith(marker):
            return text
        if text:
            return f"{text}\n\n{marker}"
        return marker

    def _release_cancelled_worker(self, worker: AgentLoop):
        try:
            self._cancelled_workers.remove(worker)
        except ValueError:
            pass

    def _format_error(self, error_msg: str | None) -> str:
        hint = ""
        if error_msg and "404" in error_msg:
            hint = t("chat.error.hint404", model=cfg.get(cfg.litellmDefaultModel))
        elif error_msg and ("401" in error_msg or "Unauthorized" in error_msg):
            hint = t("chat.error.hint401")
        return t("chat.error.requestFailed", error=error_msg, hint=hint)
