"""UIA 取词 — 直接向前台控件查询当前选中的文字，不碰剪贴板、不抢焦点。

为什么用 UIA：操作系统没有「选区变化」的全局事件，过去只能靠鼠标拖选手势
推断「可能选了文字」，结果切标签页、拖滚动条这类同为拖动的动作会被误判而
弹窗。Windows UI Automation 的 TextPattern 能在拖选松手的瞬间直接问前台
控件「你现在选了什么」，从而：

  - 切标签页 / 拖滚动条（无选区）→ 查到空 → 不弹窗
  - 真选了文字 → 查到内容 → 弹窗，且文字已到手，无需再发 Ctrl+C

相比 Ctrl+C 劫持的优势：纯查询，不注入全局按键（不会在附着控制台的开发期
被解释成 SIGINT 打断 app），不改剪贴板（不打扰正常复制粘贴），不抢焦点。

代价：依赖目标应用对 UIA 的支持。主流浏览器、Office、记事本、原生输入框
都支持；少数自绘控件 / 老 Electron / 远程桌面 / Canvas 渲染的网页 / 浏览器
内置 PDF / 跨域 iframe 查不到选区。对这类「读不到」的情况返回
NO_TEXT_PATTERN，让调用方照常弹按钮、点击时用 Ctrl+C 兜底救回，而不是
当成「没选中」漏弹。只有「控件支持 TextPattern 但选区为空」（切标签 /
拖滚动条）才判为真没选中、静默不弹。

COM 线程注意：本函数会在鼠标钩子线程被调用。uiautomation 库按线程自动
CoInitialize，查到的文字由调用方 marshal 回 Qt 主线程再用。
"""
from __future__ import annotations

from enum import Enum, auto
import logging
import time
from contextlib import nullcontext
from threading import current_thread, main_thread

from app.core.selection_capture import MAX_SELECTION_CHARS, clean_selection

logger = logging.getLogger(__name__)


def _diagnostic_call(query_id, operation, callback):
    """记录现有 UIA 调用的边界，不增加查询，不输出文本或异常消息。"""
    if not logger.isEnabledFor(logging.DEBUG):
        return callback()
    started = time.perf_counter()
    logger.debug(
        "[SelectionTiming] stage=uia_step_begin t=%.6f query_id=%s operation=%s",
        started, query_id, operation,
    )
    try:
        result = callback()
    except Exception as exc:
        logger.debug(
            "[SelectionTiming] stage=uia_step_error t=%.6f query_id=%s "
            "operation=%s elapsed_ms=%.2f exception_type=%s",
            time.perf_counter(), query_id, operation,
            (time.perf_counter() - started) * 1000, type(exc).__name__,
        )
        raise
    logger.debug(
        "[SelectionTiming] stage=uia_step_done t=%.6f query_id=%s "
        "operation=%s elapsed_ms=%.2f result_present=%s",
        time.perf_counter(), query_id, operation,
        (time.perf_counter() - started) * 1000, result is not None,
    )
    return result


def _get_text_pattern(control):
    """兼容 uiautomation 的具体控件类与通用 Control。"""
    method = getattr(control, "GetTextPattern", None)
    if callable(method):
        return method()
    pattern_id = getattr(getattr(_auto, "PatternId", None), "TextPattern", None)
    if pattern_id is None:
        return None
    return control.GetPattern(pattern_id)


def _get_bounding_rectangles(text_range):
    """uiautomation 2.x 使用 GetBoundingRectangles()，兼容旧属性形式。"""
    method = getattr(text_range, "GetBoundingRectangles", None)
    if callable(method):
        return method()
    value = getattr(text_range, "BoundingRectangles", None)
    return value() if callable(value) else value

try:
    import uiautomation as _auto
    _UIA_OK = True
except Exception:
    # ImportError（未安装）或导入期 COM/comtypes 异常都视为不可用，退回旧路径。
    _UIA_OK = False


class SelectionStatus(Enum):
    """UIA 取词的查询结果状态。

    区分「读不到」与「真没选中」是关键：前者要弹按钮走 Ctrl+C 兜底救回，
    后者（切标签 / 拖滚动条）静默不弹。把二者压成「空串」会让 Canvas 网页、
    浏览器内置 PDF、跨域 iframe 等读不到选区的页面被误当成「没选中」而漏弹。
    """

    HAS_TEXT = auto()         # 取到非空选中文字
    EMPTY_SELECTION = auto()  # 控件支持 TextPattern 但选区为空 → 真没选中，静默
    NO_TEXT_PATTERN = auto()  # 控件不支持 TextPattern → 读不到，应弹按钮走兜底
    NO_FOCUS = auto()         # 拿不到焦点控件 → 无从判断，静默
    UNAVAILABLE = auto()      # UIA 库不可用 → 调用方整体退回 Ctrl+C 路径


def is_available() -> bool:
    """UIA 是否可用。不可用时调用方应退回 Ctrl+C 取词路径。"""
    return _UIA_OK


def _uia_context():
    """uiautomation 要求调用线程先初始化 COM；只在后台线程配对初始化。"""
    if current_thread() is main_thread():
        return nullcontext()
    initializer = getattr(_auto, "UIAutomationInitializerInThread", None)
    return initializer() if initializer is not None else nullcontext()


def query_selection(*, point: tuple[int, int] | None = None) -> tuple[SelectionStatus, str]:
    """查询前台聚焦控件当前选中的文字，返回三态结果。

    纯查询：不发按键、不读写剪贴板、不改变焦点。

    返回 (状态, 文字)。仅 HAS_TEXT 时文字非空；其余状态文字为空串。
    调用方据状态决定：HAS_TEXT 带文字弹窗；NO_TEXT_PATTERN/UNAVAILABLE
    弹窗但走 Ctrl+C 兜底取词；EMPTY_SELECTION/NO_FOCUS 静默不弹。
    """
    if not _UIA_OK:
        return (SelectionStatus.UNAVAILABLE, "")
    with _uia_context():
        return _query_selection(point=point)


def _query_selection(*, point=None):
    query_id = f"text-{time.perf_counter_ns():x}"
    try:
        control = _diagnostic_call(query_id, "focused_control", _auto.GetFocusedControl)
    except Exception:
        return (SelectionStatus.NO_FOCUS, "")
    if control is None:
        return (SelectionStatus.NO_FOCUS, "")
    logger.debug(
        "[SelectionTiming] stage=uia_control query_id=%s control_class=%s",
        query_id, type(control).__name__,
    )
    result = _selection_via_text_pattern(control, query_id=query_id)
    # Electron/浏览器可能聚焦外层 Pane；在拖选末点找实际文本及其祖先。
    # 只在焦点控件根本不可读时兜底，真实空选区不扩大查询，以保留防误弹规则。
    if result[0] is not SelectionStatus.NO_TEXT_PATTERN or point is None:
        return result
    try:
        target = _diagnostic_call(query_id, "control_at_point", lambda: _auto.ControlFromPoint(*point))
        source_pid = control.ProcessId
        for depth in range(4):
            if target is None or target.ProcessId != source_pid:
                break
            candidate = _selection_via_text_pattern(target, query_id=f"{query_id}-point{depth}")
            if candidate[0] is SelectionStatus.HAS_TEXT:
                return candidate
            # 空 TextPattern 不再沿祖先查询，避免抓到别处保留的旧选区。
            if candidate[0] is SelectionStatus.EMPTY_SELECTION:
                return candidate
            target = _diagnostic_call(query_id, "point_parent", target.GetParentControl)
    except Exception as exc:
        logger.debug(
            "[SelectionTiming] stage=uia_point_fallback_error query_id=%s exception_type=%s",
            query_id, type(exc).__name__,
        )
    return result


def get_selection_bounds() -> tuple[int, int, int, int] | None:
    """查询前台控件当前选区的屏幕包围盒，用于定位浮标。

    返回 (left, top, right, bottom)，为**整片选区所有矩形的并集**——跨所有
    选区 range、所有行的最小外接矩形。这样无论从哪个方向拖选（左→右 / 右→左 /
    上→下 / 下→上），包围盒都一致，调用方据此把浮标放到选区水平中心的正下方，
    不会因方向不同而偏移或盖住文字。

    取不到（UIA 不可用 / 控件不支持 BoundingRectangles / 无选区）返回 None，
    调用方退回鼠标坐标。

    纯查询：不按键、不读剪贴板、不改变焦点。
    """
    if not _UIA_OK:
        return None
    with _uia_context():
        return _query_selection_bounds()


def _query_selection_bounds():
    query_id = f"bounds-{time.perf_counter_ns():x}"
    try:
        control = _diagnostic_call(query_id, "focused_control", _auto.GetFocusedControl)
    except Exception:
        return None
    if control is None:
        return None
    try:
        pattern = _diagnostic_call(query_id, "text_pattern", lambda: _get_text_pattern(control))
    except Exception:
        return None
    if pattern is None:
        return None
    try:
        ranges = _diagnostic_call(query_id, "selection_ranges", pattern.GetSelection)
    except Exception:
        return None
    if not ranges:
        return None

    # 合并所有 range 的所有矩形为一个并集包围盒，与选择方向无关。
    left = top = None
    right = bottom = None
    for index, rng in enumerate(ranges):
        try:
            rects = _diagnostic_call(
                query_id, f"bounding_rectangles:{index}", lambda: _get_bounding_rectangles(rng),
            )
        except Exception:
            continue
        if not rects:
            continue
        for rect in rects:
            if left is None:
                left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
                continue
            left = min(left, rect.left)
            top = min(top, rect.top)
            right = max(right, rect.right)
            bottom = max(bottom, rect.bottom)
    if left is None:
        return None
    return (left, top, right, bottom)


def _selection_via_text_pattern(control, *, query_id=None) -> tuple[SelectionStatus, str]:
    """文档 / 富文本 / 输入框：TextPattern.GetSelection 拿选中区间的文字。

    返回三态：
      - 无 TextPattern（pattern 为 None / 取 pattern 抛异常）→ NO_TEXT_PATTERN，
        交给调用方走 Ctrl+C 兜底（Canvas 网页、内置 PDF、自绘控件等）。
      - 有 TextPattern 但选区为空 → EMPTY_SELECTION，真没选中（切标签等），静默。
      - 取到非空文字 → HAS_TEXT。

    不用 ValuePattern 兜底——它返回控件的**全部**内容而非选区，会把没选中的
    部分也带出来，造成错误取词。宁可此处取不到（漏弹），不可取错。
    """
    query_id = query_id or f"text-{time.perf_counter_ns():x}"
    try:
        pattern = _diagnostic_call(query_id, "text_pattern", lambda: _get_text_pattern(control))
    except Exception:
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    if pattern is None:
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    try:
        ranges = _diagnostic_call(query_id, "selection_ranges", pattern.GetSelection)
    except Exception:
        # pattern 在但取选区失败，仍属「读不到」，给兜底机会。
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    if not ranges:
        return (SelectionStatus.EMPTY_SELECTION, "")

    parts = []
    for index, rng in enumerate(ranges):
        try:
            parts.append(_diagnostic_call(
                query_id, f"range_text:{index}", lambda: rng.GetText(MAX_SELECTION_CHARS),
            ))
        except Exception:
            continue
    text = clean_selection("".join(parts))
    if not text:
        return (SelectionStatus.EMPTY_SELECTION, "")
    return (SelectionStatus.HAS_TEXT, text)
