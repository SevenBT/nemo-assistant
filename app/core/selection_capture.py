"""划词取词 — 通过剪贴板劫持拿到任意应用中选中的文字。

Windows 没有读取其他应用选区的通用 API。业界事实标准（PowerToys、各类
划词翻译工具）的做法是：模拟 Ctrl+C 让前台应用把选区写进系统剪贴板，
读出后再还原原始剪贴板内容。

两个必须处理的坑：
  1. 修饰键残留：热键（如 ctrl+alt+e）触发时 ctrl/alt 还按着，直接 send
     ctrl+c 会变成 ctrl+alt+c。必须先 release 修饰键。
  2. 复制是异步的：ctrl+c 发给前台应用后由它异步写剪贴板，不能立刻读，
     必须轮询等待剪贴板变化。

纯逻辑（清洗/截断/判定）与副作用（按键、读写剪贴板）分离，便于单测。
"""
from __future__ import annotations

import time

from PyQt6.QtWidgets import QApplication

from app.core.clipboard_util import (
    backup_clipboard as _backup_clipboard,
    keyboard_available,
    release_modifiers,
    restore_clipboard as _restore_clipboard,
    send_hotkey,
)

# 取词上限：超长选区截断，避免爆 token。8000 字约够覆盖整页文档。
MAX_SELECTION_CHARS = 8000

# 轮询参数：复制是异步的，等剪贴板出现新内容。
_POLL_TIMEOUT_MS = 400
_POLL_INTERVAL_MS = 30


def clean_selection(text: str) -> str:
    """清洗取到的文字：去首尾空白，超长截断。

    纯函数，便于单测。返回空串表示「无有效选中」。
    """
    if not text:
        return ""
    cleaned = text.strip()
    if len(cleaned) > MAX_SELECTION_CHARS:
        cleaned = cleaned[:MAX_SELECTION_CHARS]
    return cleaned


def is_valid_selection(captured: str) -> bool:
    """判定本次 Ctrl+C 是否真的取到了新选区。

    纯函数，便于单测。取词前已 clipboard.clear()，所以「清空后出现非空内容」
    即说明 Ctrl+C 产生了新复制——选中了文字。不再与劫持前的剪贴板内容比较：
    那样会把「选中的词恰好等于上次复制的词」误判为没选中（漏弹）。
    """
    return bool(captured)


def capture_selection() -> str:
    """抓取当前选中的文字。必须在主线程、且**源应用仍持有焦点时**调用。

    ★ 时机至关重要：必须在触发的第一时间调用（热键刚按下 / 鼠标刚松开），
    此时被选中文字的源应用还是前台窗口，Ctrl+C 才会发给它。一旦我们的浮窗
    弹出并被点击，焦点就被抢走，Ctrl+C 会发给我们自己的 app，取不到选区。

    返回清洗后的选中文字；若未取到（没选中 / 复制失败 / keyboard 不可用）
    返回空串。原始剪贴板内容（含图片/文件/富文本等所有格式）在取词后立即
    同步还原。
    """
    if not keyboard_available():
        return ""

    clipboard = QApplication.clipboard()
    backup = _backup_clipboard(clipboard)

    # 坑1：释放热键残留的修饰键，否则 ctrl+c 被污染成 ctrl+alt+c。
    release_modifiers()

    # 清空剪贴板，使「内容是否变化」的判定更可靠。
    clipboard.clear()

    # 坑3：我们合成的是**全局** Ctrl+C，无法预知它落到哪个窗口。若此刻前台正好是
    # 运行本应用的控制台（开发期从命令行启动、又恰好把焦点切过去），这个 Ctrl+C
    # 会被控制台解释成中断信号，给附着的 Python 进程发 SIGINT，在 time.sleep 处抛
    # KeyboardInterrupt 打断整个 app。这里显式吞掉它：还原剪贴板、静默返回，
    # 绝不让取词的副作用波及主进程存活。
    try:
        send_hotkey("ctrl+c")
        # 坑2：复制是异步的，轮询等待剪贴板出现内容。
        captured = _poll_clipboard(clipboard)
    except KeyboardInterrupt:
        _restore_clipboard(clipboard, backup)
        return ""
    except Exception:
        _restore_clipboard(clipboard, backup)
        return ""

    cleaned = clean_selection(captured)

    # 取词完毕，立即同步还原原始剪贴板（不用延迟定时器：上一次的延迟还原会
    # 在下一次取词的轮询窗口里把旧内容塞回剪贴板，导致取到「上次的词」）。
    _restore_clipboard(clipboard, backup)

    if is_valid_selection(cleaned):
        return cleaned
    return ""


def _poll_clipboard(clipboard) -> str:
    """轮询剪贴板直到出现非空内容或超时。返回取到的原始文本。"""
    deadline = time.monotonic() + _POLL_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        text = clipboard.text()
        if text:
            return text
        QApplication.processEvents()
        time.sleep(_POLL_INTERVAL_MS / 1000)
    return clipboard.text()
