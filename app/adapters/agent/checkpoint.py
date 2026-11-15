"""File checkpoints with an explicit directory and the existing disk format."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from app.agent.contracts import CheckpointSnapshot


class FileCheckpointStore:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, session_id: str) -> Path:
        return self.directory / f"{session_id}.checkpoint.json"

    def save(self, session_id: str, snapshot: CheckpointSnapshot) -> None:
        path = self._path(session_id)
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(snapshot), stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def restore(self, session_id: str) -> dict | None:
        """Read old/new checkpoints; unresolved calls become interruption results."""
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
        except (json.JSONDecodeError, OSError):
            corrupt = path.with_suffix(f".corrupt-{int(os.path.getmtime(path))}")
            path.rename(corrupt)
            return None
        payload["error_results"] = [
            {
                "role": "tool", "tool_call_id": call["id"],
                "content": json.dumps(
                    {"error": "任务中断，该工具未执行完成。"}, ensure_ascii=False,
                ),
            }
            for call in payload.get("pending_tool_calls", [])
        ]
        self.clear(session_id)
        return payload

    def clear(self, session_id: str) -> None:
        try:
            self._path(session_id).unlink(missing_ok=True)
        except OSError:
            pass

    def has_checkpoint(self, session_id: str) -> bool:
        return self._path(session_id).exists()
