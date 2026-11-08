"""划词结果气泡 — 就地显示 LLM 快查结果的轻量浮窗。

在选区附近弹出，流式显示解释/翻译结果。不创建会话、不走完整 prompt 体系。
用户看完即走（零痕迹），或点击图标按钮转入主窗继续对话。

气泡尺寸随回复内容自适应增大：宽度按最宽一行自然宽度增长（单调不回缩，
避免流式过程中左右抖动），高度按换行后实际行数增长，两者都受最大值约束，
超出则在气泡内滚动。

视觉风格跟随应用主题，定位逻辑复用 TextActionPopup 同款策略。
焦点策略与 TextActionPopup 一致：WS_EX_NOACTIVATE，不抢焦点。
"""
from __future__ import annotations

import logging
import threading
import time
import uuid

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QTextEdit,
    QVBoxLayout,
)
from qfluentwidgets import TransparentToolButton, FluentIcon

from app.core.config import cfg
from app.core.llm_gateway import CancellationToken, LLMGateway
from app.i18n import t
from app.ui import style
from app.ui.global_click_watcher import GlobalClickWatcher
from app.ui.non_activating_popup import NonActivatingPopup
from app.ui.popup_geometry import GAP_PX as _GAP_PX
from app.ui.popup_geometry import place_below_anchor
from app.ui.text_actions import get_text_action

logger = logging.getLogger(__name__)

# 布局参数：气泡宽高自适应内容，但限制上下界。
_BUBBLE_MIN_WIDTH = 240
_BUBBLE_MAX_WIDTH = 420
_BUBBLE_MIN_HEIGHT = 80
_BUBBLE_MAX_HEIGHT = 420
_H_MARGIN = 16   # 内容区左右内边距之和（8 + 8）
_V_CHROME = 44   # 上下内边距 + footer 工具栏高度的预留
_PROMPT_STREAM_TIMEOUT_SECONDS = 30


def _run_prompt_stream(
    gateway, prompt, cancel_token, emit_text, emit_done, emit_error,
    *, request_id, action_key, request_started, prompt_prepare_ms,
):
    """Send a standalone user prompt through the LLM gateway and forward events."""
    try:
        messages = [{"role": "user", "content": prompt}]
        completed = False
        worker_started = time.perf_counter()
        gateway_started = None
        first_token_at = None
        ui_dispatch_started = None
        logger.info(
            "[SelectionTiming] request_id=%s stage=request_ready action=%s "
            "prompt_chars=%d messages=1 system_messages=0 tools=0 prompt_prepare_ms=%.2f",
            request_id,
            action_key,
            len(prompt),
            prompt_prepare_ms,
        )
        logger.info(
            "[SelectionTiming] request_id=%s stage=worker_started elapsed_ms=%.2f",
            request_id,
            (worker_started - request_started) * 1000,
        )
        gateway_started = time.perf_counter()
        for event in gateway.chat_stream(
            messages,
            tools=None,
            cancel_token=cancel_token,
            trace_id=request_id,
            stream_timeout=_PROMPT_STREAM_TIMEOUT_SECONDS,
        ):
            if cancel_token.is_cancelled():
                return
            if event.get("type") == "text":
                token_at = time.perf_counter()
                if first_token_at is None:
                    first_token_at = token_at
                    logger.info(
                        "[SelectionTiming] request_id=%s stage=first_token gateway_ttft_ms=%.2f",
                        request_id,
                        (first_token_at - gateway_started) * 1000,
                    )
                ui_dispatch_started = token_at
                emit_text(event.get("delta", ""), token_at)
            elif event.get("type") == "error":
                failed_at = time.perf_counter()
                logger.warning(
                    "[SelectionTiming] request_id=%s stage=gateway_error elapsed_ms=%.2f "
                    "gateway_ms=%.2f error=%s",
                    request_id,
                    (failed_at - request_started) * 1000,
                    (failed_at - gateway_started) * 1000,
                    event.get("error_kind") or event.get("message", "unknown"),
                )
                emit_error(event.get("message", t("resultbubble.requestFailed")))
                return
            elif event.get("type") == "done":
                completed = True
        gateway_finished = time.perf_counter()
        if not completed and not cancel_token.is_cancelled():
            logger.warning(
                "[SelectionTiming] request_id=%s stage=incomplete_stream elapsed_ms=%.2f "
                "gateway_ms=%.2f ttft_ms=%s",
                request_id,
                (gateway_finished - request_started) * 1000,
                (gateway_finished - gateway_started) * 1000,
                "none" if first_token_at is None else f"{(first_token_at - gateway_started) * 1000:.2f}",
            )
            emit_error(t("resultbubble.timeout"))
            return
        if not cancel_token.is_cancelled():
            completion_emitted = time.perf_counter()
            logger.info(
                "[SelectionTiming] request_id=%s stage=gateway_done gateway_ms=%.2f "
                "ttft_ms=%s generation_after_first_ms=%s",
                request_id,
                (gateway_finished - gateway_started) * 1000,
                "none" if first_token_at is None else f"{(first_token_at - gateway_started) * 1000:.2f}",
                "none" if first_token_at is None else f"{(gateway_finished - first_token_at) * 1000:.2f}",
            )
            emit_done(request_id, completion_emitted, ui_dispatch_started)
    except Exception as exc:
        if not cancel_token.is_cancelled():
            logger.exception(
                "[SelectionTiming] request_id=%s stage=worker_error elapsed_ms=%.2f",
                request_id,
                (time.perf_counter() - request_started) * 1000,
            )
            emit_error(str(exc))


class ResultBubble(NonActivatingPopup):
    """划词结果气泡：就地流式显示 LLM 快查结果。"""

    # 信号
    _text_chunk = pyqtSignal(int, str, float)
    _stream_done = pyqtSignal(int, float, float)
    _stream_error = pyqtSignal(int, str)
    _hide_requested = pyqtSignal()  # 全球点击监听
    replace_requested = pyqtSignal(str)  # rewrite：用户点「替换原文」，载荷为最终结果
    copy_requested = pyqtSignal(str)     # rewrite：用户点「复制」，载荷为最终结果
    edit_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_geo: QRect | None = None
        self._cached_geo_physical: QRect | None = None
        self._click_watcher = GlobalClickWatcher(
            geometry_provider=lambda: self._cached_geo_physical,
            on_hide_requested=self._hide_requested.emit,
            owner_name="ResultBubble",
        )
        self._bg_color = QColor("#1E1E1E")
        self._border_color = QColor("#333333")
        self._llm_gateway = LLMGateway()
        self._cancel_token: CancellationToken | None = None
        self._stream_thread: threading.Thread | None = None
        self._stream_generation = 0
        self._request_id = ""
        self._request_started = 0.0
        self._prompt_prepare_ms = 0.0
        self._streaming = False
        self._full_text = ""
        # 编辑通过单独的对话框完成，气泡自身始终不抢焦点。
        self._mode = "oneshot"
        # rewrite 模式下记下的原始选中文字（回填时校验选区未变）。
        self._original_text = ""
        # 锚点（选区下方的逻辑坐标）与当前自适应宽度（单调增长）
        self._anchor_x = 0
        self._anchor_y = 0
        self._content_width = _BUBBLE_MIN_WIDTH

        self._build_window()
        self._build_ui()

        # 信号连接
        self._text_chunk.connect(self._append_text)
        self._stream_done.connect(self._on_stream_done)
        self._stream_error.connect(self._on_stream_error)
        self._hide_requested.connect(self._on_hide_requested)

    # ── 窗口设置 ────────────────────────────────────────────────────────

    def _build_window(self):
        # 窗口标志与不激活属性由 NonActivatingPopup 基类设置；这里补气泡专有的
        # 自绘背景属性与尺寸约束。
        self.setObjectName("resultBubble")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setMinimumWidth(_BUBBLE_MIN_WIDTH)
        self.setMaximumWidth(_BUBBLE_MAX_WIDTH)
        self.setMaximumHeight(_BUBBLE_MAX_HEIGHT)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 6)
        layout.setSpacing(4)

        # 内容区
        self._content = QTextEdit()
        self._content.setReadOnly(True)
        self._content.setFrameStyle(QFrame.Shape.NoFrame)
        self._content.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._content.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._content.setObjectName("bubbleContent")
        layout.addWidget(self._content)

        # 查看结果可复制；改写结果额外提供编辑和替换，流式期间禁用。
        self._footer = QFrame(self)
        self._footer.setObjectName("bubbleFooter")
        footer_row = QHBoxLayout(self._footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(2)
        footer_row.addStretch()
        self._edit_btn = TransparentToolButton(FluentIcon.EDIT, self)
        self._edit_btn.setToolTip(t("resultbubble.editTooltip"))
        self._edit_btn.clicked.connect(
            lambda: self.edit_requested.emit(self._content.toPlainText())
        )
        footer_row.addWidget(self._edit_btn)
        self._copy_btn = TransparentToolButton(FluentIcon.COPY, self)
        self._copy_btn.setToolTip(t("resultbubble.copyTooltip"))
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        footer_row.addWidget(self._copy_btn)
        self._replace_btn = TransparentToolButton(FluentIcon.PASTE, self)
        self._replace_btn.setToolTip(t("resultbubble.replaceTooltip"))
        self._replace_btn.clicked.connect(self._on_replace_clicked)
        footer_row.addWidget(self._replace_btn)
        self._footer.show()
        layout.addWidget(self._footer)

    # ── 主题适配 ────────────────────────────────────────────────────────

    def _apply_theme_style(self):
        """根据当前主题动态生成气泡样式。"""
        theme_name = cfg.get(cfg.theme)
        theme = style.get_theme(theme_name)

        bg = theme["surface_solid"]
        border_color = theme["border_solid"]
        text_color = theme["text"]

        # 背景/边框由 paintEvent 显式绘制（QSS 背景在 WA_TranslucentBackground
        # 下不稳定，会透出桌面）。这里只缓存颜色给 paintEvent。
        self._bg_color = QColor(bg)
        self._border_color = QColor(border_color)

        qss = f"""
            #bubbleContent {{
                background: transparent;
                color: {text_color};
                font-size: 13px;
                border: none;
            }}
            #bubbleFooter {{
                background: transparent;
                border: none;
            }}
            #bubbleFooter TransparentToolButton {{
                color: {text_color};
            }}
            #bubbleFooter TransparentToolButton:hover {{
                background: {theme["accent_subtle"]};
                color: {theme["accent"]};
            }}
        """
        self.setStyleSheet(qss)

        # 设置内容字体
        font = QFont()
        font.setPointSize(10)
        self._content.setFont(font)

    def paintEvent(self, event):
        """显式绘制不透明的圆角背景 + 边框。

        WA_TranslucentBackground 让未绘制区域透明（圆角外），但背景本身必须
        在这里实绘，否则整块透出桌面（QSS #id 背景在该属性下不可靠）。
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, 8, 8)
        painter.fillPath(path, self._bg_color)
        painter.setPen(self._border_color)
        painter.drawPath(path)
        super().paintEvent(event)

    # ── 公开 API ────────────────────────────────────────────────────────

    def show_oneshot(self, x: int, y: int, text: str, action_key: str):
        """弹气泡、自行发起请求、流式显示，不落库，完成后可复制。

        Args:
            x: 选区水平中心（逻辑像素）。
            y: 选区底边（逻辑像素）。
            text: 选中的文字。
            action_key: 动作标识（如 "explain"）。
        """
        self._mode = "oneshot"
        self._original_text = ""
        self._footer.show()
        self._edit_btn.hide()
        self._replace_btn.hide()
        self._copy_btn.setEnabled(False)
        self._start_stream(x, y, text, action_key)

    def show_rewrite(self, x: int, y: int, text: str, action_key: str):
        """改写回填：弹气泡流式显示 AI 改写结果，底部带回填 footer。

        与 show_oneshot 共用流式机制，差异：显示 footer[复制 / 替换原文]、
        记下原始选中文字供回填时校验选区未变。

        内容区保持只读以保住源应用焦点；编辑按钮通过控制器打开独立编辑框，
        返回后重新校验源窗口与选区，再允许替换。

        Args:
            x: 选区水平中心（逻辑像素）。
            y: 选区底边（逻辑像素）。
            text: 选中的原始文字（回填校验用）。
            action_key: 改写动作标识（polish / translate_inplace / fix_grammar）。
        """
        self._mode = "rewrite"
        self._original_text = text
        self._footer.show()
        self._edit_btn.show()
        self._replace_btn.show()
        # 流式期间禁用回填按钮，完成后在 _on_stream_done 启用。
        self._replace_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._edit_btn.setEnabled(False)
        self._start_stream(x, y, text, action_key)

    def show_rewrite_result(self, x: int, y: int, original: str, result: str):
        """Redisplay a locally edited result without making another AI request."""
        self._cancel_current()
        self._mode = "rewrite"
        self._original_text = original
        self._full_text = result
        self._content.setPlainText(result)
        self._footer.show()
        self._edit_btn.show()
        self._replace_btn.show()
        for button in (self._edit_btn, self._copy_btn, self._replace_btn):
            button.setEnabled(bool(result.strip()))
        self._apply_theme_style()
        self._position_at(x, y)
        self._adjust_size()
        self.show()
        self.raise_()

    def _start_stream(self, x: int, y: int, text: str, action_key: str):
        """Reset the bubble and stream one user-only prompt in a worker thread."""
        self._cancel_current()
        generation = self._stream_generation
        self._request_id = uuid.uuid4().hex[:12]
        self._request_started = time.perf_counter()
        # 起始：清空内容、复位宽度、定位、显示。
        self._full_text = ""
        self._streaming = True
        self._content.clear()
        self._content.setPlaceholderText("···")
        self._content_width = _BUBBLE_MIN_WIDTH
        self._apply_theme_style()
        self._position_at(x, y)
        self.show()
        self.raise_()

        # 气泡用 action.render(text)，与对应动作共用同一份（含自定义）提示词。
        action = get_text_action(action_key)
        if action is None or not action.goes_to_ai:
            self._content.setPlainText(t("resultbubble.unsupportedAction"))
            self._streaming = False
            return
        prompt_started = time.perf_counter()
        prompt = action.render(text)
        self._prompt_prepare_ms = (time.perf_counter() - prompt_started) * 1000
        logger.info(
            "[SelectionTiming] request_id=%s stage=prompt_prepared action=%s "
            "selection_chars=%d elapsed_ms=%.2f system_prompt=none history=none",
            self._request_id,
            action_key,
            len(text),
            self._prompt_prepare_ms,
        )
        cancel_token = CancellationToken()
        self._cancel_token = cancel_token
        self._stream_thread = threading.Thread(
            target=_run_prompt_stream,
            args=(
                self._llm_gateway,
                prompt,
                cancel_token,
                lambda delta, emitted_at: self._text_chunk.emit(
                    generation, delta, emitted_at
                ),
                lambda request_id, finished_at, last_ui_at: self._stream_done.emit(
                    generation, finished_at, last_ui_at or finished_at
                ),
                lambda message: self._stream_error.emit(generation, message),
            ),
            kwargs={
                "request_id": self._request_id,
                "action_key": action_key,
                "request_started": self._request_started,
                "prompt_prepare_ms": self._prompt_prepare_ms,
            },
            name="selection-prompt-stream",
            daemon=True,
        )
        self._stream_thread.start()

    def _on_copy_clicked(self):
        self.copy_requested.emit(self._content.toPlainText().strip())

    def _on_replace_clicked(self):
        self.replace_requested.emit(self._content.toPlainText().strip())

    # ── 定位 ────────────────────────────────────────────────────────────

    def _position_at(self, x: int, y: int):
        """记下锚点（选区下方）并按初始尺寸定位。

        锚点是选区水平中心 / 底边的逻辑坐标，后续随内容增大时由
        _reposition() 复用它重新摆放气泡（始终相对同一锚点对齐）。
        """
        self._anchor_x = x
        self._anchor_y = y
        self.setFixedWidth(self._content_width)
        self.setFixedHeight(_BUBBLE_MIN_HEIGHT)
        self._reposition()

    def _reposition(self):
        """按当前宽高与锚点重新摆放气泡，并做屏幕边缘修正。

        水平居中对齐锚点 x；默认置于锚点 y 下方，底部空间不足则翻到上方；
        左右越界则贴边。同步刷新供 mouse hook 比对的物理像素几何（缩放屏上
        点击气泡内部也能正确判定为「内部」，不误关）。
        """
        w, h = self.width(), self.height()
        screen = QApplication.screenAt(QPoint(self._anchor_x, self._anchor_y + _GAP_PX)) \
            or QApplication.primaryScreen()
        screen_geo = screen.availableGeometry() if screen is not None else None
        scale = screen.devicePixelRatio() if screen is not None else 1.0

        placed = place_below_anchor(
            w, h, self._anchor_x, self._anchor_y, screen_geo, scale
        )
        self._cached_geo = placed.logical
        self._cached_geo_physical = placed.physical
        self.move(placed.logical.x(), placed.logical.y())

    # ── 流式文本处理 ────────────────────────────────────────────────────

    def _append_text(self, generation: int, delta: str, emitted_at: float):
        if generation != self._stream_generation:
            return
        dispatch_ms = (time.perf_counter() - emitted_at) * 1000
        if self._full_text == "":
            logger.info(
                "[SelectionTiming] request_id=%s stage=first_ui_chunk dispatch_ms=%.2f",
                self._request_id,
                dispatch_ms,
            )
        self._full_text += delta
        self._content.setPlainText(self._full_text)
        # 滚动到底部
        cursor = self._content.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._content.setTextCursor(cursor)
        # 动态调整宽高
        self._adjust_size()

    def _natural_width(self) -> int:
        """内容中最宽一行的像素宽度（不换行的自然宽度）。"""
        fm = self._content.fontMetrics()
        longest = 0
        for line in self._full_text.split("\n"):
            adv = fm.horizontalAdvance(line)
            if adv > longest:
                longest = adv
        return longest

    def _adjust_size(self):
        """随内容自适应气泡宽高，受最大值约束，超出则内部滚动。

        宽度单调增长（只增不减），避免流式逐字到达时左右边界来回抖动。
        高度按当前宽度下的换行结果计算。任一尺寸变化都重新定位。
        """
        # 宽度：按最宽行自然宽度增长，clamp 到 [min, max]，且不回缩
        target_w = self._natural_width() + _H_MARGIN + 4
        target_w = max(_BUBBLE_MIN_WIDTH, min(target_w, _BUBBLE_MAX_WIDTH))
        target_w = max(target_w, self._content_width)
        self._content_width = target_w
        if self.width() != target_w:
            self.setFixedWidth(target_w)

        # 高度：在当前宽度下测量文档实际高度，clamp 到 [min, max]
        doc_height = self._content.document().size().height()
        target_h = int(doc_height) + _V_CHROME
        target_h = max(_BUBBLE_MIN_HEIGHT, min(target_h, _BUBBLE_MAX_HEIGHT))
        if self.height() != target_h:
            self.setFixedHeight(target_h)

        self._reposition()

    def _on_stream_done(self, generation: int, finished_at: float, last_ui_at: float):
        if generation != self._stream_generation:
            return
        ui_finished_at = time.perf_counter()
        logger.info(
            "[SelectionTiming] request_id=%s stage=ui_done total_ms=%.2f "
            "ui_finalize_ms=%.2f ui_after_last_chunk_ms=%.2f result_chars=%d",
            self._request_id,
            (ui_finished_at - self._request_started) * 1000,
            (ui_finished_at - finished_at) * 1000,
            (ui_finished_at - last_ui_at) * 1000,
            len(self._full_text),
        )
        self._streaming = False
        self._cancel_token = None
        self._stream_thread = None
        self._content.setPlaceholderText("")
        if self._mode == "rewrite":
            # 改写完成：剥离常见前缀/代码块包裹后回填进编辑区，启用回填按钮。
            from app.core.selection_inject import strip_ai_preamble
            cleaned = strip_ai_preamble(self._full_text)
            if cleaned and cleaned != self._full_text:
                self._full_text = cleaned
                self._content.setPlainText(cleaned)
            has_text = bool(self._content.toPlainText().strip())
            self._replace_btn.setEnabled(has_text)
            self._edit_btn.setEnabled(has_text)
        self._copy_btn.setEnabled(bool(self._content.toPlainText().strip()))

    def _on_stream_error(self, generation: int, msg: str):
        if generation != self._stream_generation:
            return
        self._streaming = False
        logger.warning(
            "[SelectionTiming] request_id=%s stage=ui_error total_ms=%.2f "
            "result_chars=%d",
            self._request_id,
            (time.perf_counter() - self._request_started) * 1000,
            len(self._full_text),
        )
        self._cancel_token = None
        self._stream_thread = None
        if not self._full_text:
            self._content.setPlainText(t("resultbubble.error", msg=msg))

    # ── 取消 / 清理 ────────────────────────────────────────────────────

    def _cancel_current(self):
        self._stream_generation += 1
        if self._cancel_token is not None:
            self._cancel_token.cancel()
            self._cancel_token = None
        self._stream_thread = None
        self._streaming = False

    def hideEvent(self, event):
        super().hideEvent(event)
        self._cancel_current()
        self._click_watcher.remove()

    # ── 显示：不激活样式由基类处理，这里挂全局点击监听 ──────────────────

    def showEvent(self, event):
        super().showEvent(event)  # NonActivatingPopup 负责 WS_EX_NOACTIVATE
        self._click_watcher.install()

    def _on_hide_requested(self):
        self.hide()
