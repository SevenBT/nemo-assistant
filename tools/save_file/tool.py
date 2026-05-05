import json
import os
import sys
from pathlib import Path


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    params = payload.get("params", {})

    filename = params.get("filename", "").strip()
    content = params.get("content", "")
    save_dir = params.get("save_dir", "").strip()

    if not filename:
        print(json.dumps({"status": "error", "data": {"message": "filename is required"}}))
        return

    # Strip any path components — only keep the basename
    filename = Path(filename).name
    if not filename:
        print(json.dumps({"status": "error", "data": {"message": "invalid filename"}}))
        return

    target_dir = Path(save_dir) if save_dir else Path.home() / "Downloads"
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / filename

    # Avoid silent overwrite: append counter suffix
    counter = 1
    stem = file_path.stem
    suffix = file_path.suffix
    while file_path.exists():
        file_path = target_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    file_path.write_text(content, encoding="utf-8")

    try:
        os.startfile(str(target_dir))
    except Exception:
        pass

    print(
        json.dumps(
            {
                "status": "success",
                "data": {
                    "path": str(file_path),
                    "filename": file_path.name,
                    "size_bytes": len(content.encode("utf-8")),
                    "message": f"已保存到 {file_path}",
                },
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
