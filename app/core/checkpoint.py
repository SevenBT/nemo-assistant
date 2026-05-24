"""
Checkpoint 持久化：在工具执行过程中保存中间状态，崩溃后可恢复。

存储位置：data/sessions/{session_id}.checkpoint.json
策略：每完成一个工具调用后写入 checkpoint，turn 正常结束后删除。
"""
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from app.core.config import SESSIONS_DIR


def _checkpoint_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.checkpoint.json"


def save_checkpoint(
    session_id: str,
    messages: list[dict],
    assistant_msg: dict,
    completed_results: list[dict],
    pending_tool_calls: list[dict],
) -> None:
    """原子写入 checkpoint 文件。

    Args:
        session_id: 会话 ID
        messages: 当前累积的 API 消息（不含本轮 assistant）
        assistant_msg: 本轮 assistant 消息（含 tool_calls）
        completed_results: 已完成的工具结果消息
        pending_tool_calls: 尚未执行的工具调用
    """
    payload: dict[str, Any] = {
        "messages": messages,
        "assistant_msg": assistant_msg,
        "completed_results": completed_results,
        "pending_tool_calls": pending_tool_calls,
    }
    path = _checkpoint_path(session_id)
    # 原子写入：先写临时文件，再 rename
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        # 写入失败时清理临时文件
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def restore_checkpoint(session_id: str) -> dict | None:
    """恢复 checkpoint，返回 payload 或 None。

    对未完成的工具调用生成错误结果。
    恢复后自动删除 checkpoint 文件。
    """
    path = _checkpoint_path(session_id)
    if not path.exists():
        return None

    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (json.JSONDecodeError, OSError):
        # 文件损坏，重命名保留
        corrupt = path.with_suffix(f".corrupt-{int(os.path.getmtime(path))}")
        path.rename(corrupt)
        return None

    # 为未完成的工具调用生成错误结果
    error_results = []
    for tc in payload.get("pending_tool_calls", []):
        error_results.append({
            "role": "tool",
            "tool_call_id": tc["id"],
            "content": json.dumps(
                {"error": "任务中断，该工具未执行完成。"},
                ensure_ascii=False,
            ),
        })

    payload["error_results"] = error_results

    # 清理 checkpoint 文件
    clear_checkpoint(session_id)
    return payload


def clear_checkpoint(session_id: str) -> None:
    """删除 checkpoint 文件（turn 正常结束后调用）。"""
    path = _checkpoint_path(session_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def has_checkpoint(session_id: str) -> bool:
    """检查是否存在未恢复的 checkpoint。"""
    return _checkpoint_path(session_id).exists()
