"""划词回填 —— 把 AI 改写结果写回前台应用的选区（取词的镜像操作）。

取词是「备份剪贴板 → Ctrl+C → 读 → 立即还原」；回填反过来：
「备份剪贴板 → 写入新内容 → Ctrl+V → **延迟**还原」。

★ 必须在源应用仍持有焦点、选区仍高亮时调用。划词浮标与结果气泡都是
  WS_EX_NOACTIVATE（不抢焦点），所以用户点气泡上「替换原文」那一刻，
  源应用仍是前台、选中文字仍高亮，Ctrl+V 会落到源应用、覆盖掉选区。

两个与取词不同的关键点：
  1. **还原必须延迟**：粘贴是异步的，源应用还没读到剪贴板就被还原回旧内容，
     会粘成旧剪贴板内容。故 Ctrl+V 后延迟 ~300ms 再还原。
  2. **回填前校验选区未变**（可选，默认开）：等 AI 期间用户可能点走、选区已失，
     此时盲粘会覆盖错误位置。粘前先静默 Ctrl+C 取一次当前选区与原文比对，
     不符则放弃回填，交由调用方兜底（把结果留在剪贴板 + 提示手动粘贴）。

纯逻辑（结果清洗、选区校验判定）与副作用（按键、读写剪贴板）分离，便于单测。
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from app.core.clipboard_util import (
    backup_clipboard,
    keyboard_available,
    release_modifiers,
    restore_clipboard,
    send_hotkey,
)
from app.core.selection_capture import capture_selection

logger = logging.getLogger(__name__)

# 粘贴是异步的，延迟这么久再还原剪贴板，给源应用留出读取窗口。
_RESTORE_DELAY_MS = 300


def strip_ai_preamble(text: str) -> str:
    """剥离 AI 回复里常见的「好的，这是改写后的：」之类前缀/包裹。

    纯函数，便于单测。回填要求只回填正文，模型偶尔仍带寒暄或用代码块包裹，
    这里做轻量清洗：去首尾空白；若整体被单层 ``` 代码块包裹则脱壳。
    不做激进的句子级裁剪（可能误删正文），仅处理高频且安全的包裹形态。
    """
    if not text:
        return ""
    cleaned = text.strip()
    # 整体被三引号代码块包裹：```lang\n...\n``` → 取中间正文
    if cleaned.startswith("```") and cleaned.endswith("```") and len(cleaned) >= 6:
        inner = cleaned[3:-3]
        # 去掉可能的语言标注首行
        if "\n" in inner:
            first, rest = inner.split("\n", 1)
            if first.strip() and " " not in first.strip():
                inner = rest
        cleaned = inner.strip()
    return cleaned


def selection_unchanged(original: str, current: str) -> bool:
    """判定重新取到的选区是否与回填前的原文一致。

    纯函数，便于单测。两者 strip 后相等才算未变；current 为空（没取到）
    返回 False——表示「无法确认相等」，**不等于「选区已变」**。调用方据此
    决定：仅当取到了不同的非空文字才放弃粘贴，取到空则不阻断（见
    replace_selection 中的用法）。
    """
    if not current:
        return False
    return original.strip() == current.strip()


def replace_selection(new_text: str, *, original: str = "", verify: bool = True) -> bool:
    """把 new_text 写回当前前台应用的选区（模拟 Ctrl+V 覆盖选中文字）。

    Args:
        new_text: 要写回的改写结果。
        original: 回填前的原始选中文字，用于 verify 校验。
        verify: 为真且 original 非空时，粘贴前先取一次当前选区与 original 比对，
            不符则放弃回填（防止等 AI 期间用户点走、粘到错误位置）。

    Returns:
        True  — 已发出粘贴指令（选区校验通过或未启用校验）。
        False — 前置条件不满足（keyboard 不可用 / 选区已变 / 写入异常），
                调用方应走兜底（把结果留在剪贴板并提示手动粘贴）。

    注意：返回 True 只表示「已发出 Ctrl+V」，无法 100% 确认源应用真的粘成功
    （只读控件可能忽略粘贴）。故调用方仍应提供「复制」兜底入口。
    """
    if not keyboard_available():
        logger.warning("回填：keyboard 不可用")
        return False

    text = new_text.strip()
    if not text:
        return False

    # 选区校验：capture_selection 内部会自行备份/还原剪贴板，必须在我们写入
    # new_text **之前**做，否则会把待回填内容读进来误判。
    #
    # ★ 只有「重新取到了不同的非空文字」才判定选区已变、放弃粘贴。取到空
    # （current 为空）在「源应用就是本 app 自己的编辑器」等场景很常见——那次
    # 校验性 Ctrl+C 没取到，并不代表用户点走了选区（气泡 NOACTIVATE 不抢焦点，
    # 选区通常仍在）。此时无法校验，不阻断、照常粘贴；否则会误杀正常回填
    # （表现为「无法替换」）。真正危险的只有「取到别的非空文字」。
    if verify and original.strip():
        current = capture_selection()
        if current and not selection_unchanged(original, current):
            logger.info("回填：选区已变（取到不同文字），放弃粘贴")
            return False

    clipboard = QApplication.clipboard()
    backup = backup_clipboard(clipboard)

    # 释放热键残留的修饰键，否则 ctrl+v 被污染成 ctrl+alt+v。
    release_modifiers()

    # 全局 Ctrl+V 若落到运行本应用的控制台，会被解释成中断信号（SIGINT）→
    # KeyboardInterrupt。与取词一致地兜底：还原剪贴板、静默返回 False。
    try:
        clipboard.setText(text)
        send_hotkey("ctrl+v")
    except KeyboardInterrupt:
        restore_clipboard(clipboard, backup)
        return False
    except Exception as e:  # pragma: no cover - 防御性
        logger.error("回填：粘贴失败 %s", e)
        restore_clipboard(clipboard, backup)
        return False

    # 粘贴是异步的：延迟还原，给源应用留出读取剪贴板的窗口。立即还原会让
    # 源应用粘到旧剪贴板内容。
    QTimer.singleShot(
        _RESTORE_DELAY_MS, lambda: restore_clipboard(clipboard, backup)
    )
    return True
