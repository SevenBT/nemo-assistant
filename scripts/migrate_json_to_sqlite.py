"""
JSON 笔记数据迁移到 SQLite 数据库。

读取 data/notes/*.json 和 data/notes/trash/*.json 文件，
转换为 SQLite 数据库格式并导入。

用法：
    python migrate_json_to_sqlite.py [--force] [--keep-json]

选项：
    --force      强制覆盖现有数据库，不询问
    --keep-json  保留原 JSON 文件，不删除
"""

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

# 设置 Windows 控制台编码为 UTF-8
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import DATA_DIR, NOTES_DIR, TRASH_DIR
from app.core.db_manager import DatabaseManager


def timestamp_to_iso(timestamp: float) -> str:
    """
    将 Unix 时间戳转换为 ISO 8601 格式字符串。

    Args:
        timestamp: Unix 时间戳（秒）

    Returns:
        str: ISO 8601 格式的时间字符串
    """
    return datetime.fromtimestamp(timestamp).isoformat()


def migrate_notes(force: bool = False, keep_json: bool = False):
    """
    执行笔记数据迁移。

    Args:
        force: 强制覆盖现有数据库
        keep_json: 保留原 JSON 文件
    """
    db_path = DATA_DIR / "notes.db"
    backup_dir = DATA_DIR / "backup_json"

    # 检查数据库是否已存在
    if db_path.exists():
        if not force:
            response = input(f"数据库 {db_path} 已存在，是否覆盖？(y/N): ")
            if response.lower() != "y":
                print("迁移已取消。")
                return
        db_path.unlink()
        print(f"已删除现有数据库：{db_path}")

    # 创建数据库
    db = DatabaseManager(db_path)
    print(f"已创建数据库：{db_path}")

    # 统计信息
    total_notes = 0
    total_trash = 0
    errors = []

    # 迁移正常笔记
    print("\n正在迁移笔记...")
    for json_path in NOTES_DIR.glob("*.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            with db.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO notes (
                        title, content, note_type,
                        created_at, updated_at,
                        is_deleted, is_completed, is_pinned
                    ) VALUES (?, ?, ?, ?, ?, 0, 0, 0)
                    """,
                    (
                        data.get("title", "新笔记"),
                        data.get("content", ""),
                        "note",
                        timestamp_to_iso(data.get("created_at", 0)),
                        timestamp_to_iso(data.get("updated_at", 0)),
                    ),
                )
                conn.commit()
            total_notes += 1
            print(f"  [OK] {json_path.name}")
        except Exception as e:
            errors.append(f"{json_path.name}: {e}")
            print(f"  [FAIL] {json_path.name}: {e}")

    # 迁移回收站笔记
    print("\n正在迁移回收站...")
    for json_path in TRASH_DIR.glob("*.json"):
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            with db.get_connection() as conn:
                now = timestamp_to_iso(data.get("updated_at", 0))
                conn.execute(
                    """
                    INSERT INTO notes (
                        title, content, note_type,
                        created_at, updated_at, deleted_at,
                        is_deleted, is_completed, is_pinned
                    ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0)
                    """,
                    (
                        data.get("title", "新笔记"),
                        data.get("content", ""),
                        "note",
                        timestamp_to_iso(data.get("created_at", 0)),
                        now,
                        now,
                    ),
                )
                conn.commit()
            total_trash += 1
            print(f"  [OK] {json_path.name}")
        except Exception as e:
            errors.append(f"trash/{json_path.name}: {e}")
            print(f"  [FAIL] {json_path.name}: {e}")

    # 备份 JSON 文件
    print("\n正在备份 JSON 文件...")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 备份笔记
    notes_backup = backup_dir / "notes"
    notes_backup.mkdir(exist_ok=True)
    for json_path in NOTES_DIR.glob("*.json"):
        shutil.copy2(json_path, notes_backup / json_path.name)

    # 备份回收站
    trash_backup = backup_dir / "trash"
    trash_backup.mkdir(exist_ok=True)
    for json_path in TRASH_DIR.glob("*.json"):
        shutil.copy2(json_path, trash_backup / json_path.name)

    print(f"已备份到：{backup_dir}")

    # 打印迁移结果
    print("\n" + "=" * 50)
    print("迁移完成！")
    print(f"  成功迁移笔记：{total_notes} 个")
    print(f"  成功迁移回收站：{total_trash} 个")
    if errors:
        print(f"  失败：{len(errors)} 个")
        print("\n失败详情：")
        for error in errors:
            print(f"    - {error}")
    print("=" * 50)

    # 询问是否删除 JSON 文件
    if not keep_json:
        response = input("\n是否删除原 JSON 文件？(y/N): ")
        if response.lower() == "y":
            for json_path in NOTES_DIR.glob("*.json"):
                json_path.unlink()
            for json_path in TRASH_DIR.glob("*.json"):
                json_path.unlink()
            print("已删除所有 JSON 文件。")
        else:
            print("保留 JSON 文件。")
    else:
        print("\n保留 JSON 文件（--keep-json 选项）。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="迁移 JSON 笔记到 SQLite 数据库")
    parser.add_argument("--force", action="store_true", help="强制覆盖现有数据库")
    parser.add_argument("--keep-json", action="store_true", help="保留原 JSON 文件")
    args = parser.parse_args()

    migrate_notes(force=args.force, keep_json=args.keep_json)

