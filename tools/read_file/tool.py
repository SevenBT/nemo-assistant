import json
import sys
from pathlib import Path

_MAX_DEFAULT = 50_000


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    raw_path = params.get("file_path", "").strip()
    max_chars = int(params.get("max_chars", _MAX_DEFAULT))

    if not raw_path:
        print(json.dumps({"status": "error", "data": {"message": "file_path is required"}}))
        return

    path = Path(raw_path).expanduser()

    if not path.exists():
        print(
            json.dumps(
                {"status": "error", "data": {"message": f"文件不存在: {path}"}},
                ensure_ascii=False,
            )
        )
        return

    if not path.is_file():
        print(
            json.dumps(
                {"status": "error", "data": {"message": f"路径不是文件: {path}"}},
                ensure_ascii=False,
            )
        )
        return

    file_size = path.stat().st_size

    content = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            content = path.read_text(encoding=enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue

    if content is None:
        print(
            json.dumps(
                {"status": "error", "data": {"message": "无法解码文件，可能是二进制文件"}},
                ensure_ascii=False,
            )
        )
        return

    truncated = len(content) > max_chars
    if truncated:
        content = content[:max_chars]

    print(
        json.dumps(
            {
                "status": "success",
                "data": {
                    "path": str(path),
                    "filename": path.name,
                    "size_bytes": file_size,
                    "content": content,
                    "truncated": truncated,
                    "chars_read": len(content),
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
