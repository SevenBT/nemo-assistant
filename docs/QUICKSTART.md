# SQLite 迁移快速开始

## 一键迁移

```bash
# 1. 执行迁移（保留 JSON 备份）
python scripts/migrate_json_to_sqlite.py --force --keep-json

# 2. 验证迁移
python scripts/verify_migration.py

# 3. 运行完整测试
python scripts/test_note_manager.py
```

## 迁移结果

迁移成功后，你将看到：

```
已创建数据库：D:\claudecode-projects\assistant\data\notes.db

正在迁移笔记...
  [OK] xxx.json
  [OK] xxx.json

正在迁移回收站...

正在备份 JSON 文件...
已备份到：D:\claudecode-projects\assistant\data\backup_json

==================================================
迁移完成！
  成功迁移笔记：X 个
  成功迁移回收站：X 个
==================================================
```

## 验证结果

验证成功后，你将看到：

```
[OK] 数据库连接正常
[OK] 笔记数量: X
[OK] int ID 查询: xxx
[OK] str ID 查询: xxx
[OK] 固定笔记功能: 0 个
[OK] 回收站功能: 0 个
[OK] 预览列表功能: X 个

所有功能验证通过！
```

## 主要变更

1. **数据存储**: JSON 文件 → SQLite 数据库
2. **Note.id**: `str (UUID)` → `int (自增)`
3. **时间格式**: `float (Unix timestamp)` → `str (ISO 8601)`
4. **新增功能**: 桌面固定、标签、待办、软删除

## 向后兼容

- NoteManager 接口保持不变
- 支持 `str` 和 `int` 类型的 note_id
- 现有 UI 代码无需修改

## 文件位置

- 数据库：`data/notes.db`
- JSON 备份：`data/backup_json/`
- 旧版 NoteManager：`app/core/note_manager_old.py`

## 详细文档

查看完整迁移指南：`docs/MIGRATION.md`

## 回滚

如果需要回滚到 JSON 存储：

```bash
# 恢复旧版 NoteManager
mv app/core/note_manager.py app/core/note_manager_sqlite.py
mv app/core/note_manager_old.py app/core/note_manager.py

# 删除数据库
rm data/notes.db

# 恢复 JSON 文件（如果已删除）
cp -r data/backup_json/notes/* data/notes/
cp -r data/backup_json/trash/* data/notes/trash/
```

## 下一步

- [ ] 启动应用测试基本功能
- [ ] 实现 UI 层的桌面固定功能
- [ ] 实现标签管理 UI
- [ ] 实现待办事项功能
- [ ] 实现笔记搜索

## 问题排查

如果遇到问题：

1. 检查 Python 版本（需要 3.10+）
2. 确保 `data` 目录存在且有写权限
3. 查看错误日志
4. 运行 `python scripts/test_note_manager.py` 诊断

## 联系支持

如有问题，请查看：
- `docs/MIGRATION.md` - 完整迁移指南
- `docs/MIGRATION_SUMMARY.md` - 迁移总结
