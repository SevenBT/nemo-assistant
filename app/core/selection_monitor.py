"""划词浮标监听 — 全局鼠标钩子，检测「拖选」手势。

钩子线程只看鼠标的按下/松开动作和坐标，**不读取任何内容**（不碰剪贴板、
无隐私顾虑）。判定为一次划词手势后，通过 pyqtSignal 把坐标 marshal 回 Qt
主线程，由主线程在光标附近弹出浮标。取词只在用户真正点击浮标动作时才发生。

镜像 hotkey_manager.py 的「后台 hook 线程 → pyqtSignal → 主线程」模式。

手势判定（位移/时间阈值）抽成纯函数 is_drag_selection，便于单测。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

from app.core import selection_uia

try:
    import mouse as _mouse
    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False

# 手势判定阈值。注意：手势只是「可能选了文字」的预筛——是否真的选中由随后的
# 静默取词决定（取不到就什么都不做）。阈值只为减少无谓的取词尝试。
_MIN_DRAG_DISTANCE = 40      # 起落点位移下限（px）：低于此视为点击/手抖，非拖选
_MIN_DRAG_DURATION = 0.12    # 起落最短耗时（s）：过滤误触发的瞬时抖动
_MAX_DRAG_DURATION = 5.0     # 起落最长耗时（s）：超时多半是拖窗/拖文件，非选字

# 标准 I 形（文本）光标句柄。可选文字区域悬停时系统光标为 IDC_IBEAM；
# 标题栏、桌面、滚动条、图标拖动等非文本区域为箭头/手型/十字等。用它把
# 「在文字上拖选」和「拖标题栏/桌面」区分开，避免兜底路径误弹。
_IDC_IBEAM = 32513


def _load_ibeam_handle() -> int:
    """加载系统标准 I-beam 光标句柄，失败返回 0（视作不可用，门槛失效即放行）。"""
    try:
        user32 = ctypes.windll.user32
        user32.LoadCursorW.restype = wintypes.HANDLE
        user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        handle = user32.LoadCursorW(None, ctypes.c_wchar_p(_IDC_IBEAM))
        return int(handle) if handle else 0
    except Exception:
        return 0


_IBEAM_HANDLE = _load_ibeam_handle()


class _CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", wintypes.HANDLE),
        ("ptScreenPos", wintypes.POINT),
    ]


def is_text_cursor() -> bool:
    """当前系统光标是否为标准 I 形（文本）光标。

    用于区分「在可选文字上拖动」与「拖标题栏/桌面/滚动条」。无法判断时
    （API 失败 / 句柄取不到）返回 True——宁可放行也不误杀真实选词。

    局限：少数应用用自绘 I-beam 光标，句柄与系统标准不同，会判为 False；
    但主流浏览器、编辑器、PDF 阅读器的文本区都用系统 I-beam，覆盖足够。
    """
    if not _IBEAM_HANDLE:
        return True  # 句柄不可用，门槛失效，放行
    try:
        info = _CURSORINFO()
        info.cbSize = ctypes.sizeof(_CURSORINFO)
        if not ctypes.windll.user32.GetCursorInfo(ctypes.byref(info)):
            return True
        return int(info.hCursor) == _IBEAM_HANDLE
    except Exception:
        return True


def should_emit(status, was_text_cursor: bool) -> bool:
    """根据 UIA 取词状态与「拖动时是否为文本光标」决定是否弹动作条。

    纯函数，便于单测。规则：

      - HAS_TEXT：UIA 已确认真有选中文字 → 必弹（不受光标门槛限制）。
      - NO_TEXT_PATTERN / UNAVAILABLE：UIA 读不到选区（内置 PDF / Canvas /
        老 Electron / 库缺失）。仅当拖动时为文本光标才弹——否则多半是拖
        标题栏 / 拖桌面 / 拖滚动条，静默，消除误弹。
      - EMPTY_SELECTION / NO_FOCUS：真没选中或无焦点控件 → 静默。
    """
    if status == selection_uia.SelectionStatus.HAS_TEXT:
        return True
    if status in (
        selection_uia.SelectionStatus.NO_TEXT_PATTERN,
        selection_uia.SelectionStatus.UNAVAILABLE,
    ):
        return was_text_cursor
    return False


def is_drag_selection(
    dx: float,
    dy: float,
    duration: float,
    *,
    min_distance: float = _MIN_DRAG_DISTANCE,
    min_duration: float = _MIN_DRAG_DURATION,
    max_duration: float = _MAX_DRAG_DURATION,
) -> bool:
    """判定一次「按下→松开」是否构成划词手势。

    纯函数，便于单测。dx/dy 为起落点位移，duration 为耗时（秒）。
    位移用切比雪夫距离（max(|dx|,|dy|)）足够区分点击与拖选，省去开方。
    """
    distance = max(abs(dx), abs(dy))
    if distance < min_distance:
        return False
    if duration < min_duration or duration > max_duration:
        return False
    return True


class SelectionMonitor(QObject):
    """全局鼠标钩子，检测划词手势并通过信号通知 UI。

    selection_gesture(x, y, text)：检测到一次拖选且 UIA 查到非空选区，参数为
    松开时的屏幕坐标与已取到的选中文字。

    取词时机的演进：早期靠手势 + Ctrl+C 劫持取词，导致切标签/拖滚动条等
    非选字拖动也注入全局 Ctrl+C（开发期附着控制台会被解释成 SIGINT），且无法
    在弹窗前判断是否真选中文字。改为在手势命中后直接用 UIA 查前台控件的选区：
    查到非空才弹窗、文字一并带出（连点击后的取词都省了）；查到空（切标签等）
    直接不发信号，从根上消除误弹与多余按键注入。

    UIA 不可用时（库缺失或目标应用不支持）退回「带空文字发信号」，由控制器
    在点击时再用 Ctrl+C 兜底取词，保证旧行为不丢失。
    """

    selection_gesture = pyqtSignal(int, int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._enabled = False
        self._press_x = 0
        self._press_y = 0
        self._press_t = 0.0
        self._press_text_cursor = True  # 按下时是否为文本光标，门槛兜底路径用
        self._hook = None

    # ------------------------------------------------------------------ 公开接口
    def start(self):
        """启用划词监听，安装鼠标钩子。"""
        if not _MOUSE_OK or self._enabled:
            return
        try:
            self._hook = _mouse.hook(self._on_event)
            self._enabled = True
        except Exception as e:  # pragma: no cover - 依赖系统钩子
            print(f"[SelectionMonitor] Failed to install hook: {e}")

    def stop(self):
        """停用划词监听，移除鼠标钩子。"""
        if not _MOUSE_OK or not self._enabled:
            return
        try:
            if self._hook is not None:
                _mouse.unhook(self._hook)
        except Exception:
            pass
        finally:
            self._hook = None
            self._enabled = False

    def set_enabled(self, enabled: bool):
        """根据配置开关启用/停用。"""
        if enabled:
            self.start()
        else:
            self.stop()

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    # ------------------------------------------------------------------ 内部实现
    def _on_event(self, event):
        """钩子线程回调。只记录左键按下/松开的坐标与时间，不读内容。"""
        # mouse 库的事件类型；用 duck typing 避免强依赖内部类名。
        button = getattr(event, "button", None)
        event_type = getattr(event, "event_type", None)
        if button != getattr(_mouse, "LEFT", "left"):
            return

        if event_type == "down":
            x, y = _mouse.get_position()
            self._press_x, self._press_y = x, y
            self._press_t = time.monotonic()
            # 按下瞬间记录光标形状：在文字上是 I-beam，拖标题栏/桌面是箭头。
            # 用按下时刻而非松开时刻——松开时光标可能已移出文本区。
            self._press_text_cursor = is_text_cursor()
        elif event_type == "up":
            x, y = _mouse.get_position()
            dx = x - self._press_x
            dy = y - self._press_y
            duration = time.monotonic() - self._press_t
            if is_drag_selection(dx, dy, duration):
                self._maybe_emit(x, y)

    def _maybe_emit(self, x: int, y: int):
        """手势命中后用 UIA 查前台选区，决定是否弹窗。

        ★ 在钩子线程同步查 UIA（uiautomation 按线程自动 CoInitialize）——必须
        趁源应用仍持前台、选区仍在时立刻查。按 UIA 状态 + 按下时光标形状分流
        （见 should_emit）：

          - HAS_TEXT：取到文字，带文字发信号、弹窗。
          - NO_TEXT_PATTERN / UNAVAILABLE：控件读不到选区（Canvas 网页、浏览器
            内置 PDF、跨域 iframe、自绘控件，或 UIA 库缺失）。**仅当按下时为文本
            光标**才带空文字发信号、弹动作条，点击时用 Ctrl+C 兜底取词；否则
            （拖标题栏/桌面/滚动条，箭头光标）静默，消除误弹。
          - EMPTY_SELECTION / NO_FOCUS：控件支持 TextPattern 但没选区（切标签 /
            拖滚动条），或拿不到焦点控件 → 静默不弹。

        —— 弹窗定位 ——
        优先用 UIA BoundingRectangles 获取选区末行在屏幕上的精确位置，
        弹窗紧贴选区下方。BoundingRectangles 不可用时退回鼠标松手坐标。
        """
        try:
            status, text = selection_uia.query_selection()
        except Exception:
            status, text = selection_uia.SelectionStatus.NO_TEXT_PATTERN, ""

        # 综合 UIA 状态与按下时光标形状决定是否弹（拖标题栏/桌面被这里挡掉）。
        if not should_emit(status, self._press_text_cursor):
            return

        px, py = x, y  # 回退：鼠标松手坐标
        # 取到文字时试着拿选区屏幕位置——同一控件，大概率可用。
        # 读不到选区的分支（无 TextPattern / UIA 不可用）没有可查的位置，
        # 直接用鼠标坐标定位。
        if status == selection_uia.SelectionStatus.HAS_TEXT:
            try:
                bounds = selection_uia.get_selection_bounds()
                if bounds is not None:
                    left, top, right, bottom = bounds
                    px = (left + right) // 2  # 水平居中于选区末行
                    py = bottom               # 紧贴选区底边
            except Exception:
                pass
        # marshal 回主线程：Qt 信号跨线程自动用 queued connection。
        # text 为空时（NO_TEXT_PATTERN / UNAVAILABLE）控制器点击时走 Ctrl+C 兜底。
        self.selection_gesture.emit(px, py, text)
