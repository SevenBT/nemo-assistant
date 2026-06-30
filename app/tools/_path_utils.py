"""
路径安全工具 — 所有文件系统工具共用的路径校验和常量。

提供：
  - resolve_safe(): 将用户输入路径解析为绝对路径，确保在 workspace 内
  - is_binary(): 检测文件是否为二进制
  - IGNORE_DIRS: 遍历时跳过的目录集合
"""
from __future__ import annotations

from pathlib import Path

from app.i18n import t

# 文件遍历时跳过的目录
IGNORE_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv",
    "venv", ".idea", ".vs", ".vscode", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".tox", "egg-info",
})


def resolve_safe(path_str: str, workspace: Path) -> tuple[Path | None, str]:
    """
    将用户输入路径解析为绝对路径，确保在 workspace 内。

    支持：
      - 相对路径（相对于 workspace）
      - 空字符串或 "."（返回 workspace 本身）

    Returns:
        (resolved_path, error_message) — 成功时 error_message 为空字符串
    """
    ws = workspace.resolve()
    if not path_str or path_str == ".":
        return ws, ""
    try:
        target = (ws / path_str).resolve()
    except (OSError, ValueError) as e:
        return None, t("tool.path.msg.invalid_path", error=e)

    if not str(target).startswith(str(ws)):
        return None, t("tool.path.msg.out_of_workspace")

    return target, ""


def is_binary(path: Path) -> bool:
    """读取前 512 字节，含 \\x00 则视为二进制。"""
    try:
        chunk = path.read_bytes()[:512]
        return b"\x00" in chunk
    except OSError:
        return True
