"""剪贴板劫持的共享基建 —— 取词（capture）与回填（inject）共用。

Windows 没有读写其他应用选区的通用 API，业界事实标准是劫持系统剪贴板：
模拟 Ctrl+C 让前台应用把选区写进剪贴板（取词），或先写好内容再模拟 Ctrl+V
让前台应用粘进去（回填）。两条路都必须在用完后把用户原本的剪贴板内容原样还原。

本模块抽出两者共享的三块逻辑，避免在 capture / inject 间复制粘贴漂移：
  1. 修饰键释放：热键（如 ctrl+alt+e）触发时 ctrl/alt 还按着，直接 send
     ctrl+c / ctrl+v 会被污染成 ctrl+alt+c。劫持前必须先 release 修饰键。
  2. 剪贴板深拷贝备份：逐 format 拷到新建 QMimeData，保全 text/html/图片/文件。
  3. 备份还原：备份为空则清空，避免残留劫持内容。
"""
from __future__ import annotations

from PyQt6.QtCore import QMimeData

try:
    import keyboard as _kb
    _KB_OK = True
except ImportError:
    _KB_OK = False

# 触发热键可能按住的修饰键，劫持剪贴板前全部释放。
MODIFIERS = ("ctrl", "alt", "shift", "windows")


def keyboard_available() -> bool:
    """keyboard 库是否可用（导入成功）。不可用时取词/回填都无法进行。"""
    return _KB_OK


def release_modifiers() -> None:
    """释放所有可能残留的修饰键，否则合成的 ctrl+c / ctrl+v 会被污染。"""
    if not _KB_OK:
        return
    for mod in MODIFIERS:
        try:
            _kb.release(mod)
        except Exception:
            pass


def send_hotkey(combo: str) -> None:
    """合成一次全局按键（如 "ctrl+c" / "ctrl+v"）。keyboard 不可用时静默。"""
    if not _KB_OK:
        return
    _kb.send(combo)


def backup_clipboard(clipboard) -> QMimeData:
    """深拷贝当前剪贴板的所有格式，供劫持后原样还原。

    不能直接持有 clipboard.mimeData() 返回的对象（生命周期由 Qt 管理，会随
    剪贴板变化失效）。逐 format 拷到新建的 QMimeData：text/html、图片、文件
    列表、富文本等都能完整保留，避免劫持后把用户原本复制的图片/文件退化成
    纯文本甚至丢失。
    """
    backup = QMimeData()
    source = clipboard.mimeData()
    if source is None:
        return backup
    try:
        for fmt in source.formats():
            backup.setData(fmt, source.data(fmt))
    except Exception:
        # 极端情况下某格式读取失败，至少保住已拷到的部分。
        pass
    return backup


def restore_clipboard(clipboard, backup: QMimeData) -> None:
    """还原剪贴板。备份为空（原本就没内容）时清空，避免残留劫持内容。"""
    if backup.formats():
        clipboard.setMimeData(backup)
    else:
        clipboard.clear()
