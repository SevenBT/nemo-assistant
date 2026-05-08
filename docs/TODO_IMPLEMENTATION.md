# 待办功能实施总结

## 已完成的工作

### 1. 数据库层扩展（NoteManager）
**文件**: `app/core/note_manager.py`

新增方法：
- `get_notes_by_type(note_type: str)` - 按类型获取笔记，待办按优先级和日期排序
- `toggle_todo_completed(note_id)` - 切换待办完成状态
- `create()` - 扩展支持 `note_type` 参数
- `update()` - 扩展支持 `priority`, `due_date`, `recurrence` 参数

### 2. UI 组件

#### TodoItemWidget（待办列表项）
**文件**: `app/ui/components/todo_item_widget.py`

功能：
- Checkbox 切换完成状态
- 显示标题、优先级标签、截止日期
- 已完成显示删除线和灰色
- 过期待办红色高亮（⚠ 图标）
- 优先级颜色：P1 红色、P2 橙色、P3 蓝色

#### TodoEditor（待办编辑器）
**文件**: `app/ui/components/todo_editor.py`

功能：
- 标题输入框
- 内容编辑器（QTextEdit）
- 优先级选择器（无/P1/P2/P3）
- 截止日期选择器（可设置/清除）
- 重复设置（无/每日/每周/每月）
- 标签输入（复用 TagInput）

#### TodoPanel（待办面板）
**文件**: `app/ui/todo_panel.py`

功能：
- 待办列表显示（使用 TodoItemWidget）
- 创建新待办
- 编辑待办
- 切换完成状态（实时更新）
- 标签过滤
- 自动保存（1.5秒防抖）

### 3. 主窗口集成
**文件**: `app/ui/main_window.py`, `app/ui/title_bar.py`

修改：
- 标题栏添加"待办"按钮
- QStackedWidget 添加 TodoPanel（index 2）
- 页面索引调整：0=聊天, 1=笔记, 2=待办, 3=定时

### 4. 样式表
**文件**: `app/ui/style.py`

新增样式：
- `#todoCheckbox` - 复选框
- `#todoTitleLabel` - 标题标签
- `#todoTitleEdit` - 标题输入
- `#todoContentEdit` - 内容编辑器
- `#todoPriorityLabel` - 优先级标签
- `#todoDueLabel` - 截止日期标签
- `#todoPriorityCombo` - 优先级选择器
- `#todoRecurrenceCombo` - 重复选择器
- `#todoDueEdit` - 日期选择器
- `#todoClearDueBtn` - 清除/设置按钮

## 功能验证点

### 数据库操作
- [x] 创建待办（note_type='todo'）
- [x] 更新待办字段（priority, due_date, recurrence）
- [x] 按类型获取待办
- [x] 待办排序（未完成优先 → 优先级 → 截止日期）
- [x] 切换完成状态

### UI 功能
- [ ] 点击"待办"标签页显示所有待办
- [ ] 待办列表按优先级和日期正确排序
- [ ] 点击 Checkbox 切换完成状态，列表实时更新
- [ ] 创建新待办，设置优先级、日期、重复
- [ ] 保存后数据库字段正确写入
- [ ] 已完成待办显示删除线和灰色
- [ ] 过期待办高亮显示
- [ ] 优先级标签颜色正确
- [ ] 标签过滤功能正常

## 测试文件

- `test_todo_db.py` - 数据库操作测试（已通过）
- `test_todo.py` - UI 测试脚本

## 使用说明

### 创建待办
1. 点击标题栏"待办"按钮
2. 点击"新建待办"
3. 输入标题和内容
4. 设置优先级（可选）
5. 点击"设置"按钮设置截止日期（可选）
6. 选择重复模式（可选）
7. 添加标签（可选）
8. 自动保存

### 完成待办
- 点击待办项前的 Checkbox

### 编辑待办
- 点击待办项，在右侧编辑器修改

### 过滤待办
- 点击左侧标签过滤面板中的标签

## 注意事项

1. **重复任务**：当前只保存配置，不实现自动创建逻辑
2. **截止日期**：支持清除（允许无截止日期的待办）
3. **优先级**：可以为空（无优先级）
4. **完成状态**：切换后立即保存到数据库
5. **排序规则**：未完成优先 → 按优先级（P1>P2>P3>无）→ 按截止日期

## 下一步优化建议

1. 添加待办删除功能（移入回收站）
2. 添加待办右键菜单（复制、导出等）
3. 实现重复任务自动创建逻辑
4. 添加待办统计（今日待办、本周待办等）
5. 添加待办提醒功能（结合定时任务）
6. 支持子任务（待办项下的检查清单）
