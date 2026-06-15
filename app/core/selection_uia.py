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
都支持；少数自绘控件 / 老 Electron / 远程桌面内的内容查不到选区，这种情况
漏弹（漏弹而非误弹——宁可少弹也不在切标签时乱弹）。

COM 线程注意：本函数会在鼠标钩子线程被调用。uiautomation 库按线程自动
CoInitialize，查到的文字由调用方 marshal 回 Qt 主线程再用。
"""
from __future__ import annotations

from app.core.selection_capture import MAX_SELECTION_CHARS, clean_selection

try:
    import uiautomation as _auto
    _UIA_OK = True
except Exception:
    # ImportError（未安装）或导入期 COM/comtypes 异常都视为不可用，退回旧路径。
    _UIA_OK = False


def is_available() -> bool:
    """UIA 是否可用。不可用时调用方应退回 Ctrl+C 取词路径。"""
    return _UIA_OK


def get_selected_text() -> str:
    """查询前台聚焦控件当前选中的文字。取不到返回空串。

    纯查询：不发按键、不读写剪贴板、不改变焦点。
    """
    if not _UIA_OK:
        return ""
    try:
        control = _auto.GetFocusedControl()
    except Exception:
        return ""
    if control is None:
        return ""
    return clean_selection(_selection_via_text_pattern(control))


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


def _selection_via_text_pattern(control) -> str:
    """文档 / 富文本 / 输入框：TextPattern.GetSelection 拿选中区间的文字。

    不用 ValuePattern 兜底——它返回控件的**全部**内容而非选区，会把没选中的
    部分也带出来，造成错误取词。宁可此处取不到（漏弹），不可取错。
    """
    try:
        pattern = control.GetTextPattern()
    except Exception:
        return ""
    if pattern is None:
        return ""
    try:
        ranges = pattern.GetSelection()
    except Exception:
        return ""
    if not ranges:
        return ""

    parts = []
    for rng in ranges:
        try:
            parts.append(rng.GetText(MAX_SELECTION_CHARS))
        except Exception:
            continue
    return "".join(parts)
