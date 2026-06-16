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

from app.core.selection_capture import MAX_SELECTION_CHARS, clean_selection

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


def query_selection() -> tuple[SelectionStatus, str]:
    """查询前台聚焦控件当前选中的文字，返回三态结果。

    纯查询：不发按键、不读写剪贴板、不改变焦点。

    返回 (状态, 文字)。仅 HAS_TEXT 时文字非空；其余状态文字为空串。
    调用方据状态决定：HAS_TEXT 带文字弹窗；NO_TEXT_PATTERN/UNAVAILABLE
    弹窗但走 Ctrl+C 兜底取词；EMPTY_SELECTION/NO_FOCUS 静默不弹。
    """
    if not _UIA_OK:
        return (SelectionStatus.UNAVAILABLE, "")
    try:
        control = _auto.GetFocusedControl()
    except Exception:
        return (SelectionStatus.NO_FOCUS, "")
    if control is None:
        return (SelectionStatus.NO_FOCUS, "")
    return _selection_via_text_pattern(control)


def get_selection_bounds() -> tuple[int, int, int, int] | None:
    """查询前台控件当前选区的屏幕包围盒，用于定位浮标。

    返回 (left, top, right, bottom)，取**最后一个**选区矩形的底边（即
    选区末行的最下方）。取不到（UIA 不可用 / 控件不支持 BoundingRectangles
    / 无选区）返回 None，调用方退回鼠标坐标。

    纯查询：不按键、不读剪贴板、不改变焦点。
    """
    if not _UIA_OK:
        return None
    try:
        control = _auto.GetFocusedControl()
    except Exception:
        return None
    if control is None:
        return None
    try:
        pattern = control.GetTextPattern()
    except Exception:
        return None
    if pattern is None:
        return None
    try:
        ranges = pattern.GetSelection()
    except Exception:
        return None
    if not ranges:
        return None
    # 选区末行的底边位置：取最后一个 range 的最后一个矩形。
    last_range = ranges[-1]
    try:
        rects = last_range.BoundingRectangles
    except Exception:
        return None
    if not rects:
        return None
    rect = rects[-1]
    return (rect.left, rect.top, rect.right, rect.bottom)


def _selection_via_text_pattern(control) -> tuple[SelectionStatus, str]:
    """文档 / 富文本 / 输入框：TextPattern.GetSelection 拿选中区间的文字。

    返回三态：
      - 无 TextPattern（pattern 为 None / 取 pattern 抛异常）→ NO_TEXT_PATTERN，
        交给调用方走 Ctrl+C 兜底（Canvas 网页、内置 PDF、自绘控件等）。
      - 有 TextPattern 但选区为空 → EMPTY_SELECTION，真没选中（切标签等），静默。
      - 取到非空文字 → HAS_TEXT。

    不用 ValuePattern 兜底——它返回控件的**全部**内容而非选区，会把没选中的
    部分也带出来，造成错误取词。宁可此处取不到（漏弹），不可取错。
    """
    try:
        pattern = control.GetTextPattern()
    except Exception:
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    if pattern is None:
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    try:
        ranges = pattern.GetSelection()
    except Exception:
        # pattern 在但取选区失败，仍属「读不到」，给兜底机会。
        return (SelectionStatus.NO_TEXT_PATTERN, "")
    if not ranges:
        return (SelectionStatus.EMPTY_SELECTION, "")

    parts = []
    for rng in ranges:
        try:
            parts.append(rng.GetText(MAX_SELECTION_CHARS))
        except Exception:
            continue
    text = clean_selection("".join(parts))
    if not text:
        return (SelectionStatus.EMPTY_SELECTION, "")
    return (SelectionStatus.HAS_TEXT, text)
