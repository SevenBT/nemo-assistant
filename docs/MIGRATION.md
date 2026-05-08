# SQLite 数据库迁移指南

## 概述

本次迁移将笔记存储从 JSON 文件迁移到 SQLite 数据库，以支持更强大的功能（标签、搜索、待办等）。

## 主要变更

### 1. 数据模型变更

- **Note.id**: `str (UUID)` → `int (自增)`
- **时间字段**: `float (Unix timestamp)` → `str (ISO 8601)`
- **新增字段**:
  - `note_type`: 笔记类型（note | todo | daily）
  - `priority`: 优先级（P1 | P2 | P3）
  - `due_date`: 截止日期
  - `recurrence`: 重复规则
  - `is_completed`: 是否完成
  - `is_deleted`: 是否删除（软删除）
  - `is_pinned`: 是否钉到桌面
  - `pin_position_x`, `pin_position_y`: 浮窗位置
  - `tags`: 标签列表

### 2. 新增功能

- **桌面固定**: 将笔记钉到桌面作为浮窗显示
- **标签系统**: 支持多标签分类
- **待办事项**: 支持待办类型笔记
- **软删除**: 删除的笔记进入回收站，可恢复

### 3. 向后兼容

- NoteManager 的公开方法签名保持不变
- 支持 `str` 和 `int` 类型的 note_id（自动转换）
- 现有 UI 代码无需修改

## 迁移步骤

### 1. 备份数据

```bash
# 备份整个 data 目录
cp -r data data_backup_$(date +%Y%m%d)
```

### 2. 运行迁移脚本

```bash
# 查看帮助
python scripts/migrate_json_to_sqlite.py --help

# 执行迁移（会询问是否覆盖和删除 JSON）
python scripts/migrate_json_to_sqlite.py

# 强制覆盖现有数据库，保留 JSON 文件
python scripts/migrate_json_to_sqlite.py --force --keep-json
```

### 3. 验证迁移结果

```bash
# 运行测试脚本
python scripts/test_note_manager.py
```

### 4. 测试应用

启动应用，验证以下功能：
- [ ] 笔记列表显示正常
- [ ] 创建新笔记
- [ ] 编辑笔记
- [ ] 删除笔记
- [ ] 回收站功能
- [ ] 恢复笔记

## 文件结构

```
app/
├── core/
│   ├── db_manager.py          # 数据库管理器（新增）
│   ├── note_manager.py        # 笔记管理器（重写）
│   └── note_manager_old.py   # 旧版本备份
├── models/
│   └── note.py                # Note 模型（扩展）
scripts/
├── migrate_json_to_sqlite.py  # 迁移脚本
└── test_note_manager.py       # 测试脚本
data/
├── notes.db                   # SQLite 数据库
├── backup_json/               # JSON 备份
│   ├── notes/
│   └── trash/
└── notes/                     # 原 JSON 文件（可选保留）
```

## 数据库结构

### notes 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| title | TEXT | 标题 |
| content | TEXT | 内容 |
| note_type | TEXT | 类型（note/todo/daily） |
| priority | TEXT | 优先级（P1/P2/P3） |
| due_date | TEXT | 截止日期 |
| recurrence | TEXT | 重复规则 |
| is_completed | INTEGER | 是否完成 |
| is_deleted | INTEGER | 是否删除 |
| is_pinned | INTEGER | 是否固定 |
| pin_position_x | INTEGER | 浮窗 X 坐标 |
| pin_position_y | INTEGER | 浮窗 Y 坐标 |
| created_at | TEXT | 创建时间（ISO 8601） |
| updated_at | TEXT | 更新时间（ISO 8601） |
| deleted_at | TEXT | 删除时间（ISO 8601） |

### tags 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| name | TEXT | 标签名（唯一） |
| created_at | TEXT | 创建时间 |

### note_tags 表（多对多关系）

| 字段 | 类型 | 说明 |
|------|------|------|
| note_id | INTEGER | 笔记 ID |
| tag_id | INTEGER | 标签 ID |

### attachments 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键，自增 |
| note_id | INTEGER | 笔记 ID |
| file_path | TEXT | 文件路径 |
| file_type | TEXT | 文件类型 |
| file_size | INTEGER | 文件大小 |
| created_at | TEXT | 创建时间 |

## API 变更

### NoteManager 新增方法

```python
# 获取固定笔记
get_pinned_notes() -> list[Note]

# 固定笔记到桌面
pin_note(note_id: Union[str, int], x: int, y: int)

# 取消固定
unpin_note(note_id: Union[str, int])

# 更新浮窗位置
update_pin_position(note_id: Union[str, int], x: int, y: int)
```

### 兼容性说明

所有接受 `note_id` 的方法现在都支持 `str` 或 `int` 类型：

```python
# 以下两种方式都有效
note = nm.get(1)
note = nm.get("1")
```

## 回滚方案

如果迁移后出现问题，可以回滚到 JSON 存储：

```bash
# 1. 恢复旧版 NoteManager
mv app/core/note_manager.py app/core/note_manager_sqlite.py
mv app/core/note_manager_old.py app/core/note_manager.py

# 2. 删除数据库文件
rm data/notes.db

# 3. 恢复 JSON 文件（如果已删除）
cp -r data/backup_json/notes/* data/notes/
cp -r data/backup_json/trash/* data/notes/trash/
```

## 常见问题

### Q: 迁移后原 JSON 文件还需要吗？

A: 不需要。迁移脚本会自动备份到 `data/backup_json/`，可以安全删除原文件。

### Q: 如何查看数据库内容？

A: 使用 SQLite 客户端：

```bash
sqlite3 data/notes.db
.tables
SELECT * FROM notes;
```

### Q: 迁移失败怎么办？

A: 检查错误日志，确保：
- JSON 文件格式正确
- 有足够的磁盘空间
- 没有其他进程占用数据库文件

### Q: 可以重复运行迁移脚本吗？

A: 可以。使用 `--force` 参数会覆盖现有数据库。

## 下一步

- [ ] 实现标签管理 UI
- [ ] 实现待办事项功能
- [ ] 实现笔记搜索
- [ ] 实现桌面固定功能（UI 层）
- [ ] 添加数据导出功能
