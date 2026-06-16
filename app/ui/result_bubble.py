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
import sys
import threading

from PyQt6.QtCore import QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from app.core.config import cfg
from app.core.llm_gateway import CancellationToken, LLMGateway
from app.ui import style

logger = logging.getLogger(__name__)

try:
    import mouse as _mouse

    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False

# Win32 常量
_GWL_EXSTYLE = -20
_WS_EX_NOACTIVATE = 0x08000000

# 布局参数：气泡宽高自适应内容，但限制上下界。
_BUBBLE_MIN_WIDTH = 240
_BUBBLE_MAX_WIDTH = 420
_BUBBLE_MIN_HEIGHT = 80
_BUBBLE_MAX_HEIGHT = 420
_H_MARGIN = 16   # 内容区左右内边距之和（8 + 8）
_V_CHROME = 44   # 上下内边距 + footer 工具栏高度的预留
_GAP_PX = 4


def _build_prompt(action_key: str, text: str) -> str:
    """构造气泡专用精简提示词（不含系统提示、记忆、工具描述）。

    翻译目标语言取自配置 selectionTranslateTarget。
    """
    if action_key == "explain":
        return f"请用简洁的语言解释下面这段文字的含义，简要回答：\n\n{text}"
    if action_key == "translate":
        target = cfg.get(cfg.selectionTranslateTarget) or "中文"
        return f"请将下面这段文字翻译成{target}，简要回答，只输出译文：\n\n{text}"
    return ""


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
                    self._on_error(event.get("message", "LLM 请求失败"))
                    return
                elif event["type"] == "done":
                    break
            self._on_done()
        except Exception as e:
            if not self._cancel.is_cancelled():
                self._on_error(str(e))


class ResultBubble(QFrame):
    """划词结果气泡：就地流式显示 LLM 快查结果。"""

    # 信号
    _text_chunk = pyqtSignal(str)   # 从 worker 线程 marshal 到主线程
    _stream_done = pyqtSignal()
    _stream_error = pyqtSignal(str)
    _hide_requested = pyqtSignal()  # 全局点击监听

    # 请求转入主窗划词速记会话，携带 (selected_text, llm_reply, action_key, force_new)
    # force_new=False 复用最近的划词速记会话，True 强制新建。
    continue_in_main = pyqtSignal(str, str, str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_geo: QRect | None = None
        self._cached_geo_physical: QRect | None = None
        self._mouse_hook = None
        self._bg_color = QColor("#1E1E1E")
        self._border_color = QColor("#333333")
        self._cancel_token: CancellationToken | None = None
        self._worker: _BubbleWorker | None = None
        self._streaming = False
        self._full_text = ""
        self._source_text = ""
        self._action_key = ""
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
        self.setObjectName("resultBubble")
        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
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

        # 底部工具栏
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 2, 0, 0)
        footer.setSpacing(4)
        footer.addStretch()

        # "在主窗继续"按钮（复用最近的划词速记会话）
        self._main_btn = QPushButton("⤢")  # ⤢ 放大
        self._main_btn.setToolTip("在主窗口继续（划词速记）")
        self._main_btn.setObjectName("bubbleMainBtn")
        self._main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._main_btn.setFixedSize(24, 24)
        self._main_btn.clicked.connect(self._on_continue_main)
        footer.addWidget(self._main_btn)

        # "在主窗新建会话"按钮（强制开一个新的划词速记会话）
        self._new_btn = QPushButton("＋")  # ＋ 新建
        self._new_btn.setToolTip("在主窗口新建会话")
        self._new_btn.setObjectName("bubbleNewBtn")
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.setFixedSize(24, 24)
        self._new_btn.clicked.connect(self._on_continue_main_new)
        footer.addWidget(self._new_btn)

        layout.addLayout(footer)

    # ── 主题适配 ────────────────────────────────────────────────────────

    def _apply_theme_style(self):
        """根据当前主题动态生成气泡样式。"""
        theme_name = cfg.get(cfg.theme)
        theme = style.get_theme(theme_name)

        bg = theme["surface_solid"]
        border_color = theme["border_solid"]
        text_color = theme["text"]
        text_secondary = theme["text_secondary"]
        accent = theme["accent"]
        surface_raised = theme["surface_raised"]

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
            #bubbleMainBtn {{
                background: transparent;
                border: none;
                color: {text_secondary};
                font-size: 14px;
                border-radius: 4px;
            }}
            #bubbleMainBtn:hover {{
                background: {surface_raised};
                color: {accent};
            }}
            #bubbleMainBtn:disabled {{
                background: transparent;
                color: {border_color};
            }}
            #bubbleNewBtn {{
                background: transparent;
                border: none;
                color: {text_secondary};
                font-size: 16px;
                border-radius: 4px;
            }}
            #bubbleNewBtn:hover {{
                background: {surface_raised};
                color: {accent};
            }}
            #bubbleNewBtn:disabled {{
                background: transparent;
                color: {border_color};
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

    def show_result(self, x: int, y: int, text: str, action_key: str):
        """在指定位置弹出气泡并开始流式获取 LLM 结果。

        Args:
            x: 选区水平中心（逻辑像素）。
            y: 选区底边（逻辑像素）。
            text: 选中的文字。
            action_key: 动作标识（"explain" / "translate"）。
        """
        # 取消上一次未完成的请求
        self._cancel_current()

        self._source_text = text
        self._action_key = action_key
        self._full_text = ""
        self._streaming = True
        self._content.clear()
        self._content.setPlaceholderText("···")  # ···
        # 重置自适应宽度起点（每次新查询从最小宽度开始单调增长）
        self._content_width = _BUBBLE_MIN_WIDTH
        # 流式期间禁用「转主窗」按钮，避免搬运半截回复；结束后再启用。
        self._set_actions_enabled(False)

        self._apply_theme_style()
        self._position_at(x, y)
        self.show()
        self.raise_()

        # 启动 LLM 请求
        prompt = _build_prompt(action_key, text)
        if not prompt:
            self._content.setPlainText("不支持的动作")
            self._streaming = False
            return

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
        左右越界则贴边。同步刷新供 mouse hook 比对的物理像素几何。
        """
        w, h = self.width(), self.height()
        px = self._anchor_x - w // 2
        py = self._anchor_y + _GAP_PX

        screen = QApplication.screenAt(QPoint(px + w // 2, py)) \
            or QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            if px + w > geo.right():
                px = geo.right() - w
            if px < geo.left():
                px = geo.left()
            if py + h > geo.bottom():
                py = self._anchor_y - h - _GAP_PX  # 翻到选区上方
            if py < geo.top():
                py = geo.top()

        self._cached_geo = QRect(px, py, w, h)
        self.move(px, py)

        # 全局 mouse hook 拿到的是物理像素，这里换算出物理坐标的几何，
        # 供 _on_global_event 比对 —— 否则在缩放屏（125%/150%）上点击气泡
        # 内部也会被判成「外部」而误关。
        scale = 1.0
        try:
            if screen is not None:
                scale = screen.devicePixelRatio()
        except Exception:
            pass
        self._cached_geo_physical = QRect(
            round(px * scale), round(py * scale),
            round(w * scale), round(h * scale),
        )

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
        # 回复完整，启用「转主窗」按钮。
        self._set_actions_enabled(True)

    def _on_stream_error(self, msg: str):
        self._streaming = False
        if not self._full_text:
            self._content.setPlainText(f"[错误] {msg}")
        # 有内容才允许转主窗；纯错误（无任何回复）保持禁用，避免搬空内容。
        self._set_actions_enabled(bool(self._full_text))

    def _set_actions_enabled(self, enabled: bool):
        """启用/禁用「转主窗」与「新建」按钮（流式期间禁用，置灰不可点）。"""
        self._main_btn.setEnabled(enabled)
        self._new_btn.setEnabled(enabled)

    def _on_continue_main(self):
        """将当前问答交接到主窗口，复用最近的划词速记会话。"""
        self.continue_in_main.emit(
            self._source_text, self._full_text, self._action_key, False
        )
        self.hide()

    def _on_continue_main_new(self):
        """将当前问答交接到主窗口，强制新建划词速记会话。"""
        self.continue_in_main.emit(
            self._source_text, self._full_text, self._action_key, True
        )
        self.hide()

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
        self._remove_click_watcher()

    # ── Win32 防激活 ────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_no_activate()
        self._install_click_watcher()

    def _apply_no_activate(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            ex_style = user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, _GWL_EXSTYLE, ex_style | _WS_EX_NOACTIVATE
            )
        except Exception:
            logger.warning(
                "ResultBubble: WS_EX_NOACTIVATE 设置失败", exc_info=True
            )

    # ── 全局点击监听 ────────────────────────────────────────────────────

    def _on_hide_requested(self):
        self.hide()

    def _install_click_watcher(self):
        if not _MOUSE_OK:
            return
        if self._mouse_hook is not None:
            return
        try:
            self._mouse_hook = _mouse.hook(self._on_global_event)
        except Exception:
            logger.warning("ResultBubble: mouse hook 安装失败", exc_info=True)

    def _remove_click_watcher(self):
        if self._mouse_hook is None:
            return
        try:
            _mouse.unhook(self._mouse_hook)
        except Exception:
            logger.warning("ResultBubble: mouse hook 卸载失败", exc_info=True)
            return
        self._mouse_hook = None

    def _on_global_event(self, event):
        event_type = getattr(event, "event_type", None)
        if event_type != "down":
            return
        button = getattr(event, "button", None)
        if button == _mouse.RIGHT:
            self._hide_requested.emit()
            return
        if button == _mouse.LEFT:
            geo = self._cached_geo_physical
            if geo is not None:
                x, y = _mouse.get_position()
                if not geo.contains(x, y):
                    self._hide_requested.emit()
