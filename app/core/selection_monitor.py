"""划词浮标监听 — 全局鼠标钩子，检测「拖选」手势。

鼠标事件驱动拖选状态机；命中后在后台用 UIA 静默读取选区，再通过 pyqtSignal
通知 Qt 主线程显示浮标。只有 UIA 不可读时，才在点击动作后通过剪贴板取词。

镜像 hotkey_manager.py 的「后台 hook 线程 → pyqtSignal → 主线程」模式。

手势判定（位移/时间阈值）抽成纯函数 is_drag_selection，便于单测。
"""
from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from app.core import selection_uia

logger = logging.getLogger(__name__)

try:
    import mouse as _mouse
    _MOUSE_OK = True
except ImportError:
    _MOUSE_OK = False

# 手势判定阈值。注意：手势只是「可能选了文字」的预筛——是否真的选中由随后的
# 静默取词决定（取不到就什么都不做）。阈值只为减少无谓的取词尝试。
#
# ★ 判定依据是「按住期间累积的真实移动轨迹长度」，不是起落两点的位移差。
# 原因（实测日志验证）：mouse 库的全局钩子在 up 时刻偶发坐标毛刺——把原地
# 点击的 up 采成几百像素外的脏坐标（如 78ms 内位移 702px，人手不可能），
# 导致「点击切行」被误判为拖选而误弹。而轨迹长度只累加按住期间真实收到的
# move 事件：点击期间无 move（轨迹=0，不弹）；快速划词哪怕 <0.1s 系统也会
# 吐出多个 move（轨迹够，照弹）；单点毛刺不进轨迹。耗时门槛因此取消——它
# 既会误杀快速划词、又拦不住高速毛刺，两端互斥，治标不治本。
_MIN_DRAG_DISTANCE = 40      # 按住期间累积轨迹下限（px）：低于此视为点击/手抖
_MIN_DRAG_MOVES = 1          # 按住期间最少 move 事件数：0 个=纯点击，必非拖选
_MAX_DRAG_DURATION = 5.0     # 起落最长耗时（s）：超时多半是拖窗/拖文件，非选字
_DIAGNOSTIC_SAMPLE_SECONDS = 0.25  # 只采样正在拖动的 move，避免逐帧日志干扰时序


def _foreground_identity() -> tuple[int, int]:
    """仅供诊断的窗口/进程编号；不读取窗口标题或应用内容。"""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
        return int(hwnd or 0), pid.value
    except Exception:
        return 0, 0

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


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


# I 形光标热点到底边的距离取不到时的兜底偏移（px，物理像素，约半行高）。
_FALLBACK_CARET_HALF_PX = 11


def caret_hotspot_to_bottom() -> int:
    """估算当前 I 形光标「热点到底边」的物理像素距离，用于把兜底锚点下移到行底。

    文本拖选时鼠标是 I 形光标，其热点在行的垂直中心；松手坐标因此落在文字
    中线而非底边，浮标贴其下方会盖住下半行。本函数查系统光标位图算出
    「热点 → 光标底边」的距离，加到锚点 y 上即可把浮标推到整行下方。

    查询失败（API 失败 / 句柄无效）返回 _FALLBACK_CARET_HALF_PX 兜底。
    在钩子线程同步调用，趁光标仍是松手瞬间的形状。
    """
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    try:
        info = _CURSORINFO()
        info.cbSize = ctypes.sizeof(_CURSORINFO)
        if not user32.GetCursorInfo(ctypes.byref(info)) or not info.hCursor:
            return _FALLBACK_CARET_HALF_PX
        icon = _ICONINFO()
        if not user32.GetIconInfo(info.hCursor, ctypes.byref(icon)):
            return _FALLBACK_CARET_HALF_PX
        bmp = _BITMAP()
        height = 0
        # 优先用彩色位图高度；无彩色位图（单色光标）时掩码位图高度是实际的两倍
        # （AND + XOR 两段堆叠），取一半。
        try:
            handle = icon.hbmColor or icon.hbmMask
            mono = not icon.hbmColor
            if handle and gdi32.GetObjectW(
                handle, ctypes.sizeof(_BITMAP), ctypes.byref(bmp)
            ):
                height = bmp.bmHeight // 2 if mono else bmp.bmHeight
        finally:
            if icon.hbmMask:
                gdi32.DeleteObject(icon.hbmMask)
            if icon.hbmColor:
                gdi32.DeleteObject(icon.hbmColor)
        if height <= 0:
            return _FALLBACK_CARET_HALF_PX
        # 热点在中心，底边距离 = 总高 - 热点 y；异常时退回半高。
        below = height - int(icon.yHotspot)
        return below if 0 < below <= height else height // 2
    except Exception:
        return _FALLBACK_CARET_HALF_PX


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


# 左键虚拟键码，用于无 DOWN 事件的恢复与诊断。
_VK_LBUTTON = 0x01


def is_left_button_physically_down() -> bool:
    """查左键当前是否物理按下（GetAsyncKeyState 最高位）。

    注意：低级鼠标钩子的回调可能早于 Windows 更新异步按键状态，收到 UP 时
    此值仍可能为 True。不能以它否决已有的 DOWN/UP 事件。

    API 失败时返回 False（fail-open：当作真释放正常处理，不卡住手势）。
    """
    try:
        state = ctypes.windll.user32.GetAsyncKeyState(_VK_LBUTTON)
        return bool(state & 0x8000)
    except Exception:
        return False


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
    path_len: float,
    move_count: int,
    duration: float,
    *,
    min_distance: float = _MIN_DRAG_DISTANCE,
    min_moves: int = _MIN_DRAG_MOVES,
    max_duration: float = _MAX_DRAG_DURATION,
) -> bool:
    """判定一次「按下→松开」是否构成划词手势。

    纯函数，便于单测。判定依据是按住期间累积的真实移动轨迹，而非起落两点
    位移差——后者会被钩子的坐标毛刺污染（见模块顶部阈值注释）。

    参数：
      path_len:   按住期间累积的轨迹总长（相邻 move 点间切比雪夫距离之和，px）。
      move_count: 按住期间收到的 move 事件数。纯点击为 0；任何拖动 ≥1。
      duration:   起落耗时（秒）。只保留上限，过滤拖窗/拖文件的超长按住。

    点击切行：move_count=0 → 直接否。快速划词：move_count≥1 且轨迹够长 → 真。
    单点坐标毛刺：不产生 move，path_len/move_count 都不增长 → 不误判。
    """
    if move_count < min_moves:
        return False
    if path_len < min_distance:
        return False
    if duration > max_duration:
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
        self._press_text_cursor = True  # 按下边沿记录的光标形状，门槛兜底路径用
        self._release_text_cursor = True
        self._drag_text_cursor_seen = True
        # DOWN/double 开始，UP 结束；物理按键只用来恢复缺失的 DOWN。
        self._press_pending = False
        # 按住期间累积的真实移动轨迹：last_x/y 为上一个采样点，path_len 为累积
        # 轨迹总长，move_count 为按住期间事件数。按下边沿重置，持续按下时累加，
        # 松开边沿据此判定拖选。轨迹来自真实坐标流，不受单点坐标毛刺影响。
        self._last_x = 0
        self._last_y = 0
        self._path_len = 0.0
        self._move_count = 0
        self._hook = None
        self._gesture_sequence = 0
        self._gesture_id = "none"
        self._last_event_at = None
        self._last_move_at = None
        self._last_sample_at = 0.0
        self._left_up_at = None
        self._left_up_event_time = None
        self._max_event_age_ms = 0.0
        self._press_foreground = (0, 0)
        self._release_probe_id = None
        self._last_probe_at = None
        # 独立于 mouse 事件流的只读探针，不结束手势、不取词、不发显示信号。
        self._diagnostic_timer = QTimer(self)
        self._diagnostic_timer.setInterval(100)
        self._diagnostic_timer.timeout.connect(self._diagnostic_probe)

    # ------------------------------------------------------------------ 公开接口
    def start(self):
        """启用划词监听，安装鼠标钩子。"""
        if not _MOUSE_OK or self._enabled:
            logger.info(
                "[SelectionTiming] stage=monitor_start_skipped t=%.6f mouse_available=%s enabled=%s",
                time.perf_counter(), _MOUSE_OK, self._enabled,
            )
            return
        try:
            self._hook = _mouse.hook(self._on_event)
            self._enabled = True
            self._last_probe_at = time.perf_counter()
            self._diagnostic_timer.start()
            logger.info(
                "[SelectionTiming] stage=monitor_started t=%.6f "
                "min_path_px=%d min_moves=%d max_duration_s=%.1f",
                time.perf_counter(), _MIN_DRAG_DISTANCE, _MIN_DRAG_MOVES, _MAX_DRAG_DURATION,
            )
        except Exception:  # pragma: no cover - 依赖系统钩子
            logger.warning(
                "SelectionMonitor: 安装鼠标钩子失败", exc_info=True
            )

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
            self._diagnostic_timer.stop()
            self._press_pending = False
            logger.info(
                "[SelectionTiming] stage=monitor_stopped t=%.6f gesture_id=%s pending=%s",
                time.perf_counter(), self._gesture_id, self._press_pending,
            )

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
    def _diagnostic_probe(self):
        """即使没有新的鼠标事件，也保留松开已发生/Qt 事件循环迟到的证据。"""
        now = time.perf_counter()
        gap_ms = ((now - self._last_probe_at) * 1000
                  if self._last_probe_at is not None else 0.0)
        self._last_probe_at = now
        if gap_ms > 350:
            logger.info(
                "[SelectionTiming] stage=qt_probe_late t=%.6f gesture_id=%s "
                "tick_gap_ms=%.2f expected_ms=100 pending=%s",
                now, self._gesture_id, gap_ms, self._press_pending,
            )
        gesture_id = self._gesture_id
        if (self._press_pending and self._release_probe_id != gesture_id
                and not is_left_button_physically_down()):
            self._release_probe_id = gesture_id
            logger.info(
                "[SelectionTiming] stage=release_probe t=%.6f gesture_id=%s "
                "physical_down=False pending=True up_seen=%s last_event_gap_ms=%.2f",
                now, gesture_id, self._left_up_at is not None,
                (now - self._last_event_at) * 1000 if self._last_event_at is not None else -1.0,
            )

    def _begin_gesture(self, mx, my, *, callback_at, event_type, button, event_age_ms):
        """记录一次按下边沿；事件标签优先，物理状态只作兜底。"""
        self._press_pending = True
        self._press_x, self._press_y = mx, my
        self._press_t = time.monotonic()
        self._press_text_cursor = is_text_cursor()
        self._release_text_cursor = self._press_text_cursor
        self._drag_text_cursor_seen = self._press_text_cursor
        self._last_x, self._last_y = mx, my
        self._path_len = 0.0
        self._move_count = 0
        self._gesture_sequence += 1
        self._gesture_id = f"{id(self):x}-{self._gesture_sequence}"
        self._left_up_at = None
        self._left_up_event_time = None
        self._last_move_at = None
        self._last_sample_at = callback_at
        self._max_event_age_ms = event_age_ms
        self._press_foreground = _foreground_identity()
        logger.info(
            "[SelectionTiming] stage=press_detected t=%.6f gesture_id=%s "
            "event=%s button=%s event_age_ms=%.2f start=(%d,%d) "
            "press_cursor_text=%s foreground_hwnd=%s foreground_pid=%s",
            callback_at, self._gesture_id, event_type, button, event_age_ms, mx, my,
            self._press_text_cursor, *self._press_foreground,
        )

    def _record_drag_move(self, mx, my, *, callback_at, event_type, event_age_ms, down_now):
        self._path_len += max(abs(mx - self._last_x), abs(my - self._last_y))
        self._last_x, self._last_y = mx, my
        self._move_count += 1
        self._max_event_age_ms = max(self._max_event_age_ms, event_age_ms)
        current_cursor_text = is_text_cursor()
        self._drag_text_cursor_seen |= current_cursor_text
        if event_type == "move":
            self._last_move_at = callback_at
            if callback_at - self._last_sample_at >= _DIAGNOSTIC_SAMPLE_SECONDS:
                self._last_sample_at = callback_at
                logger.info(
                    "[SelectionTiming] stage=drag_sample t=%.6f gesture_id=%s "
                    "event_age_ms=%.2f physical_down=%s pos=(%d,%d) "
                    "path_px=%.1f moves=%d cursor_text=%s up_seen=%s",
                    callback_at, self._gesture_id, event_age_ms, down_now, mx, my,
                    self._path_len, self._move_count, current_cursor_text,
                    self._left_up_at is not None,
                )

    def _finish_gesture(self, mx, my, *, callback_at, event_type, button, event_time,
                        event_age_ms, event_gap_ms):
        if not self._press_pending:
            return
        self._press_pending = False
        self._release_text_cursor = is_text_cursor()
        self._drag_text_cursor_seen |= self._release_text_cursor
        duration = time.monotonic() - self._press_t
        accepted = is_drag_selection(self._path_len, self._move_count, duration)
        reason = ("accepted" if accepted else "no_moves" if self._move_count < _MIN_DRAG_MOVES
                  else "short_path" if self._path_len < _MIN_DRAG_DISTANCE else "too_long")
        up_to_release_ms = ((callback_at - self._left_up_at) * 1000
                            if self._left_up_at is not None else -1.0)
        last_move_gap_ms = ((callback_at - self._last_move_at) * 1000
                            if self._last_move_at is not None else -1.0)
        logger.info(
            "[SelectionTiming] stage=gesture t=%.6f gesture_id=%s accepted=%s "
            "path_px=%.1f moves=%d duration_ms=%.2f "
            "start=(%d,%d) end=(%d,%d) delta=(%d,%d) press_cursor_text=%s "
            "release_cursor_text=%s drag_cursor_text_seen=%s reason=%s end_event=%s end_button=%s "
            "event_time=%s event_age_ms=%.2f max_event_age_ms=%.2f "
            "event_gap_ms=%.2f last_move_gap_ms=%.2f up_seen=%s "
            "up_event_time=%s up_to_release_ms=%.2f "
            "press_foreground=%s release_foreground=%s",
            callback_at, self._gesture_id, accepted, self._path_len, self._move_count,
            duration * 1000, self._press_x, self._press_y, mx, my,
            mx - self._press_x, my - self._press_y, self._press_text_cursor,
            self._release_text_cursor, self._drag_text_cursor_seen, reason,
            event_type, button, event_time, event_age_ms,
            max(self._max_event_age_ms, event_age_ms), event_gap_ms, last_move_gap_ms,
            self._left_up_at is not None, self._left_up_event_time, up_to_release_ms,
            self._press_foreground, _foreground_identity(),
        )
        if accepted:
            self._maybe_emit(mx, my)

    def _fallback_state_event(self, mx, my, *, callback_at, event_type, button,
                              event_age_ms, event_gap_ms, down_now, was_down, event_time):
        """无事件标签时保留旧的物理按键兜底路径。"""
        if down_now and not was_down:
            self._begin_gesture(
                mx, my, callback_at=callback_at, event_type=event_type,
                button=button, event_age_ms=event_age_ms,
            )
        elif down_now and was_down:
            self._record_drag_move(
                mx, my, callback_at=callback_at, event_type=event_type,
                event_age_ms=event_age_ms, down_now=down_now,
            )
        elif not down_now and was_down:
            self._finish_gesture(
                mx, my, callback_at=callback_at, event_type=event_type,
                button=button, event_time=event_time, event_age_ms=event_age_ms,
                event_gap_ms=event_gap_ms,
            )

    def _on_event(self, event):
        """按事件顺序处理 DOWN/double、move、UP。

        低级钩子投递事件时，GetAsyncKeyState 可能还未更新。正常 UP 必须直接
        结束手势，否则静止鼠标会一直等下一次 move。无轨迹的 UP 不弹窗，后续
        仍按着的 move 可以恢复手势；重复 UP 则忽略。
        """
        callback_at = time.perf_counter()
        callback_wall = time.time()
        raw_event_type = getattr(event, "event_type", None)
        labeled_event = raw_event_type is not None or (hasattr(event, "x") and hasattr(event, "time"))
        event_type = raw_event_type or ("move" if hasattr(event, "x") else "unknown")
        button = getattr(event, "button", "none")
        event_time = getattr(event, "time", None)
        event_age_ms = ((callback_wall - event_time) * 1000
                        if isinstance(event_time, (float, int)) and event_time > 0 else -1.0)
        event_gap_ms = ((callback_at - self._last_event_at) * 1000
                        if self._last_event_at is not None else -1.0)
        self._last_event_at = callback_at
        # 取当前坐标：MoveEvent 自带 x/y；ButtonEvent 用 get_position()。
        mx = getattr(event, "x", None)
        my = getattr(event, "y", None)
        if mx is None or my is None:
            try:
                mx, my = _mouse.get_position()
            except Exception:
                logger.warning(
                    "[SelectionTiming] stage=event_skipped t=%.6f reason=position_unavailable "
                    "event=%s button=%s", callback_at, event_type, button,
                )
                return

        down_now = is_left_button_physically_down()
        was_down = self._press_pending
        # 保留标签与物理状态不一致的诊断证据，但不再用物理状态否决 UP。
        if button == "left":
            logger.info(
                "[SelectionTiming] stage=button_event t=%.6f gesture_id=%s event=%s "
                "button=%s event_time=%s event_age_ms=%.2f event_gap_ms=%.2f "
                "physical_down=%s pending=%s pos=(%d,%d)",
                callback_at, self._gesture_id, event_type, button, event_time,
                event_age_ms, event_gap_ms, down_now, was_down, mx, my,
            )

        labeled = labeled_event and event_type in {"down", "up", "double", "move"}
        left_button = button == "left" or button == getattr(_mouse, "LEFT", "__missing__")
        if labeled and left_button and event_type in {"down", "double"}:
            if self._press_pending:
                logger.info(
                    "[SelectionTiming] stage=gesture_cancelled t=%.6f gesture_id=%s "
                    "reason=new_press_before_release",
                    callback_at, self._gesture_id,
                )
            self._begin_gesture(
                mx, my, callback_at=callback_at, event_type=event_type,
                button=button, event_age_ms=event_age_ms,
            )
        elif labeled and left_button and event_type == "up":
            self._left_up_at = callback_at
            self._left_up_event_time = event_time
            self._finish_gesture(
                mx, my, callback_at=callback_at, event_type=event_type,
                button=button, event_time=event_time, event_age_ms=event_age_ms,
                event_gap_ms=event_gap_ms,
            )
        elif labeled and event_type == "move":
            if self._press_pending:
                self._record_drag_move(
                    mx, my, callback_at=callback_at, event_type=event_type,
                    event_age_ms=event_age_ms, down_now=down_now,
                )
            elif down_now:
                # DOWN 丢失或前置空 UP：靠仍按着的 move 恢复起点，不把 UP 当 DOWN。
                self._begin_gesture(
                    mx, my, callback_at=callback_at, event_type=event_type,
                    button=button, event_age_ms=event_age_ms,
                )
        elif not labeled:
            self._fallback_state_event(
                mx, my, callback_at=callback_at, event_type=event_type, button=button,
                event_age_ms=event_age_ms, event_gap_ms=event_gap_ms,
                down_now=down_now, was_down=was_down, event_time=event_time,
            )
        # 空闲 move、重复 UP 与其他按键不触发动作条。

    def _maybe_emit(self, x: int, y: int):
        """手势命中后用 UIA 查前台选区，决定是否弹窗。

        ★ 在鼠标事件线程同步查 UIA（显式初始化该线程的 COM 上下文）——必须
        趁源应用仍持前台、选区仍在时立刻查。按 UIA 状态 + 全程光标证据分流
        （见 should_emit）：

          - HAS_TEXT：取到文字，带文字发信号、弹窗。
          - NO_TEXT_PATTERN / UNAVAILABLE：控件读不到选区（Canvas 网页、浏览器
            内置 PDF、跨域 iframe、自绘控件，或 UIA 库缺失）。仅当按下、拖动或
            松开时采到文本光标才带空文字弹出动作条，点击时用 Ctrl+C 兜底；否则
            （拖标题栏/桌面/滚动条，箭头光标）静默，消除误弹。
          - EMPTY_SELECTION / NO_FOCUS：控件支持 TextPattern 但没选区（切标签 /
            拖滚动条），或拿不到焦点控件 → 静默不弹。

        —— 弹窗定位 ——
        优先用 UIA 取整片选区的并集包围盒，弹窗居中于选区水平中心、紧贴其底边。
        包围盒不可用时退回「按下点 + 松手点」推算的锚点（水平中点、垂直取较低
        者）——两者都与拖选方向无关，浮标不会因方向不同而偏移或盖住文字。
        """
        capture_started = time.perf_counter()
        logger.info(
            "[SelectionTiming] stage=uia_capture_begin t=%.6f gesture_id=%s",
            capture_started, self._gesture_id,
        )
        try:
            status, text = selection_uia.query_selection(point=(x, y))
        except Exception as exc:
            logger.warning(
                "[SelectionTiming] stage=uia_capture_error gesture_id=%s exception_type=%s",
                self._gesture_id, type(exc).__name__,
            )
            status, text = selection_uia.SelectionStatus.NO_TEXT_PATTERN, ""
        logger.info(
            "[SelectionTiming] stage=uia_capture t=%.6f gesture_id=%s elapsed_ms=%.2f status=%s chars=%d",
            time.perf_counter(), self._gesture_id,
            (time.perf_counter() - capture_started) * 1000,
            getattr(status, "name", str(status)),
            len(text or ""),
        )

        cursor_evidence = (
            self._press_text_cursor
            or self._release_text_cursor
            or self._drag_text_cursor_seen
        )
        emit = should_emit(status, cursor_evidence)
        # 没有选区确认、也从未出现文本光标的拖动仍静默，避免拖窗/桌面误弹。
        if not emit:
            logger.info(
                "[SelectionTiming] stage=filtered t=%.6f gesture_id=%s status=%s "
                "press_cursor_text=%s release_cursor_text=%s drag_cursor_text_seen=%s",
                time.perf_counter(), self._gesture_id, getattr(status, "name", str(status)),
                self._press_text_cursor, self._release_text_cursor, self._drag_text_cursor_seen,
            )
            return

        # 回退锚点：用「按下点 + 松手点」的包围盒，水平取中点、垂直取较低者
        # （选区底边）。直接用松手点会让锚点随拖选方向变（右→左选松手在左侧、
        # 下→上选松手在顶部），导致浮标偏左或盖住文字；用两点包围盒则与方向无关。
        #
        # 但文本拖选时鼠标是 I 形光标、热点在行垂直中心，松手 y 落在文字中线而非
        # 底边——直接贴其下方会盖住下半行。故再下移「热点→光标底边」的距离，把
        # 锚点推到整行下方。
        px = (self._press_x + x) // 2
        py = max(self._press_y, y) + caret_hotspot_to_bottom()
        # 取到文字时试着拿选区屏幕位置——同一控件，大概率可用。
        # 读不到选区的分支（无 TextPattern / UIA 不可用）没有可查的位置，
        # 直接用包围盒锚点定位。
        if status == selection_uia.SelectionStatus.HAS_TEXT:
            bounds_started = time.perf_counter()
            logger.info(
                "[SelectionTiming] stage=uia_bounds_begin t=%.6f gesture_id=%s",
                bounds_started, self._gesture_id,
            )
            bounds = None
            try:
                bounds = selection_uia.get_selection_bounds()
                if bounds is not None:
                    left, top, right, bottom = bounds
                    px = (left + right) // 2  # 水平居中于整片选区
                    py = bottom               # 紧贴选区底边
            except Exception as exc:
                logger.warning(
                    "[SelectionTiming] stage=uia_bounds_error gesture_id=%s exception_type=%s",
                    self._gesture_id, type(exc).__name__,
                )
            logger.info(
                "[SelectionTiming] stage=uia_bounds t=%.6f gesture_id=%s elapsed_ms=%.2f found=%s",
                time.perf_counter(), self._gesture_id,
                (time.perf_counter() - bounds_started) * 1000,
                bounds is not None,
            )
        # marshal 回主线程：Qt 信号跨线程自动用 queued connection。
        # text 为空时（NO_TEXT_PATTERN / UNAVAILABLE）控制器点击时走 Ctrl+C 兜底。
        logger.info(
            "[SelectionTiming] stage=signal_emit t=%.6f gesture_id=%s status=%s "
            "anchor_physical=(%d,%d) chars=%d",
            time.perf_counter(), self._gesture_id, getattr(status, "name", str(status)),
            px, py, len(text or ""),
        )
        self.selection_gesture.emit(px, py, text)
