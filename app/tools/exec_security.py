"""
命令执行安全策略 — deny patterns 和路径校验。

职责：
  - 维护危险命令模式列表
  - 检查命令是否匹配危险模式
  - 提供统一的安全检查接口
"""
from __future__ import annotations

import re

# 危险命令模式（正则），匹配到的命令需要用户确认
_DENY_PATTERNS: list[str] = [
    # 递归删除
    r"rm\s+(-[a-zA-Z]*r[a-zA-Z]*|--recursive)",
    r"rmdir\s+/s",
    r"del\s+/[fqs]",
    # 磁盘格式化
    r"\bformat\s+[a-zA-Z]:",
    r"\bmkfs\b",
    r"\bdiskpart\b",
    # 系统关机/重启
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    # Windows 注册表危险操作
    r"reg\s+delete",
    # fork bomb
    r":\(\)\s*\{",
    # 覆盖磁盘设备
    r">\s*/dev/sd",
    r"\bdd\s+if=",
    # 强制结束关键进程
    r"taskkill\s+/f\s+/im\s+(explorer|csrss|winlogon|svchost)",
    r"kill\s+-9\s+1\b",
]

_COMPILED_PATTERNS: list[re.Pattern] = [
    re.compile(p, re.IGNORECASE) for p in _DENY_PATTERNS
]


def is_dangerous_command(command: str) -> tuple[bool, str]:
    """
    检查命令是否匹配危险模式。

    Returns:
        (is_dangerous, matched_pattern_description)
    """
    for i, pattern in enumerate(_COMPILED_PATTERNS):
        if pattern.search(command):
            return True, _DENY_PATTERNS[i]
    return False, ""
