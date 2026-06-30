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


class _BubbleWorker(threading.Thread):
    """后台线程：调用 LLMGateway 流式获取结果。"""

    def __init__(
        self,
        messages: list[dict],
        cancel_token: CancellationToken,
        on_chunk: callable,
        on_done: callable,
        on_error: callable,
    ):
        super().__init__(daemon=True)
        self._messages = messages
        self._cancel = cancel_token
        self._on_chunk = on_chunk
        self._on_done = on_done
        self._on_error = on_error

    def run(self):
        try:
            gateway = LLMGateway()
            for event in gateway.chat_stream(
                self._messages, tools=None, cancel_token=self._cancel
            ):
                if self._cancel.is_cancelled():
                    break
                if event["type"] == "text":
                    self._on_chunk(event["delta"])
                elif event["type"] == "error":
                    self._on_error(event.get("message", t("resultbubble.requestFailed")))
                    return
                elif event["type"] == "done":
                    break
            self._on_done()
        except Exception as e:
            if not self._cancel.is_cancelled():
                self._on_error(str(e))


class ResultBubble(NonActivatingPopup):
    """划词结果气泡：就地流式显示 LLM 快查结果。"""

    # 信号
    _text_chunk = pyqtSignal(str)   # 从 worker 线程 marshal 到主线程
    _stream_done = pyqtSignal()
    _stream_error = pyqtSignal(str)
    _hide_requested = pyqtSignal()  # 全局点击监听
    replace_requested = pyqtSignal(str)  # rewrite：用户点「替换原文」，载荷为最终结果
    copy_requested = pyqtSignal(str)     # rewrite：用户点「复制」，载荷为最终结果

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
        self._cancel_token: CancellationToken | None = None
        self._worker: _BubbleWorker | None = None
        self._streaming = False
        self._full_text = ""
        # 当前模式："oneshot"（只读快查）或 "rewrite"（可编辑 + footer 回填）。
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

        # Footer：仅 rewrite 模式显示。替换原文 / 复制。流式期间禁用，完成后启用。
        self._footer = QFrame(self)
        self._footer.setObjectName("bubbleFooter")
        footer_row = QHBoxLayout(self._footer)
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer_row.setSpacing(2)
        footer_row.addStretch()
        self._copy_btn = TransparentToolButton(FluentIcon.COPY, self)
        self._copy_btn.setToolTip(t("resultbubble.copyTooltip"))
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        footer_row.addWidget(self._copy_btn)
        self._replace_btn = TransparentToolButton(FluentIcon.PASTE, self)
        self._replace_btn.setToolTip(t("resultbubble.replaceTooltip"))
        self._replace_btn.clicked.connect(self._on_replace_clicked)
        footer_row.addWidget(self._replace_btn)
        self._footer.hide()
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
        """一次性解释：弹气泡、自行发起请求、流式显示，不落库、无按钮。

        Args:
            x: 选区水平中心（逻辑像素）。
            y: 选区底边（逻辑像素）。
            text: 选中的文字。
            action_key: 动作标识（如 "explain"）。
        """
        self._mode = "oneshot"
        self._original_text = ""
        self._footer.hide()
        self._start_stream(x, y, text, action_key)

    def show_rewrite(self, x: int, y: int, text: str, action_key: str):
        """改写回填：弹气泡流式显示 AI 改写结果，底部带回填 footer。

        与 show_oneshot 共用流式机制，差异：显示 footer[复制 / 替换原文]、
        记下原始选中文字供回填时校验选区未变。

        内容区**保持只读**：气泡是 WS_EX_NOACTIVATE 永不抢焦点（这正是 Ctrl+V
        能落回源应用的前提），故无法接收键盘输入，不能就地编辑。需要微调改写
        结果时走「续入会话」。

        Args:
            x: 选区水平中心（逻辑像素）。
            y: 选区底边（逻辑像素）。
            text: 选中的原始文字（回填校验用）。
            action_key: 改写动作标识（polish / translate_inplace / fix_grammar）。
        """
        self._mode = "rewrite"
        self._original_text = text
        self._footer.show()
        # 流式期间禁用回填按钮，完成后在 _on_stream_done 启用。
        self._replace_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._start_stream(x, y, text, action_key)

    def _start_stream(self, x: int, y: int, text: str, action_key: str):
        """共用的流式启动：复位状态、定位显示、渲染提示词、起 worker。"""
        self._cancel_current()
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
        prompt = action.render(text)

        messages = [{"role": "user", "content": prompt}]
        self._cancel_token = CancellationToken()
        self._worker = _BubbleWorker(
            messages=messages,
            cancel_token=self._cancel_token,
            on_chunk=lambda delta: self._text_chunk.emit(delta),
            on_done=lambda: self._stream_done.emit(),
            on_error=lambda msg: self._stream_error.emit(msg),
        )
        self._worker.start()

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

    def _append_text(self, delta: str):
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

    def _on_stream_done(self):
        self._streaming = False
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
            self._copy_btn.setEnabled(has_text)

    def _on_stream_error(self, msg: str):
        self._streaming = False
        if not self._full_text:
            self._content.setPlainText(t("resultbubble.error", msg=msg))

    # ── 取消 / 清理 ────────────────────────────────────────────────────

    def _cancel_current(self):
        if self._cancel_token is not None:
            self._cancel_token.cancel()
            self._cancel_token = None
        self._worker = None
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
