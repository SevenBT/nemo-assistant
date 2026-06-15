"""划词浮标监听 — 全局鼠标钩子，检测「拖选」手势。

钩子线程只看鼠标的按下/松开动作和坐标，**不读取任何内容**（不碰剪贴板、
无隐私顾虑）。判定为一次划词手势后，通过 pyqtSignal 把坐标 marshal 回 Qt
主线程，由主线程在光标附近弹出浮标。取词只在用户真正点击浮标动作时才发生。

镜像 hotkey_manager.py 的「后台 hook 线程 → pyqtSignal → 主线程」模式。

手势判定（位移/时间阈值）抽成纯函数 is_drag_selection，便于单测。
"""
from __future__ import annotations

import time

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
        趁源应用仍持前台、选区仍在时立刻查。查到非空：带文字发信号、弹窗。
        查到空：多半是切标签/拖滚动条等非选字拖动，直接不发，从根上消除误弹。

        UIA 不可用时（库缺失 / 应用不支持）带空文字发信号，由控制器在点击时
        用 Ctrl+C 兜底取词，保住旧行为。

        —— 弹窗定位 ——
        优先用 UIA BoundingRectangles 获取选区末行在屏幕上的精确位置，
        弹窗紧贴选区下方。BoundingRectangles 不可用时退回鼠标松手坐标。
        """
        text = ""
        px, py = x, y  # 回退：鼠标松手坐标
        if selection_uia.is_available():
            try:
                text = selection_uia.get_selected_text()
            except Exception:
                text = ""
            # UIA 可用却查到空 → 没真选中文字（切标签等），静默不弹。
            if not text:
                return
            # 拿到了文字，试试也拿到选区屏幕位置——同一控件，大概率可用。
            try:
                bounds = selection_uia.get_selection_bounds()
                if bounds is not None:
                    left, top, right, bottom = bounds
                    px = (left + right) // 2  # 水平居中于选区末行
                    py = bottom               # 紧贴选区底边
            except Exception:
                pass
        # marshal 回主线程：Qt 信号跨线程自动用 queued connection。
        self.selection_gesture.emit(px, py, text)
